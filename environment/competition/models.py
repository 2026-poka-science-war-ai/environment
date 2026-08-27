from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Self, cast, get_args

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..scenario.models import Racer
from ..scenario.types import Cup, PlayerSeat
from ..telemetry.types import VsPoints
from .types import CupKey, TeamIdentifier, TeamName, VsSessionVerdict

SEATS_IN_ORDER: Final[Sequence[PlayerSeat]] = (1, 2, 3, 4)

TEAM_IDENTIFIERS: Final[Sequence[TeamIdentifier]] = ("a", "b")

_MODELS_PER_TEAM: Final[int] = 2


def _resolved(configured: Path) -> Path:
    return configured.expanduser().resolve()


class RepeatedCharacterError(ValueError): ...


class TeamsIncompleteError(ValueError): ...


class TeamModelCountError(ValueError): ...


class TeamPickCountError(ValueError): ...


class ModelFileNotFoundError(ValueError): ...


class WiiIsoFileNotFoundError(ValueError): ...


class CupPresetsIncompleteError(ValueError): ...


class UndecidedSessionError(RuntimeError): ...


class PickedRacers(BaseModel):
    """What each team takes for one cup, in the order its models are listed."""

    model_config = ConfigDict(frozen=True)

    a: Sequence[Racer]
    b: Sequence[Racer]

    def for_team(self, identifier: TeamIdentifier) -> Sequence[Racer]:
        return self.a if identifier == "a" else self.b

    @model_validator(mode="after")
    def validate_pick_count(self) -> Self:
        for identifier, picked in (("a", self.a), ("b", self.b)):
            if len(picked) != _MODELS_PER_TEAM:
                raise TeamPickCountError(
                    f"team {identifier} must pick exactly {_MODELS_PER_TEAM} "
                    f"racers per cup, got {len(picked)}"
                )
        return self

    @model_validator(mode="after")
    def validate_characters_are_distinct(self) -> Self:
        characters = [racer.character for racer in (*self.a, *self.b)]
        repeated = sorted(
            {character for character in characters if characters.count(character) > 1}
        )
        if repeated:
            raise RepeatedCharacterError(
                f"a cup must pick distinct characters, got {repeated} twice"
            )
        return self


class CupPreset(BaseModel):
    model_config = ConfigDict(frozen=True)

    team_a_first: PickedRacers
    team_b_first: PickedRacers

    def for_first_picking_team(self, team: TeamIdentifier) -> PickedRacers:
        return self.team_a_first if team == "a" else self.team_b_first


class TeamConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: TeamName
    models: Sequence[Path]

    @field_validator("models")
    @classmethod
    def resolve_model_files(cls, models: Sequence[Path]) -> Sequence[Path]:
        return tuple(_resolved(model_file) for model_file in models)

    @model_validator(mode="after")
    def validate_model_count(self) -> Self:
        if len(self.models) != _MODELS_PER_TEAM:
            raise TeamModelCountError(
                f"a team must submit exactly {_MODELS_PER_TEAM} models, "
                f"got {len(self.models)}"
            )
        return self


class CompetitionConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    wii_iso_file: Path
    teams: Mapping[TeamIdentifier, TeamConfiguration]
    cups: Mapping[CupKey, CupPreset]

    @field_validator("wii_iso_file")
    @classmethod
    def resolve_wii_iso_file(cls, wii_iso_file: Path) -> Path:
        return _resolved(wii_iso_file)

    def team(self, identifier: TeamIdentifier) -> TeamConfiguration:
        return self.teams[identifier]

    @model_validator(mode="after")
    def validate_both_teams_are_described(self) -> Self:
        if set(self.teams) != {"a", "b"}:
            raise TeamsIncompleteError(
                f"the configuration must describe teams 'a' and 'b', "
                f"got {sorted(self.teams)}"
            )
        return self

    @model_validator(mode="after")
    def validate_every_cup_is_present(self) -> Self:
        expected = set(cast(Sequence[CupKey], get_args(CupKey)))
        if set(self.cups) != expected:
            raise CupPresetsIncompleteError(
                f"missing cup presets for {sorted(expected - set(self.cups))}"
            )
        return self

    @model_validator(mode="after")
    def validate_referenced_files_exist(self) -> Self:
        if not self.wii_iso_file.is_file():
            raise WiiIsoFileNotFoundError(
                f"the disc image {self.wii_iso_file} does not exist"
            )
        for identifier, team in self.teams.items():
            for model_file in team.models:
                if not model_file.is_file():
                    raise ModelFileNotFoundError(
                        f"the model file {model_file} for team {identifier} "
                        "does not exist"
                    )
        return self


class TeamScores(BaseModel):
    model_config = ConfigDict(frozen=True)

    points_by_team: Mapping[TeamIdentifier, VsPoints]
    verdict: VsSessionVerdict


class VsSessionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    cup: Cup
    first_picking_team: TeamIdentifier
    points_by_seat: Mapping[PlayerSeat, VsPoints]
    scores: TeamScores
    attempt: int
    video_file: Path

    @property
    def winner(self) -> TeamIdentifier:
        verdict = self.scores.verdict
        if verdict == "tie":
            raise UndecidedSessionError(
                f"the {self.cup} session was tied and has no winner"
            )
        return verdict


class CompetitionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    sessions: Sequence[VsSessionOutcome]

    @property
    def sessions_won_by_team(self) -> Mapping[TeamIdentifier, int]:
        return {
            identifier: sum(
                1 for session in self.sessions if session.winner == identifier
            )
            for identifier in ("a", "b")
        }

    @property
    def winner(self) -> TeamIdentifier:
        won = self.sessions_won_by_team
        if won["a"] == won["b"]:
            raise UndecidedSessionError(
                f"the competition ended level at {won['a']} sessions each"
            )
        return "a" if won["a"] > won["b"] else "b"
