import logging
from contextlib import contextmanager
from typing import Iterator

from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import (
    Dolphin,
    DolphinScenario,
)

from .models import RaceConfiguration

_LOGGER = logging.getLogger(__name__)


class MarioKartWiiRace(DolphinScenario):
    class Session(DolphinScenario.Session):
        def terminated(self) -> Terminated:
            _LOGGER.debug("Checking MarioKartWiiRace terminated state")
            # TODO: implement this method to determine if the Mario Kart Wii race has terminated, e.g. by checking all the players have finished the race
            return Terminated(False)

        def truncated(self) -> Truncated:
            _LOGGER.debug("Checking MarioKartWiiRace truncated state")
            # TODO: implement this method to determine if the Mario Kart Wii race has been truncated
            return Truncated(False)

    def __init__(self, configuration: RaceConfiguration, dolphin: Dolphin):
        self._configuration = configuration
        self._dolphin = dolphin
        _LOGGER.debug(
            "Initialized MarioKartWiiRace with configuration=%s and dolphin=%s",
            configuration,
            type(dolphin).__name__,
        )

    @contextmanager
    def session(self) -> Iterator[MarioKartWiiRace.Session]:
        _LOGGER.info("Opening MarioKartWiiRace session")
        with self._dolphin.session() as dolphin_session:
            # TODO: e.g. navigating the Dolphin emulator to the race menus in Mario Kart Wii.
            scenario_session = MarioKartWiiRace.Session(dolphin_session=dolphin_session)
            _LOGGER.debug("Mario Kart scenario session ready")
            yield scenario_session
            _LOGGER.info("Closing MarioKartWiiRace session")
            # TODO: e.g. cleaning up after the Mario Kart Wii race.
