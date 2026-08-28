from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final

from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import (
    Dolphin,
    DolphinAction,
    DolphinFrameBuffer,
    DolphinFrameBufferUnavailable,
    DolphinGameCubeControllerInput,
    DolphinGameCubeControllerNoOp,
    DolphinMemoryView,
    DolphinScenario,
)

from ..telemetry.functions import read_menu_state, read_race_progress, read_race_stage
from ..telemetry.models import MenuState, RaceProgress
from ..telemetry.services import GuestMemory, GuestMemoryAddressError
from ..telemetry.types import RacerCount
from .functions import navigate, racer_count_of
from .models import RaceConfiguration

_LOGGER = logging.getLogger(__name__)

_CONTROLLER_PORTS: Final[int] = 4

MENU_ADVANCE_PERIOD_FRAMES: Final[int] = 30

_MENU_ADVANCE_PRESS_FRAMES: Final[int] = 3

_RACE_TEARDOWN_FRAMES: Final[int] = 90

RESULTS_HOLD_FRAMES: Final[int] = 900

_MENU_RETURN_BUDGET_FRAMES: Final[int] = 7200

_MENU_TEARDOWN_FRAMES: Final[int] = 180

_MENU_SETTLE_FRAMES: Final[int] = 300

_SESSION_TIME_BUDGET_SECONDS: Final[float] = 2 * 60 * 60

RACE_STAGE_INTRO: Final[int] = 0
RACE_STAGE_COUNTDOWN: Final[int] = 1
RACE_STAGE_RACE: Final[int] = 2
RACE_STAGE_FINISHED: Final[int] = 3

_RACE_STAGES: Final[frozenset[int]] = frozenset(
    {RACE_STAGE_INTRO, RACE_STAGE_COUNTDOWN, RACE_STAGE_RACE, RACE_STAGE_FINISHED}
)

_A = DolphinGameCubeControllerInput(a=True)


def idle_action() -> DolphinAction:
    return [DolphinGameCubeControllerNoOp() for _ in range(_CONTROLLER_PORTS)]


def _press_a_on_port_one() -> DolphinAction:
    return [
        _A,
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
        DolphinGameCubeControllerNoOp(),
    ]


FrameObserver = Callable[[DolphinFrameBuffer], None]


class _ObservedDolphinSession(Dolphin.Session):
    """Every frame the menu macros execute passes through here."""

    def __init__(self, session: Dolphin.Session, observe: FrameObserver) -> None:
        self._session = session
        self._observe = observe
        self._frame = 0
        self._last_menu: MenuState | None = None

    def _log_menu_change(self) -> None:
        try:
            state = read_menu_state(GuestMemory(self._session.memory_view()))
        except GuestMemoryAddressError:
            return
        if state == self._last_menu:
            return
        self._last_menu = state
        _LOGGER.info("Menu frame %d: %s", self._frame, state)

    def execute(self, action: DolphinAction) -> None:
        self._session.execute(action)
        self._frame += 1
        self._log_menu_change()
        try:
            with self._session.frame_buffer() as screens:
                self._observe(screens[0])
        except DolphinFrameBufferUnavailable:
            return

    def memory_view(self) -> DolphinMemoryView:
        return self._session.memory_view()

    @contextmanager
    def frame_buffer(self) -> Generator[list[DolphinFrameBuffer], None, None]:
        with self._session.frame_buffer() as screens:
            yield screens


class VsSessionLifecycle:
    """Read it freely; only the scenario's session drives it, through `observe`."""

    def __init__(self, race_count: int, racer_count: RacerCount) -> None:
        self._race_count = race_count
        self._racer_count = racer_count
        self._completed_race_count = 0
        self._is_racing = False
        self._frames_without_manager = 0
        self._frames_since_session_completed = 0
        self._started_at = time.monotonic()
        self._stage: int | None = None
        self._latest_progress: RaceProgress | None = None
        self._reached_menu = False

    @property
    def completed_race_count(self) -> int:
        return self._completed_race_count

    @property
    def race_count(self) -> int:
        return self._race_count

    @property
    def is_racing(self) -> bool:
        return self._is_racing

    @property
    def stage(self) -> int | None:
        return self._stage

    @property
    def latest_progress(self) -> RaceProgress | None:
        return self._latest_progress

    @property
    def is_counting_down(self) -> bool:
        return (
            not self.is_session_complete
            and not self._is_racing
            and self._stage == RACE_STAGE_COUNTDOWN
        )

    @property
    def is_session_complete(self) -> bool:
        return self._completed_race_count >= self._race_count

    @property
    def has_reached_menu(self) -> bool:
        return (
            self.is_session_complete
            and self._frames_without_manager >= _MENU_TEARDOWN_FRAMES
        )

    @property
    def is_finished(self) -> bool:
        if not self.is_session_complete:
            return False
        if self.has_reached_menu:
            return (
                self._frames_without_manager
                >= _MENU_TEARDOWN_FRAMES + _MENU_SETTLE_FRAMES
            )
        return (
            self._frames_since_session_completed
            >= RESULTS_HOLD_FRAMES + _MENU_RETURN_BUDGET_FRAMES
        )

    @property
    def has_exhausted_budget(self) -> bool:
        return time.monotonic() - self._started_at >= _SESSION_TIME_BUDGET_SECONDS

    @property
    def should_advance_menu(self) -> bool:
        if self._is_racing or self.is_counting_down or self.is_session_complete:
            return False
        return self._completed_race_count > 0 or self._latest_progress is None

    def observe(self, memory: GuestMemory) -> None:
        if self.is_session_complete:
            self._frames_since_session_completed += 1

        stage = read_race_stage(memory)
        self._stage = stage if stage in _RACE_STAGES else None

        progress = read_race_progress(memory, self._racer_count)
        self._latest_progress = progress

        if progress is None:
            self._frames_without_manager += 1
            if self.has_reached_menu and not self._reached_menu:
                self._reached_menu = True
                _LOGGER.info(
                    "The race manager has been gone for %d frames, %d frames "
                    "after the last race, so the session is back at a menu",
                    self._frames_without_manager,
                    self._frames_since_session_completed,
                )
            if (
                self._is_racing
                and self._frames_without_manager >= _RACE_TEARDOWN_FRAMES
            ):
                self._credit_race("the race manager was torn down")
            return

        self._frames_without_manager = 0

        if not self._is_racing:
            if progress.is_live and not progress.has_ended:
                self._is_racing = True
                _LOGGER.info(
                    "Race %d of %d is live (stage %s)",
                    self._completed_race_count + 1,
                    self._race_count,
                    self._stage,
                )
            return

        if progress.has_ended:
            self._credit_race("every kart was credited with finishing")

    def _credit_race(self, reason: str) -> None:
        self._is_racing = False
        self._completed_race_count += 1
        _LOGGER.info(
            "Race %d of %d finished: %s",
            self._completed_race_count,
            self._race_count,
            reason,
        )

    def menu_action(self, step_index: int) -> DolphinAction:
        is_pressed = (
            step_index % MENU_ADVANCE_PERIOD_FRAMES < _MENU_ADVANCE_PRESS_FRAMES
        )
        return _press_a_on_port_one() if is_pressed else idle_action()

    def session_end_action(self) -> DolphinAction:
        if self._frames_since_session_completed < RESULTS_HOLD_FRAMES:
            return idle_action()
        if self._frames_without_manager > 0:
            return idle_action()
        return self.menu_action(self._frames_since_session_completed)


class MarioKartWiiRace(DolphinScenario):
    class Session(DolphinScenario.Session):
        def __init__(
            self,
            dolphin_session: Dolphin.Session,
            lifecycle: VsSessionLifecycle,
        ) -> None:
            super().__init__(dolphin_session=dolphin_session)
            self._lifecycle = lifecycle

        def terminated(self) -> Terminated:
            self._lifecycle.observe(GuestMemory(self.dolphin.memory_view()))
            return Terminated(self._lifecycle.is_finished)

        def truncated(self) -> Truncated:
            if self._lifecycle.has_exhausted_budget:
                _LOGGER.warning(
                    "Truncating the session after %.0f seconds without finishing",
                    _SESSION_TIME_BUDGET_SECONDS,
                )
                return Truncated(True)
            return Truncated(False)

    def __init__(
        self,
        configuration: RaceConfiguration,
        dolphin: Dolphin,
        observe_frame: FrameObserver | None = None,
    ):
        self._configuration = configuration
        self._dolphin = dolphin
        self._observe_frame = observe_frame
        self._lifecycle = VsSessionLifecycle(
            race_count=configuration.races,
            racer_count=racer_count_of(configuration),
        )
        self._step_index = 0

    @property
    def lifecycle(self) -> VsSessionLifecycle:
        return self._lifecycle

    @contextmanager
    def session(self) -> Generator[MarioKartWiiRace.Session, None, None]:
        _LOGGER.info("Opening MarioKartWiiRace session")
        with self._dolphin.session() as dolphin_session:
            navigate(
                dolphin_session
                if self._observe_frame is None
                else _ObservedDolphinSession(dolphin_session, self._observe_frame),
                self._configuration,
            )
            yield MarioKartWiiRace.Session(
                dolphin_session=dolphin_session,
                lifecycle=self._lifecycle,
            )
            _LOGGER.info("Closing MarioKartWiiRace session")

    def control(self, action: DolphinAction) -> DolphinAction:
        """Every action must be routed through this: the environment has no hook
        that lets a scenario take the controllers for the menus between races."""
        self._step_index += 1
        if self._lifecycle.is_session_complete:
            return self._lifecycle.session_end_action()
        if self._lifecycle.is_racing or self._lifecycle.is_counting_down:
            return action
        if self._lifecycle.should_advance_menu:
            return self._lifecycle.menu_action(self._step_index)
        return idle_action()
