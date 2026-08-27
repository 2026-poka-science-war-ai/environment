import logging
from dataclasses import dataclass
from typing import Protocol

from wii_arena.core.agent.protocols import Agent
from wii_arena.dolphin import (
    DolphinGameCubeControllerInput,
    DolphinObservation,
)

_LOGGER = logging.getLogger(__name__)


class Model(Protocol):
    """A submitted model. Its seat reaches it through its constructor."""

    def act(
        self, observation: DolphinObservation
    ) -> DolphinGameCubeControllerInput: ...


@dataclass(frozen=True)
class Player:
    name: str
    model: Model


class PlayerAgent(Agent[DolphinObservation, DolphinGameCubeControllerInput]):
    def __init__(self, player: Player, seat: int) -> None:
        self._player = player
        self._seat = seat
        _LOGGER.debug("Seat %d is played by %s", seat, player.name)

    def act(self, observation: DolphinObservation) -> DolphinGameCubeControllerInput:
        return self._player.model.act(observation)
