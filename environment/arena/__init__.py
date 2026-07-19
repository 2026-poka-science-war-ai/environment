import logging
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

from wii_arena.core.agent.protocols import Agent
from wii_arena.core.environment.types import Terminated, Truncated
from wii_arena.dolphin import (
    DolphinEnvironment,
    DolphinFrameBuffer,
    DolphinGameCubeControllerInput,
    DolphinObservation,
)

_LOGGER = logging.getLogger(__name__)

_FIRST_TEAM_SEATS = (1, 3)
_SECOND_TEAM_SEATS = (2, 4)


class ObservationResolver[TObs](Protocol):
    def resolve(self, observation: DolphinObservation, seat: int) -> TObs: ...


class Model[TObs](Protocol):
    def act(self, observation: TObs) -> DolphinGameCubeControllerInput: ...


@dataclass(frozen=True)
class Team[TObs]:
    name: str
    resolver: ObservationResolver[TObs]
    model: Model[TObs]


class TeamSeatAgent[TObs](Agent[DolphinObservation, DolphinGameCubeControllerInput]):
    def __init__(self, team: Team[TObs], seat: int) -> None:
        self._team = team
        self._seat = seat

    def act(self, observation: DolphinObservation) -> DolphinGameCubeControllerInput:
        return self._team.model.act(
            self._team.resolver.resolve(observation, self._seat)
        )


class Arena:
    def __init__(
        self,
        environment: DolphinEnvironment,
        teams: tuple[Team[Any], Team[Any]],
    ) -> None:
        first_team, second_team = teams
        team_of: dict[int, Team[Any]] = {}
        for team, seats in (
            (first_team, _FIRST_TEAM_SEATS),
            (second_team, _SECOND_TEAM_SEATS),
        ):
            for seat in seats:
                team_of[seat] = team

        self._agents: list[Agent[DolphinObservation, DolphinGameCubeControllerInput]] = [
            TeamSeatAgent(team_of[seat], seat) for seat in sorted(team_of)
        ]
        self._environment = environment
        _LOGGER.info(
            "Arena configured with seat assignment %s",
            {seat: team.name for seat, team in team_of.items()},
        )

    def stream(self) -> Iterator[DolphinFrameBuffer]:
        with self._environment.session() as environment:
            observation, context = environment.reset()
            terminated, truncated = Terminated(False), Truncated(False)

            yield observation[1][0]

            while not (terminated or truncated):
                actions = [agent.act(observation) for agent in self._agents]
                observation, terminated, truncated, context = environment.step(actions)
                yield observation[1][0]
