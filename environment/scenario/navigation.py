import logging

from wii_arena.dolphin import (
    Dolphin,
    DolphinAction,
    DolphinGameCubeControllerInput,
    DolphinGameCubeControllerNoOp,
)

from .models import CHARACTER_SIZES, RaceConfiguration
from .types import (
    Cc,
    Character,
    Course,
    CourseRule,
    Cpu,
    ItemRule,
    Races,
    Vehicle,
    VehicleRule,
    VehicleSize,
)

_LOGGER = logging.getLogger(__name__)

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


def _click(
    session: Dolphin.Session,
    inputs: dict[int, DolphinGameCubeControllerInput],
    *,
    idle_frames: int = 250,
    press_frames: int = 3,
) -> None:
    action = _to_action(inputs)
    idle_action = [
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
    ]
    for _ in range(press_frames):
        session.execute(action)
    for _ in range(idle_frames):
        session.execute(idle_action)


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
    "Mii A": (6, 2),
    "Mii B": (6, 3),
}

_VEHICLE_CHOICE_GRID: dict[VehicleSize, dict[str, tuple[tuple[Vehicle, ...], ...]]] = {
    "small": {
        "kart": (
            ("Standard Kart S", "Baby Booster", "Concerto"),
            ("Cheep Charger", "Rally Romper", "Blue Falcon"),
        ),
        "bike": (
            ("Standard Bike S", "Bullet Bike", "Nanobike"),
            ("Quacker", "Magikruiser", "Bubble Bike"),
        ),
    },
    "medium": {
        "kart": (
            ("Standard Kart M", "Nostalgia 1", "Wild Wing"),
            ("Turbo Blooper", "B Dasher MK 2", "Royal Racer"),
        ),
        "bike": (
            ("Standard Bike M", "Mach Bike", "Bon Bon"),
            ("Rapide", "Nitrocycle", "Dolphin Dasher"),
        ),
    },
    "large": {
        "kart": (
            ("Standard Kart L", "Offroader", "Flame Flyer"),
            ("Piranha Prowler", "Aero Glider", "Dragonetti"),
        ),
        "bike": (
            ("Standard Bike L", "Bowser Bike", "Wario Bike"),
            ("Twinkle Star", "Torpedo", "Phantom"),
        ),
    },
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


def _build_vehicle_position_map() -> dict[Vehicle, tuple[int, int]]:
    result: dict[Vehicle, tuple[int, int]] = {}
    for size_grid in _VEHICLE_CHOICE_GRID.values():
        for ui_col, vehicle_type in ((0, "kart"), (1, "bike")):
            for block, column in enumerate(size_grid[vehicle_type]):
                for row, vehicle in enumerate(column):
                    result[vehicle] = (row + block * 3, ui_col)
    return result


VEHICLE_POSITION_MAP: dict[Vehicle, tuple[int, int]] = _build_vehicle_position_map()

CUP_POSITION_MAP: dict[str, tuple[int, int]] = {
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

COURSE_TO_CUP_MAP: dict[Course, str] = {
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

_CC_ORDER: tuple[Cc, ...] = (50, 100, 150, "mirror")
_CPU_ORDER: tuple[Cpu, ...] = ("easy", "normal", "hard", "off")
_VEHICLE_RULE_ORDER: tuple[VehicleRule, ...] = ("all", "karts", "bikes")
_COURSE_RULE_ORDER: tuple[CourseRule, ...] = ("choose", "random", "in order")
_ITEM_RULE_ORDER: tuple[ItemRule, ...] = ("recommended", "frantic", "basic", "none")
_RACES_ORDER: tuple[Races, ...] = (2, 3, 4, 5, 8, 10, 12, 16, 32)


def navigate(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    players = configuration.players
    num_agents = len(players)

    _LOGGER.info(
        "Navigating menus for num_agents=%d, course=%s",
        num_agents,
        configuration.course,
    )
    enter_main_menu(session, num_agents)

    if num_agents == 1:
        _click(session, {1: _A}, idle_frames=300)
        _click(session, {1: _DOWN}, idle_frames=10)
        _click(session, {1: _DOWN}, idle_frames=10)
        _click(
            session, {1: _A}, idle_frames=100
        )  # select VS Race in ["VS Race", "Battle"]
    else:
        for _ in range(3):
            _click(session, {1: _RIGHT}, idle_frames=10)
        _click(session, {1: _A})

        _click(session, {2: _A}, idle_frames=10)
        _click(session, {3: _A}, idle_frames=10)
        _click(session, {4: _A}, idle_frames=10)
        _click(session, {}, idle_frames=50)
        _click(session, {1: _A}, idle_frames=100)

        _click(
            session, {1: _A}, idle_frames=100
        )  # select VS Race in ["VS Race", "Battle"]

    # setting rules (CC, CPU, etc.)
    _click(session, {1: _UP}, idle_frames=10)
    _click(session, {1: _A}, idle_frames=100)
    select_rules(session, configuration)
    _click(session, {1: _DOWN}, idle_frames=10)

    if configuration.mode == "solo":
        _click(session, {1: _A})
    elif configuration.mode == "team":
        _click(session, {1: _DOWN}, idle_frames=10)
        _click(session, {1: _A})

    select_character(session, configuration)

    if configuration.mode == "team":
        if num_agents == 1:
            # Team select
            _click(session, {1: _A})
        else:
            # Team select (1, 3p select red team, 2, 4p select green team)
            _click(session, {1: _A, 2: _A, 3: _A, 4: _A})
            _click(session, {1: _A})

    select_vehicle(session, configuration)

    if num_agents == 1:
        if players[0].drift_mode == "automatic":
            _click(session, {1: _UP}, idle_frames=10)
            _click(session, {1: _A}, idle_frames=10)
        elif players[0].drift_mode == "manual":
            _click(session, {1: _A}, idle_frames=10)
    else:
        for player in range(1, num_agents + 1):
            if players[player - 1].drift_mode == "automatic":
                _click(session, {player: _A}, idle_frames=10)
            elif players[player - 1].drift_mode == "manual":
                _click(session, {player: _DOWN}, idle_frames=10)
                _click(session, {player: _A}, idle_frames=10)
    _click(session, {})

    select_cup(session, configuration)

    select_course(session, configuration)

    _click(session, {}, idle_frames=600)


def enter_main_menu(session: Dolphin.Session, num_agents: int) -> None:
    all_a = {player: _A for player in range(1, num_agents + 1)}
    _click(session, {}, idle_frames=800)
    _click(session, all_a, idle_frames=500)

    for _ in range(7):
        _click(session, all_a)


def select_character(
    session: Dolphin.Session, configuration: RaceConfiguration
) -> None:
    players = configuration.players
    num_agents = len(players)

    if num_agents == 4:
        _click(session, {4: _DOWN}, idle_frames=10)
        _click(session, {4: _DOWN}, idle_frames=10)
        _click(session, {4: _DOWN}, idle_frames=10)
        _click(session, {4: _DOWN}, idle_frames=10)
        _click(session, {4: _RIGHT}, idle_frames=10)

        _click(session, {3: _RIGHT}, idle_frames=10)
        _click(session, {3: _RIGHT}, idle_frames=10)
        _click(session, {3: _DOWN}, idle_frames=10)
        _click(session, {3: _DOWN}, idle_frames=10)
        _click(session, {3: _DOWN}, idle_frames=10)
        _click(session, {3: _RIGHT}, idle_frames=10)

        _click(session, {2: _RIGHT}, idle_frames=10)
        _click(session, {2: _DOWN}, idle_frames=10)
        _click(session, {2: _DOWN}, idle_frames=10)
        _click(session, {2: _DOWN}, idle_frames=10)
        _click(session, {2: _DOWN}, idle_frames=10)
        _click(session, {2: _RIGHT}, idle_frames=10)

    _click(session, {1: _RIGHT}, idle_frames=10)
    _click(session, {1: _RIGHT}, idle_frames=10)
    _click(session, {1: _DOWN}, idle_frames=10)
    _click(session, {1: _DOWN}, idle_frames=10)
    _click(session, {1: _DOWN}, idle_frames=10)
    _click(session, {1: _DOWN}, idle_frames=10)
    _click(session, {1: _RIGHT}, idle_frames=10)

    selected_coordinate: list[tuple[int, int]] = []
    selected_choices: list[tuple[int, int]] = []
    for player in range(1, num_agents + 1):
        coordinate = CHARACTER_POSITION_MAP[players[player - 1].character]
        selected_coordinate.append(coordinate)
        selected_choices.append((player, coordinate[0] * 4 + coordinate[1]))

    for player, _ in sorted(selected_choices, key=lambda x: x[1]):
        row, col = selected_coordinate[player - 1]
        for _ in range(6 - row):
            _click(session, {player: _UP}, idle_frames=10)
        for _ in range(3 - col):
            _click(session, {player: _LEFT}, idle_frames=10)
        _click(session, {player: _A}, idle_frames=10)

    _click(session, {})


def select_vehicle(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    players = configuration.players
    num_agents = len(players)
    is_grid = num_agents == 1
    for player in range(1, num_agents + 1):
        selected_vehicle = players[player - 1].vehicle

        if is_grid:
            target_row, target_col = VEHICLE_POSITION_MAP[selected_vehicle]

            vertical_move = _UP if target_row <= 0 else _DOWN
            for _ in range(abs(target_row)):
                _click(session, {player: vertical_move}, idle_frames=10)

            horizontal_move = _LEFT if target_col <= 0 else _RIGHT
            for _ in range(abs(target_col)):
                _click(session, {player: horizontal_move}, idle_frames=10)
            _click(session, {player: _A}, idle_frames=150)

        else:
            target_size = CHARACTER_SIZES[players[player - 1].character]
            for vehicle in VEHICLE_CHOICE_QUEUE[target_size]:
                _click(
                    session,
                    {player: DolphinGameCubeControllerInput()},
                    idle_frames=10,
                )
                if vehicle == selected_vehicle:
                    _click(session, {player: _A}, idle_frames=150)
                    break
                _click(session, {player: _RIGHT}, idle_frames=10)


def select_cup(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    target_row, target_col = CUP_POSITION_MAP[COURSE_TO_CUP_MAP[configuration.course]]

    for _ in range(target_row):
        _click(session, {1: _DOWN}, idle_frames=10)

    for _ in range(target_col):
        _click(session, {1: _RIGHT}, idle_frames=10)

    _click(session, {1: _A}, idle_frames=100)


def select_course(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    target_index = COURSE_POSITION_MAP[configuration.course]
    for _ in range(target_index):
        _click(session, {1: _DOWN}, idle_frames=10)
    _click(session, {1: _A}, idle_frames=100)
    _click(session, {1: _A})


def select_rules(session: Dolphin.Session, configuration: RaceConfiguration) -> None:
    rules: list[tuple[tuple[object, ...], object, int]] = [
        (_CC_ORDER, configuration.cc, 1),
        (_CPU_ORDER, configuration.cpu, 1),
        (_VEHICLE_RULE_ORDER, configuration.vehicle_rule, 0),
        (_COURSE_RULE_ORDER, configuration.course_rule, 0),
        (_ITEM_RULE_ORDER, configuration.item_rule, 0),
        (_RACES_ORDER, configuration.races, 2),
    ]

    for order, selected_rule, start_col in rules:
        target_col = order.index(selected_rule)
        col_shift = target_col - start_col

        horizontal_move = _LEFT if col_shift <= 0 else _RIGHT
        for _ in range(abs(col_shift)):
            _click(session, {1: horizontal_move}, idle_frames=50)
        _click(session, {1: _A}, idle_frames=50)

    _click(session, {1: _A}, idle_frames=100)
