import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final

from wii_arena.dolphin import (
    Dolphin,
    DolphinAction,
    DolphinFrameBuffer,
    DolphinGameCubeControllerInput,
    DolphinGameCubeControllerNoOp,
    DolphinMemoryView,
)

from ..telemetry.functions import (
    focused_page,
    read_joined_player_count,
    read_menu_state,
    read_race_stage,
    read_rules_page,
    read_selected_entry,
    seat_is_choosing,
)
from ..telemetry.models import MenuState, RulesPage
from ..telemetry.services import GuestMemory, GuestMemoryAddressError
from ..telemetry.types import GuestAddress, KartIndex, RacerCount
from .models import CHARACTER_SIZES, RaceConfiguration
from .types import (
    Cc,
    Character,
    Course,
    CourseRule,
    Cpu,
    Cup,
    DriftMode,
    ItemRule,
    PlayerSeat,
    Races,
    Vehicle,
    VehicleRule,
    VehicleSize,
)

_LOGGER = logging.getLogger(__name__)


class MenuNavigationError(RuntimeError): ...


class MenuNavigationTimeoutError(MenuNavigationError): ...


class DriftPageUnrecognisedError(MenuNavigationError): ...


class MenuTargetMissedError(MenuNavigationError): ...


class MenuPageUnreadableError(MenuNavigationError): ...


class RulesNotTakenError(MenuNavigationError): ...


CURSOR_NUDGE_FRAMES: Final[int] = 45
RULE_SETTLE_FRAMES: Final[int] = 80
BOOT_SETTLE_FRAMES: Final[int] = 900
BOOT_CONFIRM_FRAMES: Final[int] = 600

_BOOT_PAGES_TO_CLEAR: Final[int] = 7

_A = DolphinGameCubeControllerInput(a=True)
_UP = DolphinGameCubeControllerInput(up=True)
_DOWN = DolphinGameCubeControllerInput(down=True)
_LEFT = DolphinGameCubeControllerInput(left=True)
_RIGHT = DolphinGameCubeControllerInput(right=True)


def _to_action(inputs: dict[int, DolphinGameCubeControllerInput]) -> DolphinAction:
    return [
        inputs.get(1, DolphinGameCubeControllerNoOp()),
        inputs.get(2, DolphinGameCubeControllerNoOp()),
        inputs.get(3, DolphinGameCubeControllerNoOp()),
        inputs.get(4, DolphinGameCubeControllerNoOp()),
    ]


MenuCondition = Callable[[Dolphin.Session], bool]

_MENU_SETTLED_STATE: Final[int] = 4

_SECTION_IDLE_STATE: Final[int] = 0


_TOP_MENU_PAGE: Final[int] = 90

_SINGLE_PLAYER_PAGE: Final[int] = 105

_JOIN_PAGE: Final[int] = 98

_MULTIPLAYER_PAGE: Final[int] = 128

_VS_HUB_PAGE: Final[int] = 114

_RULES_PAGE: Final[int] = 115

_CHARACTER_PAGE: Final[int] = 107

_VEHICLE_PAGE: Final[int] = 129

_SOLO_VEHICLE_PAGE: Final[int] = 108

_CUP_PAGE: Final[int] = 110

_COURSE_PAGE: Final[int] = 111

_COURSE_CONFIRM_PAGE: Final[int] = 75

_DRIFT_PAGE: Final[int] = 130

_SOLO_DRIFT_PAGE: Final[int] = 109

_CONDITION_HOLD_FRAMES: Final[int] = 15

_PRESS_FRAMES: Final[int] = 3


class _MenuSession(Dolphin.Session):
    def __init__(self, session: Dolphin.Session, deadline: float) -> None:
        self._session = session
        self._deadline = deadline
        self._frames = 0

    @property
    def frames(self) -> int:
        return self._frames

    def execute(self, action: DolphinAction) -> None:
        self._session.execute(action)
        self._frames += 1
        if time.monotonic() >= self._deadline:
            state = _menu_state(self)
            raise MenuNavigationTimeoutError(
                f"The menus did not reach the race within the session's time, "
                f"after {self._frames} frames on page "
                f"{state.page_id if state is not None else 'unknown'}"
            )

    def memory_view(self) -> DolphinMemoryView:
        return self._session.memory_view()

    @contextmanager
    def frame_buffer(self) -> Generator[list[DolphinFrameBuffer], None, None]:
        with self._session.frame_buffer() as screens:
            yield screens


def _vehicle_page(num_racers: int) -> int:
    return _SOLO_VEHICLE_PAGE if num_racers == 1 else _VEHICLE_PAGE


def _page_settles(page_id: int) -> MenuCondition:
    """The course page is born settled and swallows presses for the twenty or
    so frames it spends sliding in."""

    def condition(session: Dolphin.Session) -> bool:
        state = _menu_state(session)
        return (
            state is not None
            and state.page_id == page_id
            and state.page_state == _MENU_SETTLED_STATE
            and state.accepts_input
        )

    return condition


def _page_closes(page_id: int) -> MenuCondition:

    def condition(session: Dolphin.Session) -> bool:
        state = _menu_state(session)
        return (
            state is not None
            and state.page_id == page_id
            and state.page_state != _MENU_SETTLED_STATE
        )

    return condition


def _another_page_settles(before: MenuState | None) -> MenuCondition:

    def condition(session: Dolphin.Session) -> bool:
        state = _menu_state(session)
        if state is None or state.page_state != _MENU_SETTLED_STATE:
            return False
        if not state.accepts_input:
            return False
        if state.section_lifecycle_state != _SECTION_IDLE_STATE:
            return False
        return before is None or state.page_id != before.page_id

    return condition


def _seat_is_choosing(session: Dolphin.Session, seat: int) -> bool | None:
    try:
        return seat_is_choosing(GuestMemory(session.memory_view()), seat)
    except GuestMemoryAddressError:
        return None


def _seat_confirms(session: Dolphin.Session, seat: int, page_id: int) -> MenuCondition:
    before = _seat_is_choosing(session, seat)

    def condition(session: Dolphin.Session) -> bool:
        state = _menu_state(session)
        if state is None or before is not True:
            return False
        if state.page_id != page_id:
            return state.page_state == _MENU_SETTLED_STATE and state.accepts_input
        return (
            state.page_state == _MENU_SETTLED_STATE
            and _seat_is_choosing(session, seat) is False
        )

    return condition


CursorReader = Callable[[Dolphin.Session, int], int | None]

_VEHICLE_CURSOR_OFFSET: Final[int] = 0xF94

_VEHICLE_CURSOR_STRIDE: Final[int] = 0x5C8

_CHARACTER_CURSOR_OFFSET: Final[int] = 0x838

_CHARACTER_CURSOR_STRIDE: Final[int] = 0x04


def _seat_cursor(
    session: Dolphin.Session, seat: int, offset: int, stride: int
) -> int | None:
    try:
        memory = GuestMemory(session.memory_view())
        page = focused_page(memory)
        if page is None:
            return None
        return memory.s32(GuestAddress(page + offset + stride * (seat - 1)))
    except GuestMemoryAddressError:
        return None


def _vehicle_cursor(session: Dolphin.Session, seat: int) -> int | None:
    return _seat_cursor(session, seat, _VEHICLE_CURSOR_OFFSET, _VEHICLE_CURSOR_STRIDE)


def _character_cursor(session: Dolphin.Session, seat: int) -> int | None:
    return _seat_cursor(
        session, seat, _CHARACTER_CURSOR_OFFSET, _CHARACTER_CURSOR_STRIDE
    )


def _joined_players(session: Dolphin.Session, _seat: int) -> int | None:
    state = _menu_state(session)
    if state is None or state.page_id != _JOIN_PAGE:
        return None
    try:
        return read_joined_player_count(GuestMemory(session.memory_view()))
    except GuestMemoryAddressError:
        return None


def _selected_entry(page_id: int) -> CursorReader:

    def read(session: Dolphin.Session, seat: int) -> int | None:
        state = _menu_state(session)
        if state is None or state.page_id != page_id:
            return None
        try:
            return read_selected_entry(GuestMemory(session.memory_view()), seat)
        except GuestMemoryAddressError:
            return None

    return read


def _cursor_moves(
    cursor: CursorReader, session: Dolphin.Session, seat: int
) -> MenuCondition:
    before = cursor(session, seat)

    def condition(session: Dolphin.Session) -> bool:
        current = cursor(session, seat)
        return current is not None and current != before

    return condition


def _press_until(
    session: Dolphin.Session,
    seat: int,
    toward: DolphinGameCubeControllerInput,
    *,
    cursor: CursorReader,
    target: int,
    presses: int,
    waiting_for: str,
    nudge_frames: int = CURSOR_NUDGE_FRAMES,
) -> None:
    budget = presses * (nudge_frames + _PRESS_FRAMES)
    seen: list[int | None] = [cursor(session, seat)]
    while budget > 0 and seen[-1] != target:
        budget -= _click(
            session,
            {seat: toward},
            idle_frames=min(nudge_frames, budget),
            until=_cursor_moves(cursor, session, seat),
            waiting_for=waiting_for,
        )
        seen.append(cursor(session, seat))

    if seen[-1] != target:
        raise MenuTargetMissedError(
            f"{waiting_for} was left on {seen[-1]} rather than {target} after "
            f"{presses * (nudge_frames + _PRESS_FRAMES)} frames, having read {seen}"
        )


def _menu_state(session: Dolphin.Session) -> MenuState | None:
    try:
        return read_menu_state(GuestMemory(session.memory_view()))
    except GuestMemoryAddressError:
        return None


def _idle_action() -> DolphinAction:
    return [
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
    ]


def _blind_click(
    session: Dolphin.Session,
    inputs: dict[int, DolphinGameCubeControllerInput],
    idle_frames: int,
) -> None:
    action = _to_action(inputs)
    idle_action = _idle_action()
    for _ in range(_PRESS_FRAMES):
        session.execute(action)
    for _ in range(idle_frames):
        session.execute(idle_action)


def _click(
    session: Dolphin.Session,
    inputs: dict[int, DolphinGameCubeControllerInput],
    *,
    until: MenuCondition,
    idle_frames: int | None = None,
    waiting_for: str = "",
) -> int:
    action = _to_action(inputs)
    idle_action = _idle_action()
    spent = 0
    for _ in range(_PRESS_FRAMES):
        session.execute(action)
        spent += 1

    held_page: int | None = None
    held_frames = 0
    while idle_frames is None or spent - _PRESS_FRAMES < idle_frames:
        session.execute(idle_action)
        spent += 1
        state = _menu_state(session)
        if state is None or not until(session):
            held_page, held_frames = None, 0
            continue
        if state.page_id != held_page:
            held_page, held_frames = state.page_id, 0
        held_frames += 1
        if held_frames >= _CONDITION_HOLD_FRAMES:
            return spent

    _LOGGER.debug("%s had not registered after %d frames", waiting_for, idle_frames)
    return spent


_SINGLE_PLAYER_MENU: tuple[str, ...] = (
    "Grand Prix",
    "Time Trials",
    "VS Race",
    "Battle",
)
_MULTIPLAYER_MENU: tuple[str, ...] = ("VS Race", "Battle")

_VS_HUB_MENU: tuple[str, ...] = ("Solo Race", "Team Race", "Rules")


CHARACTER_POSITION_MAP: dict[Character, tuple[int, int]] = {
    "Baby Mario": (0, 0),
    "Baby Luigi": (0, 1),
    "Baby Peach": (0, 2),
    "Baby Daisy": (0, 3),
    "Toad": (1, 0),
    "Toadette": (1, 1),
    "Koopa Troopa": (1, 2),
    "Dry Bones": (1, 3),
    "Mario": (2, 0),
    "Luigi": (2, 1),
    "Peach": (2, 2),
    "Daisy": (2, 3),
    "Yoshi": (3, 0),
    "Birdo": (3, 1),
    "Diddy Kong": (3, 2),
    "Bowser Jr": (3, 3),
    "Wario": (4, 0),
    "Waluigi": (4, 1),
    "Donkey Kong": (4, 2),
    "Bowser": (4, 3),
    "King Boo": (5, 0),
    "Rosalina": (5, 1),
    "Funky Kong": (5, 2),
    "Dry Bowser": (5, 3),
}

CHARACTER_ID_MAP: dict[Character, int] = {
    "Mario": 0,
    "Baby Peach": 1,
    "Waluigi": 2,
    "Bowser": 3,
    "Baby Daisy": 4,
    "Dry Bones": 5,
    "Baby Mario": 6,
    "Luigi": 7,
    "Toad": 8,
    "Donkey Kong": 9,
    "Yoshi": 10,
    "Wario": 11,
    "Baby Luigi": 12,
    "Toadette": 13,
    "Koopa Troopa": 14,
    "Daisy": 15,
    "Peach": 16,
    "Birdo": 17,
    "Diddy Kong": 18,
    "King Boo": 19,
    "Bowser Jr": 20,
    "Dry Bowser": 21,
    "Funky Kong": 22,
    "Rosalina": 23,
}

_SHARED_ROW = max(row for row, _ in CHARACTER_POSITION_MAP.values()) + 1
_SHARED_COLUMN = max(column for _, column in CHARACTER_POSITION_MAP.values())

_CHARACTER_AT: dict[tuple[int, int], Character] = {
    position: character for character, position in CHARACTER_POSITION_MAP.items()
}

_CHARACTER_DEFAULTS: dict[int, Character] = {
    1: "Mario",
    2: "Luigi",
    3: "Yoshi",
    4: "Peach",
}

VEHICLE_CHOICE_QUEUE: dict[VehicleSize, list[Vehicle]] = {
    "small": [
        "Standard Kart S",
        "Baby Booster",
        "Concerto",
        "Cheep Charger",
        "Rally Romper",
        "Blue Falcon",
        "Standard Bike S",
        "Bullet Bike",
        "Nanobike",
        "Quacker",
        "Magikruiser",
        "Bubble Bike",
    ],
    "medium": [
        "Standard Kart M",
        "Nostalgia 1",
        "Wild Wing",
        "Turbo Blooper",
        "Royal Racer",
        "B Dasher MK 2",
        "Standard Bike M",
        "Mach Bike",
        "Bon Bon",
        "Rapide",
        "Nitrocycle",
        "Dolphin Dasher",
    ],
    "large": [
        "Standard Kart L",
        "Offroader",
        "Flame Flyer",
        "Piranha Prowler",
        "Aero Glider",
        "Dragonetti",
        "Standard Bike L",
        "Bowser Bike",
        "Wario Bike",
        "Twinkle Star",
        "Torpedo",
        "Phantom",
    ],
}

_VEHICLE_GRID_ROW_COUNT: Final[int] = 6

_VEHICLE_KIND_STRIDE: Final[int] = 18

_VEHICLE_SIZE_ORDER: Final[tuple[VehicleSize, ...]] = ("small", "medium", "large")


def _vehicle_position(entry: int) -> tuple[int, int]:
    return entry % _VEHICLE_GRID_ROW_COUNT, entry // _VEHICLE_GRID_ROW_COUNT


def _vehicle_identifier(size: VehicleSize, entry: int) -> int:
    row, column = _vehicle_position(entry)
    return (
        _VEHICLE_KIND_STRIDE * column
        + len(_VEHICLE_SIZE_ORDER) * row
        + _VEHICLE_SIZE_ORDER.index(size)
    )


VEHICLE_POSITION_MAP: dict[Vehicle, tuple[int, int]] = {
    vehicle: _vehicle_position(entry)
    for queue in VEHICLE_CHOICE_QUEUE.values()
    for entry, vehicle in enumerate(queue)
}

VEHICLE_ID_MAP: dict[Vehicle, int] = {
    vehicle: _vehicle_identifier(size, entry)
    for size, queue in VEHICLE_CHOICE_QUEUE.items()
    for entry, vehicle in enumerate(queue)
}

_CUP_COLUMN_COUNT: Final[int] = 4

_CUP_ROW_COUNT: Final[int] = 2


def _cup_identifier(row: int, column: int) -> int:
    return row * _CUP_COLUMN_COUNT + column


CUP_POSITION_MAP: dict[Cup, tuple[int, int]] = {
    "Mushroom Cup": (0, 0),
    "Flower Cup": (0, 1),
    "Star Cup": (0, 2),
    "Special Cup": (0, 3),
    "Shell Cup": (1, 0),
    "Banana Cup": (1, 1),
    "Leaf Cup": (1, 2),
    "Lightning Cup": (1, 3),
}

COURSE_POSITION_MAP: dict[Course, int] = {
    "Luigi Circuit": 0,
    "Moo Moo Meadows": 1,
    "Mushroom Gorge": 2,
    "Toad's Factory": 3,
    "Mario Circuit": 0,
    "Coconut Mall": 1,
    "DK Summit": 2,
    "Wario's Gold Mine": 3,
    "Daisy Circuit": 0,
    "Koopa Cape": 1,
    "Maple Treeway": 2,
    "Grumble Volcano": 3,
    "Dry Dry Ruins": 0,
    "Moonview Highway": 1,
    "Bowser's Castle": 2,
    "Rainbow Road": 3,
    "GCN Peach Beach": 0,
    "DS Yoshi Falls": 1,
    "SNES Ghost Valley 2": 2,
    "N64 Mario Raceway": 3,
    "N64 Sherbet Land": 0,
    "GBA Shy Guy Beach": 1,
    "DS Delfino Square": 2,
    "GCN Waluigi Stadium": 3,
    "DS Desert Street": 0,
    "GBA Bowser Castle 3": 1,
    "N64 DK's Jungle Parkway": 2,
    "GCN Mario Circuit": 3,
    "SNES Mario Circuit 3": 0,
    "DS Peach Gardens": 1,
    "GCN DK Mountain": 2,
    "N64 Bowser's Castle": 3,
}

COURSE_ID_MAP: dict[Course, int] = {
    "Luigi Circuit": 8,
    "Moo Moo Meadows": 1,
    "Mushroom Gorge": 2,
    "Toad's Factory": 4,
    "Mario Circuit": 0,
    "Coconut Mall": 5,
    "DK Summit": 6,
    "Wario's Gold Mine": 7,
    "Daisy Circuit": 9,
    "Koopa Cape": 15,
    "Maple Treeway": 11,
    "Grumble Volcano": 3,
    "Dry Dry Ruins": 14,
    "Moonview Highway": 10,
    "Bowser's Castle": 12,
    "Rainbow Road": 13,
    "GCN Peach Beach": 16,
    "DS Yoshi Falls": 20,
    "SNES Ghost Valley 2": 25,
    "N64 Mario Raceway": 26,
    "N64 Sherbet Land": 27,
    "GBA Shy Guy Beach": 31,
    "DS Delfino Square": 23,
    "GCN Waluigi Stadium": 18,
    "DS Desert Street": 21,
    "GBA Bowser Castle 3": 30,
    "N64 DK's Jungle Parkway": 29,
    "GCN Mario Circuit": 17,
    "SNES Mario Circuit 3": 24,
    "DS Peach Gardens": 22,
    "GCN DK Mountain": 19,
    "N64 Bowser's Castle": 28,
}

_COURSES_PER_CUP: Final[int] = 4


COURSE_TO_CUP_MAP: dict[Course, Cup] = {
    "Luigi Circuit": "Mushroom Cup",
    "Moo Moo Meadows": "Mushroom Cup",
    "Mushroom Gorge": "Mushroom Cup",
    "Toad's Factory": "Mushroom Cup",
    "Mario Circuit": "Flower Cup",
    "Coconut Mall": "Flower Cup",
    "DK Summit": "Flower Cup",
    "Wario's Gold Mine": "Flower Cup",
    "Daisy Circuit": "Star Cup",
    "Koopa Cape": "Star Cup",
    "Maple Treeway": "Star Cup",
    "Grumble Volcano": "Star Cup",
    "Dry Dry Ruins": "Special Cup",
    "Moonview Highway": "Special Cup",
    "Bowser's Castle": "Special Cup",
    "Rainbow Road": "Special Cup",
    "GCN Peach Beach": "Shell Cup",
    "DS Yoshi Falls": "Shell Cup",
    "SNES Ghost Valley 2": "Shell Cup",
    "N64 Mario Raceway": "Shell Cup",
    "N64 Sherbet Land": "Banana Cup",
    "GBA Shy Guy Beach": "Banana Cup",
    "DS Delfino Square": "Banana Cup",
    "GCN Waluigi Stadium": "Banana Cup",
    "DS Desert Street": "Leaf Cup",
    "GBA Bowser Castle 3": "Leaf Cup",
    "N64 DK's Jungle Parkway": "Leaf Cup",
    "GCN Mario Circuit": "Leaf Cup",
    "SNES Mario Circuit 3": "Lightning Cup",
    "DS Peach Gardens": "Lightning Cup",
    "GCN DK Mountain": "Lightning Cup",
    "N64 Bowser's Castle": "Lightning Cup",
}


def kart_of_seat(seat: PlayerSeat) -> KartIndex:
    return KartIndex(seat - 1)


def racer_count_of(configuration: RaceConfiguration) -> RacerCount:
    if configuration.cpu == "off":
        return RacerCount(len(configuration.racers))
    return RacerCount(VS_RACE_GRID_SIZE)


def first_course_of_cup(cup: Cup) -> Course:
    for course, course_cup in COURSE_TO_CUP_MAP.items():
        if course_cup == cup and COURSE_POSITION_MAP[course] == 0:
            return course
    raise ValueError(f"{cup} has no course at the first grid position.")


_CC_ORDER: tuple[Cc, ...] = (50, 100, 150, "mirror")
_CPU_ORDER: tuple[Cpu, ...] = ("easy", "normal", "hard", "off")

_SOLO_CPU_ORDER: tuple[Cpu, ...] = ("easy", "normal", "hard")

_VEHICLE_RULE_ORDER: tuple[VehicleRule, ...] = ("all", "karts", "bikes")
_COURSE_RULE_ORDER: tuple[CourseRule, ...] = ("choose", "random", "in order")
_ITEM_RULE_ORDER: tuple[ItemRule, ...] = ("recommended", "frantic", "basic", "none")
_RACES_ORDER: tuple[Races, ...] = (2, 3, 4, 5, 8, 10, 12, 16, 32)

_MENU_SEAT: Final[int] = 1

VS_RACE_GRID_SIZE: Final[int] = 12


def navigate(
    session: Dolphin.Session,
    configuration: RaceConfiguration,
    deadline: float,
) -> None:
    menus = _MenuSession(session, deadline)
    racers = configuration.racers
    num_racers = len(racers)

    _LOGGER.info(
        "Navigating menus for num_racers=%d, course=%s",
        num_racers,
        configuration.course,
    )
    _enter_main_menu(menus, num_racers)

    _press_until(
        menus,
        _MENU_SEAT,
        _RIGHT,
        cursor=_selected_entry(_TOP_MENU_PAGE),
        target=num_racers - 1,
        presses=num_racers - 1,
        waiting_for="the racer count",
    )
    _click(
        menus,
        {1: _A},
        until=_another_page_settles(_menu_state(menus)),
        waiting_for="the page the racer count opens",
    )

    if num_racers == 1:
        _press_until(
            menus,
            _MENU_SEAT,
            _DOWN,
            cursor=_selected_entry(_SINGLE_PLAYER_PAGE),
            target=_SINGLE_PLAYER_MENU.index("VS Race"),
            presses=len(_SINGLE_PLAYER_MENU),
            waiting_for="VS Race on the single-player menu",
        )
    else:
        joining = _menu_state(menus)
        for player in range(2, num_racers):
            _press_until(
                menus,
                player,
                _A,
                cursor=_joined_players,
                target=player,
                presses=1,
                waiting_for=f"player {player} joining",
            )
        _click(
            menus,
            {num_racers: _A},
            until=_another_page_settles(joining),
            waiting_for="the page the last guest's press opens",
        )
        _click(
            menus,
            {1: _A},
            until=_page_settles(_MULTIPLAYER_PAGE),
            waiting_for="the multiplayer menu",
        )
        _press_until(
            menus,
            _MENU_SEAT,
            _UP,
            cursor=_selected_entry(_MULTIPLAYER_PAGE),
            target=_MULTIPLAYER_MENU.index("VS Race"),
            presses=len(_MULTIPLAYER_MENU) - 1,
            waiting_for="VS Race on the multiplayer menu",
        )

    _click(
        menus,
        {1: _A},
        until=_page_settles(_VS_HUB_PAGE),
        waiting_for="the VS race menu",
    )

    _walk_vs_hub(menus, "Rules", _UP)
    _click(
        menus,
        {1: _A},
        until=_page_settles(_RULES_PAGE),
        waiting_for="the rules page",
    )
    _select_rules(menus, configuration)

    _walk_vs_hub(menus, "Solo Race", _DOWN)
    _click(
        menus,
        {1: _A},
        until=_page_settles(_CHARACTER_PAGE),
        waiting_for="the character page",
    )

    _select_character(menus, configuration)

    _select_vehicle(menus, configuration)

    for player in range(1, num_racers + 1):
        _select_drift_mode(menus, player, racers[player - 1].drift_mode)
        _confirm_drift(menus, player)
    _click(
        menus,
        {},
        until=_page_settles(_CUP_PAGE),
        waiting_for="the cup page",
    )

    _select_cup(menus, configuration)

    _select_course(menus, configuration)

    _wait_for_race(menus, len(racers))

    _LOGGER.info("Navigated to the race in %d frames", menus.frames)


def _enter_main_menu(session: Dolphin.Session, num_racers: int) -> None:
    all_a = {player: _A for player in range(1, num_racers + 1)}
    _blind_click(session, {}, BOOT_SETTLE_FRAMES)
    _blind_click(session, all_a, BOOT_CONFIRM_FRAMES)

    for _ in range(_BOOT_PAGES_TO_CLEAR):
        _click(
            session,
            all_a,
            until=_another_page_settles(_menu_state(session)),
            waiting_for="the next boot page",
        )


def _rules_page(session: Dolphin.Session) -> RulesPage | None:
    state = _menu_state(session)
    if state is None or state.page_id != _RULES_PAGE:
        return None
    try:
        return read_rules_page(GuestMemory(session.memory_view()))
    except GuestMemoryAddressError:
        return None


def _rule_option_reader(row: int) -> CursorReader:

    def read(session: Dolphin.Session, _seat: int) -> int | None:
        page = _rules_page(session)
        if page is None or page.focused_row != row:
            return None
        return page.option_of(row)

    return read


def _rule_is_taken(row: int) -> MenuCondition:

    def condition(session: Dolphin.Session) -> bool:
        page = _rules_page(session)
        return page is not None and page.focused_row != row

    return condition


def _rule_walk(
    option: int, target: int, option_count: int
) -> tuple[DolphinGameCubeControllerInput, int]:
    rightward = (target - option) % option_count
    if rightward <= option_count - rightward:
        return _RIGHT, rightward
    return _LEFT, option_count - rightward


def _rule_position(
    session: Dolphin.Session, row: int, option_count: int, waiting_for: str
) -> int:
    page = _rules_page(session)
    if page is None or page.focused_row != row:
        raise MenuPageUnreadableError(f"{waiting_for} could not be read")

    offered = page.option_count_of(row)
    if offered != option_count:
        raise MenuPageUnreadableError(
            f"{waiting_for} offers {offered} options, not the {option_count} "
            f"the macros name"
        )

    option = page.option_of(row)
    if not 0 <= option < offered:
        raise MenuPageUnreadableError(
            f"{waiting_for} reads option {option}, which is not one of its {offered}"
        )
    return option


def _select_rule(
    session: Dolphin.Session, row: int, order: tuple[object, ...], selected_rule: object
) -> object | None:
    waiting_for = f"the rules page's row {row}"
    target = order.index(selected_rule)
    option = _rule_position(session, row, len(order), waiting_for)
    toward, presses = _rule_walk(option, target, len(order))
    _press_until(
        session,
        _MENU_SEAT,
        toward,
        cursor=_rule_option_reader(row),
        target=target,
        presses=presses,
        nudge_frames=RULE_SETTLE_FRAMES,
        waiting_for=waiting_for,
    )
    taken = _rule_option_reader(row)(session, _MENU_SEAT)
    _click(
        session,
        {_MENU_SEAT: _A},
        until=_rule_is_taken(row),
        waiting_for=f"{waiting_for} to be taken",
    )
    if taken is None or not 0 <= taken < len(order):
        return None
    return order[taken]


def _walk_vs_hub(
    session: Dolphin.Session, entry: str, toward: DolphinGameCubeControllerInput
) -> None:
    _press_until(
        session,
        _MENU_SEAT,
        toward,
        cursor=_selected_entry(_VS_HUB_PAGE),
        target=_VS_HUB_MENU.index(entry),
        presses=len(_VS_HUB_MENU),
        waiting_for=f"{entry} on the VS race menu",
    )


def _select_rules(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    rules: tuple[tuple[tuple[object, ...], object], ...] = (
        (_CC_ORDER, configuration.cc),
        (
            _CPU_ORDER if len(configuration.racers) > 1 else _SOLO_CPU_ORDER,
            configuration.cpu,
        ),
        (_VEHICLE_RULE_ORDER, configuration.vehicle_rule),
        (_COURSE_RULE_ORDER, configuration.course_rule),
        (_ITEM_RULE_ORDER, configuration.item_rule),
        (_RACES_ORDER, configuration.races),
    )

    taken = [
        _select_rule(session, row, order, selected_rule)
        for row, (order, selected_rule) in enumerate(rules)
    ]
    wanted = [selected_rule for _, selected_rule in rules]
    if taken != wanted:
        raise RulesNotTakenError(f"the rules page took {taken} rather than {wanted}")
    _LOGGER.info("The rules page was left on %s", taken)

    _click(
        session,
        {_MENU_SEAT: _A},
        until=_page_settles(_VS_HUB_PAGE),
        waiting_for="the VS race menu the rules close onto",
    )


def _nudge_character(
    session: Dolphin.Session, seat: int, toward: DolphinGameCubeControllerInput
) -> None:
    _click(
        session,
        {seat: toward},
        until=_cursor_moves(_character_cursor, session, seat),
        waiting_for=f"seat {seat}'s character cursor",
    )


def _walk_character(
    session: Dolphin.Session,
    seat: int,
    toward: DolphinGameCubeControllerInput,
    onto: Character,
    presses: int,
) -> None:
    _press_until(
        session,
        seat,
        toward,
        cursor=_character_cursor,
        target=CHARACTER_ID_MAP[onto],
        presses=presses,
        waiting_for=f"seat {seat}'s character cursor on {onto}",
    )


def _confirm_character(session: Dolphin.Session, seat: int) -> None:
    _click(
        session,
        {seat: _A},
        until=_seat_confirms(session, seat, _CHARACTER_PAGE),
        waiting_for=f"seat {seat}'s character confirmation",
    )


def _select_character(
    session: Dolphin.Session, configuration: RaceConfiguration
) -> None:
    racers = configuration.racers
    num_racers = len(racers)

    last_row = _SHARED_ROW - 1
    for player in reversed(range(1, num_racers + 1)):
        row, column = CHARACTER_POSITION_MAP[_CHARACTER_DEFAULTS[player]]
        _walk_character(
            session,
            player,
            _RIGHT,
            _CHARACTER_AT[row, _SHARED_COLUMN],
            _SHARED_COLUMN - column,
        )
        _walk_character(
            session,
            player,
            _DOWN,
            _CHARACTER_AT[last_row, _SHARED_COLUMN],
            last_row - row,
        )
        _nudge_character(session, player, _DOWN)

    for player in sorted(
        range(1, num_racers + 1),
        key=lambda seat: CHARACTER_POSITION_MAP[racers[seat - 1].character],
    ):
        character = racers[player - 1].character
        row, column = CHARACTER_POSITION_MAP[character]
        _walk_character(
            session, player, _UP, _CHARACTER_AT[row, _SHARED_COLUMN], _SHARED_ROW - row
        )
        _walk_character(session, player, _LEFT, character, _SHARED_COLUMN - column)
        _confirm_character(session, player)

    _click(
        session,
        {},
        until=_page_settles(_vehicle_page(num_racers)),
        waiting_for="the vehicle page",
    )


def _confirm_vehicle(session: Dolphin.Session, seat: int, page_id: int) -> None:
    _click(
        session,
        {seat: _A},
        until=_seat_confirms(session, seat, page_id),
        waiting_for=f"seat {seat}'s vehicle confirmation",
    )


def _select_vehicle(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    racers = configuration.racers
    num_racers = len(racers)
    is_grid = num_racers == 1
    for player in range(1, num_racers + 1):
        selected_vehicle = racers[player - 1].vehicle
        target_size = CHARACTER_SIZES[racers[player - 1].character]

        if is_grid:
            target_row, target_column = VEHICLE_POSITION_MAP[selected_vehicle]
            cursor = _selected_entry(_SOLO_VEHICLE_PAGE)
            _press_until(
                session,
                player,
                _DOWN,
                cursor=cursor,
                target=VEHICLE_ID_MAP[VEHICLE_CHOICE_QUEUE[target_size][target_row]],
                presses=_VEHICLE_GRID_ROW_COUNT,
                waiting_for=f"seat {player}'s vehicle row",
            )
            _press_until(
                session,
                player,
                _RIGHT if target_column > 0 else _LEFT,
                cursor=cursor,
                target=VEHICLE_ID_MAP[selected_vehicle],
                presses=1,
                waiting_for=f"seat {player}'s {selected_vehicle}",
            )
            _confirm_vehicle(session, player, _vehicle_page(num_racers))

        else:
            entry = VEHICLE_CHOICE_QUEUE[target_size].index(selected_vehicle)
            _press_until(
                session,
                player,
                _RIGHT,
                cursor=_vehicle_cursor,
                target=entry,
                presses=entry,
                waiting_for=f"seat {player}'s vehicle cursor",
            )
            _confirm_vehicle(session, player, _vehicle_page(num_racers))


def _drift_entry(page_id: int, seat: int, mode: DriftMode) -> int | None:
    if page_id == _DRIFT_PAGE:
        return 2 * (seat - 1) + (0 if mode == "automatic" else 1)
    if page_id == _SOLO_DRIFT_PAGE:
        return 1 if mode == "automatic" else 0
    return None


def _select_drift_mode(session: Dolphin.Session, seat: int, mode: DriftMode) -> None:
    state = _menu_state(session)
    target = None if state is None else _drift_entry(state.page_id, seat, mode)
    if state is None or target is None:
        raise DriftPageUnrecognisedError(
            f"seat {seat} was left on "
            f"{'no page at all' if state is None else f'page {state.page_id}'}, "
            f"which is neither of the drift pages ({_DRIFT_PAGE} and "
            f"{_SOLO_DRIFT_PAGE}), so the entry its {mode} drift sits at cannot "
            f"be named"
        )
    _press_until(
        session,
        seat,
        _UP if mode == "automatic" else _DOWN,
        cursor=_selected_entry(state.page_id),
        target=target,
        presses=1,
        waiting_for=f"seat {seat}'s drift cursor",
    )


def _confirm_drift(session: Dolphin.Session, seat: int) -> None:
    state = _menu_state(session)
    if state is None:
        raise MenuPageUnreadableError(
            f"seat {seat}'s drift confirmation cannot name the page it is made on"
        )
    _click(
        session,
        {seat: _A},
        until=_seat_confirms(session, seat, state.page_id),
        waiting_for=f"seat {seat}'s drift confirmation",
    )


def _select_cup(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    cup = COURSE_TO_CUP_MAP[configuration.course]
    target_row, target_column = CUP_POSITION_MAP[cup]
    cursor = _selected_entry(_CUP_PAGE)
    opened_on = cursor(session, _MENU_SEAT)
    if opened_on is None:
        raise MenuPageUnreadableError(
            "the cup page could not be read, so the column to walk down is unknown"
        )
    column = opened_on % _CUP_COLUMN_COUNT

    _press_until(
        session,
        _MENU_SEAT,
        _DOWN,
        cursor=cursor,
        target=_cup_identifier(target_row, column),
        presses=_CUP_ROW_COUNT,
        waiting_for=f"the {cup}'s row",
    )
    _press_until(
        session,
        _MENU_SEAT,
        _RIGHT,
        cursor=cursor,
        target=_cup_identifier(target_row, target_column),
        presses=_CUP_COLUMN_COUNT,
        waiting_for=f"the {cup}",
    )

    _click(
        session,
        {1: _A},
        until=_page_settles(_COURSE_PAGE),
        waiting_for="the course page",
    )


def _select_course(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    _press_until(
        session,
        _MENU_SEAT,
        _DOWN,
        cursor=_selected_entry(_COURSE_PAGE),
        target=COURSE_ID_MAP[configuration.course],
        presses=_COURSES_PER_CUP,
        waiting_for=f"the {configuration.course}",
    )
    _click(
        session,
        {1: _A},
        until=_page_settles(_COURSE_CONFIRM_PAGE),
        waiting_for="the course confirmation",
    )
    _click(
        session,
        {1: _A},
        until=_page_closes(_COURSE_CONFIRM_PAGE),
        waiting_for="the course confirmation to close",
    )


def _race_stage(session: Dolphin.Session) -> int | None:
    try:
        return read_race_stage(GuestMemory(session.memory_view()))
    except GuestMemoryAddressError:
        return None


def _wait_for_race(session: Dolphin.Session, num_racers: int) -> None:
    idle = _idle_action()
    while True:
        session.execute(idle)
        if _race_stage(session) is None:
            continue
        with session.frame_buffer() as screens:
            if len(screens) > num_racers:
                return
