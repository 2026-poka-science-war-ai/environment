import struct
from collections.abc import Sequence
from contextlib import AbstractContextManager

from wii_arena.dolphin import (
    Dolphin,
    DolphinAction,
    DolphinGameCubeControllerInput,
    DolphinMemoryView,
)

from environment.scenario.models import RaceConfiguration, Racer
from environment.scenario.services import (
    MENU_ADVANCE_PERIOD_FRAMES,
    RACE_STAGE_COUNTDOWN,
    RACE_STAGE_INTRO,
    RACE_STAGE_RACE,
    RESULTS_HOLD_FRAMES,
    MarioKartWiiRace,
    VsSessionLifecycle,
    idle_action,
)
from environment.scenario.types import Races
from environment.telemetry.services import GuestMemory
from environment.telemetry.types import KartIndex, RacerCount

_RACE_MANAGER_POINTER = 0x809BD730
_RACE_MANAGER = 0x80300000
_KART_ARRAY = 0x80310000
_KART_BASE = 0x80320000
_KART_STRIDE = 0x100

_RACER_COUNT = RacerCount(4)
_MODEL_ACTION: DolphinAction = [
    DolphinGameCubeControllerInput(b=True) for _ in range(4)
]


def _memory(
    *, completions: Sequence[float] | None, finished: int = 0, stage: int = 0
) -> GuestMemory:
    raw = bytearray(0xA00000)

    def put_u32(address: int, value: int) -> None:
        struct.pack_into(">I", raw, address - 0x80000000, value)

    if completions is None:
        put_u32(_RACE_MANAGER_POINTER, 0)
        return GuestMemory(DolphinMemoryView(memoryview(raw)))

    put_u32(_RACE_MANAGER_POINTER, _RACE_MANAGER)
    put_u32(_RACE_MANAGER + 0x0C, _KART_ARRAY)
    put_u32(_RACE_MANAGER + 0x28, stage)
    struct.pack_into(">B", raw, (_RACE_MANAGER + 0x1C) - 0x80000000, finished)
    for index, completion in enumerate(completions):
        kart = _KART_BASE + _KART_STRIDE * index
        put_u32(_KART_ARRAY + 4 * index, kart)
        struct.pack_into(">f", raw, (kart + 0x10) - 0x80000000, completion)
    return GuestMemory(DolphinMemoryView(memoryview(raw)))


def _lifecycle(race_count: int = 2) -> VsSessionLifecycle:
    return VsSessionLifecycle(race_count=race_count, racer_count=_RACER_COUNT)


def _pressed_a(action: Sequence[object]) -> bool:
    first = action[0]
    return isinstance(first, DolphinGameCubeControllerInput) and first.a


def test_a_countdown_is_not_yet_a_race() -> None:
    lifecycle = _lifecycle()

    lifecycle.observe(_memory(completions=[0.0] * 4, stage=RACE_STAGE_COUNTDOWN))

    assert not lifecycle.is_racing
    assert lifecycle.is_counting_down
    assert not lifecycle.should_advance_menu


def test_the_intro_camera_is_neither_a_race_nor_a_countdown() -> None:
    lifecycle = _lifecycle()

    lifecycle.observe(_memory(completions=[0.94] * 4, stage=RACE_STAGE_INTRO))

    assert not lifecycle.is_racing
    assert not lifecycle.is_counting_down


def test_karts_past_the_line_are_racing() -> None:
    lifecycle = _lifecycle()

    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))

    assert lifecycle.is_racing
    assert not lifecycle.should_advance_menu


def test_a_race_is_credited_when_every_kart_has_finished() -> None:
    lifecycle = _lifecycle()
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))

    lifecycle.observe(_memory(completions=[5.0] * 4, finished=4, stage=4))

    assert lifecycle.completed_race_count == 1
    assert not lifecycle.is_racing
    assert not lifecycle.is_session_complete


def test_the_results_are_walked_on_even_when_a_kart_never_finished() -> None:
    lifecycle = _lifecycle()
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))
    lifecycle.observe(_memory(completions=[5.0, 5.0, 5.0, 1.6], finished=4, stage=4))

    assert lifecycle.completed_race_count == 1
    assert lifecycle.should_advance_menu


def test_a_session_completes_once_its_last_race_is_credited() -> None:
    lifecycle = _lifecycle(race_count=1)
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))

    lifecycle.observe(_memory(completions=[5.0] * 4, finished=4, stage=4))

    assert lifecycle.is_session_complete
    assert not lifecycle.should_advance_menu
    assert not lifecycle.is_finished


def test_the_menu_needs_the_manager_gone_for_a_sustained_stretch() -> None:
    lifecycle = _lifecycle(race_count=1)
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))
    lifecycle.observe(_memory(completions=[5.0] * 4, finished=4, stage=4))

    lifecycle.observe(_memory(completions=None))
    assert not lifecycle.has_reached_menu

    for _ in range(500):
        lifecycle.observe(_memory(completions=None))
    assert lifecycle.has_reached_menu
    assert lifecycle.is_finished


def test_nothing_is_pressed_from_the_first_frame_without_a_race() -> None:
    lifecycle = _lifecycle(race_count=1)
    results = _memory(completions=[5.0] * 4, finished=4, stage=4)
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))
    lifecycle.observe(results)
    for _ in range(RESULTS_HOLD_FRAMES):
        lifecycle.observe(results)

    lifecycle.observe(_memory(completions=None))

    assert not lifecycle.has_reached_menu
    assert lifecycle.session_end_action() == idle_action()


def test_the_final_results_are_held_before_the_menu_is_asked_for() -> None:
    lifecycle = _lifecycle(race_count=1)
    results = _memory(completions=[5.0] * 4, finished=4, stage=4)
    lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))
    lifecycle.observe(results)

    assert lifecycle.session_end_action() == idle_action()

    for _ in range(RESULTS_HOLD_FRAMES):
        lifecycle.observe(results)

    pressed_within_one_period: list[bool] = []
    for _ in range(60):
        pressed_within_one_period.append(_pressed_a(lifecycle.session_end_action()))
        lifecycle.observe(results)

    assert any(pressed_within_one_period)


def test_the_menu_walk_pulses_rather_than_holds() -> None:
    lifecycle = _lifecycle()
    actions = [lifecycle.menu_action(step) for step in range(60)]

    assert any(_pressed_a(action) for action in actions)
    assert any(action == idle_action() for action in actions)


def test_a_kart_slot_that_does_not_resolve_is_skipped() -> None:
    lifecycle = _lifecycle()

    lifecycle.observe(_memory(completions=[1.2, 1.2, 1.2], stage=RACE_STAGE_RACE))

    progress = lifecycle.latest_progress
    assert progress is not None
    assert set(progress.completions) == {KartIndex(0), KartIndex(1), KartIndex(2)}
    assert lifecycle.is_racing


class _UnusedDolphin(Dolphin):
    def session(self) -> AbstractContextManager[Dolphin.Session]:
        raise NotImplementedError


def _scenario(race_count: Races = 2) -> MarioKartWiiRace:
    return MarioKartWiiRace(
        configuration=RaceConfiguration(
            racers=[
                Racer(
                    character="Mario", vehicle="Standard Kart M", drift_mode="manual"
                ),
                Racer(character="Daisy", vehicle="Mach Bike", drift_mode="manual"),
                Racer(character="Toad", vehicle="Standard Kart S", drift_mode="manual"),
                Racer(character="Bowser", vehicle="Flame Flyer", drift_mode="manual"),
            ],
            mode="solo",
            course="Luigi Circuit",
            cc=150,
            cpu="off",
            vehicle_rule="all",
            course_rule="in order",
            item_rule="recommended",
            races=race_count,
        ),
        dolphin=_UnusedDolphin(),
    )


def _control_over(scenario: MarioKartWiiRace, frames: int) -> list[DolphinAction]:
    return [scenario.control(_MODEL_ACTION) for _ in range(frames)]


def test_a_live_race_is_driven_by_the_models() -> None:
    scenario = _scenario()
    scenario.lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))

    assert scenario.control(_MODEL_ACTION) == _MODEL_ACTION


def test_the_countdown_is_driven_by_the_models() -> None:
    scenario = _scenario()
    scenario.lifecycle.observe(
        _memory(completions=[0.0] * 4, stage=RACE_STAGE_COUNTDOWN)
    )

    assert scenario.control(_MODEL_ACTION) == _MODEL_ACTION


def test_the_intro_camera_is_driven_by_nobody() -> None:
    scenario = _scenario()
    scenario.lifecycle.observe(_memory(completions=[0.94] * 4, stage=RACE_STAGE_INTRO))

    assert scenario.control(_MODEL_ACTION) == idle_action()


def test_the_results_between_races_are_walked_on_by_the_scenario() -> None:
    scenario = _scenario()
    results = _memory(completions=[5.0] * 4, finished=4, stage=4)
    scenario.lifecycle.observe(_memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE))
    scenario.lifecycle.observe(results)

    actions = _control_over(scenario, MENU_ADVANCE_PERIOD_FRAMES)

    assert any(_pressed_a(action) for action in actions)
    assert all(action != _MODEL_ACTION for action in actions)


def test_the_menu_after_the_last_race_is_left_alone() -> None:
    scenario = _scenario(race_count=2)
    results = _memory(completions=[5.0] * 4, finished=4, stage=4)
    for _ in range(2):
        scenario.lifecycle.observe(
            _memory(completions=[1.2] * 4, stage=RACE_STAGE_RACE)
        )
        scenario.lifecycle.observe(results)
    for _ in range(RESULTS_HOLD_FRAMES):
        scenario.lifecycle.observe(results)
    scenario.lifecycle.observe(_memory(completions=None))

    assert scenario.control(_MODEL_ACTION) == idle_action()
