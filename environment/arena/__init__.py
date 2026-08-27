import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from wii_arena.core.agent.protocols import Agent
from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import (
    DolphinAction,
    DolphinEnvironment,
    DolphinFrameBuffer,
    DolphinGameCubeControllerInput,
    DolphinGameCubeControllerNoOp,
    DolphinObservation,
)

_LOGGER = logging.getLogger(__name__)


class ObservationResolver[TObs](Protocol):
    def resolve(self, observation: DolphinObservation, seat: int) -> TObs: ...


class Model[TObs](Protocol):
    def act(self, observation: TObs) -> DolphinGameCubeControllerInput: ...


@dataclass(frozen=True)
class Player[TObs]:
    name: str
    resolver: ObservationResolver[TObs]
    model: Model[TObs]


class PlayerAgent[TObs](Agent[DolphinObservation, DolphinGameCubeControllerInput]):
    def __init__(self, player: Player[TObs], seat: int) -> None:
        self._player = player
        self._seat = seat

    def act(self, observation: DolphinObservation) -> DolphinGameCubeControllerInput:
        return self._player.model.act(
            self._player.resolver.resolve(observation, self._seat)
        )


class Arena:
    def __init__(
        self,
        environment: DolphinEnvironment,
        players: Sequence[Player[Any]],
    ) -> None:
        self._agents: list[
            Agent[DolphinObservation, DolphinGameCubeControllerInput]
        ] = [PlayerAgent(player, seat) for seat, player in enumerate(players, start=1)]
        self._environment = environment
        _LOGGER.info(
            "Arena configured with seat assignment %s",
            {seat: player.name for seat, player in enumerate(players, start=1)},
        )

    def stream(self) -> Iterator[DolphinFrameBuffer]:
        controller_ports = 4
        with self._environment.session() as environment:
            observation, _context = environment.reset()
            terminated, truncated = Terminated(False), Truncated(False)

            yield observation[1][0]

            while not (terminated or truncated):
                actions: DolphinAction = [
                    agent.act(observation) for agent in self._agents
                ]
                actions += [DolphinGameCubeControllerNoOp()] * (
                    controller_ports - len(actions)
                )
                observation, terminated, truncated, _context = environment.step(actions)
                yield observation[1][0]
