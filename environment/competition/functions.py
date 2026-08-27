import importlib.util
import logging
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from random import Random
from typing import Final, cast

from ..arena import Model
from ..scenario.functions import first_course_of_cup, racer_count_of
from ..scenario.models import RaceConfiguration
from ..scenario.types import (
    Cc,
    CourseRule,
    Cpu,
    Cup,
    ItemRule,
    Mode,
    PlayerSeat,
    Races,
    VehicleRule,
)
from ..telemetry.types import RacerCount
from .models import SEATS_IN_ORDER, TEAM_IDENTIFIERS, CompetitionConfiguration
from .types import CupKey, SeatsByTeam, TeamIdentifier

_LOGGER = logging.getLogger(__name__)

COMPETITION_MODE: Final[Mode] = "solo"
COMPETITION_CC: Final[Cc] = 150
COMPETITION_CPU: Final[Cpu] = "normal"
COMPETITION_VEHICLE_RULE: Final[VehicleRule] = "all"
COMPETITION_COURSE_RULE: Final[CourseRule] = "in order"
COMPETITION_ITEM_RULE: Final[ItemRule] = "recommended"
COMPETITION_RACES: Final[Races] = 4
COMPETITION_SESSION_COUNT: Final[int] = 3

SESSIONS_TO_WIN: Final[int] = COMPETITION_SESSION_COUNT // 2 + 1

MODEL_CLASS_NAME: Final[str] = "Model"

CUP_BY_KEY: Final[Mapping[CupKey, Cup]] = {
    "mushroom_cup": "Mushroom Cup",
    "flower_cup": "Flower Cup",
    "star_cup": "Star Cup",
    "special_cup": "Special Cup",
    "shell_cup": "Shell Cup",
    "banana_cup": "Banana Cup",
    "leaf_cup": "Leaf Cup",
    "lightning_cup": "Lightning Cup",
}

_KEY_BY_CUP: Final[Mapping[Cup, CupKey]] = {cup: key for key, cup in CUP_BY_KEY.items()}

_SELECTABLE_CUPS: Final[Sequence[Cup]] = tuple(CUP_BY_KEY.values())

_SEATS_PER_TEAM: Final[int] = 2

_VALIDATION_SEATS: Final[SeatsByTeam] = {"a": (1, 2), "b": (3, 4)}


class ModelModuleImportError(ImportError): ...


class ModelClassNotFoundError(AttributeError): ...


class ModelProtocolError(TypeError): ...


def _reject_unraceable_presets(configuration: CompetitionConfiguration) -> None:
    for cup in _SELECTABLE_CUPS:
        for first_picking_team in TEAM_IDENTIFIERS:
            race_configuration_for(
                configuration, cup, first_picking_team, _VALIDATION_SEATS
            )


def load_competition_configuration(
    configuration_file: Path,
) -> CompetitionConfiguration:
    with configuration_file.open("rb") as stream:
        document = tomllib.load(stream)

    configuration = CompetitionConfiguration.model_validate(document)
    _reject_unraceable_presets(configuration)

    _LOGGER.info(
        "Loaded competition configuration for %s versus %s",
        configuration.team("a").name,
        configuration.team("b").name,
    )
    return configuration


def competition_racer_count(configuration: CompetitionConfiguration) -> RacerCount:
    return racer_count_of(
        race_configuration_for(configuration, "Mushroom Cup", "a", _VALIDATION_SEATS)
    )


def key_of_cup(cup: Cup) -> CupKey:
    return _KEY_BY_CUP[cup]


def race_configuration_for(
    configuration: CompetitionConfiguration,
    cup: Cup,
    first_picking_team: TeamIdentifier,
    seats_by_team: SeatsByTeam,
) -> RaceConfiguration:
    """Each team's picks take its drawn seats in the order they are listed."""
    picked = configuration.cups[key_of_cup(cup)].for_first_picking_team(
        first_picking_team
    )
    by_seat = {
        seat: racer
        for identifier, seats in seats_by_team.items()
        for seat, racer in zip(seats, picked.for_team(identifier))
    }
    return RaceConfiguration(
        racers=[by_seat[seat] for seat in SEATS_IN_ORDER],
        mode=COMPETITION_MODE,
        course=first_course_of_cup(cup),
        cc=COMPETITION_CC,
        cpu=COMPETITION_CPU,
        vehicle_rule=COMPETITION_VEHICLE_RULE,
        course_rule=COMPETITION_COURSE_RULE,
        item_rule=COMPETITION_ITEM_RULE,
        races=COMPETITION_RACES,
    )


def select_cups(
    random: Random, count: int = COMPETITION_SESSION_COUNT
) -> Sequence[Cup]:
    selected = tuple(random.sample(_SELECTABLE_CUPS, count))
    _LOGGER.info("Selected cups %s", list(selected))
    return selected


def select_seat_assignment(random: Random) -> SeatsByTeam:
    drawn = list(SEATS_IN_ORDER)
    random.shuffle(drawn)
    assignment: SeatsByTeam = {
        "a": tuple(sorted(drawn[:_SEATS_PER_TEAM])),
        "b": tuple(sorted(drawn[_SEATS_PER_TEAM:])),
    }
    _LOGGER.info(
        "Seats drawn: %s", {team: list(seats) for team, seats in assignment.items()}
    )
    return assignment


def select_opening_team(random: Random) -> TeamIdentifier:
    opening_team = random.choice(TEAM_IDENTIFIERS)
    _LOGGER.info("Team %s picks first in the opening VS race", opening_team)
    return opening_team


def first_picking_team(
    session_index: int,
    opening_team: TeamIdentifier,
    decided_winners: Sequence[TeamIdentifier],
) -> TeamIdentifier:
    if session_index == 0:
        return opening_team
    previous_winner = decided_winners[session_index - 1]
    return "b" if previous_winner == "a" else "a"


def load_model(
    model_file: Path, player: PlayerSeat, team_players: Sequence[PlayerSeat]
) -> Model:
    module_name = f"competition_model_seat_{player}"
    specification = importlib.util.spec_from_file_location(module_name, model_file)
    if specification is None or specification.loader is None:
        raise ModelModuleImportError(
            f"{model_file} could not be loaded as a Python module"
        )

    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as import_error:
        del sys.modules[module_name]
        raise ModelModuleImportError(
            f"{model_file} raised while being imported"
        ) from import_error

    declared = vars(module).get(MODEL_CLASS_NAME)
    if declared is None:
        raise ModelClassNotFoundError(
            f"{model_file} does not define a class named {MODEL_CLASS_NAME!r}"
        )
    if not callable(declared):
        raise ModelProtocolError(
            f"{MODEL_CLASS_NAME!r} in {model_file} is not callable"
        )

    # A dynamically imported attribute cannot be typed; `act` is checked below.
    built = cast(Model, declared(player=player, team_players=list(team_players)))
    if not callable(getattr(built, "act", None)):
        raise ModelProtocolError(
            f"{MODEL_CLASS_NAME!r} in {model_file} has no callable 'act' method"
        )

    _LOGGER.info(
        "Loaded the model for seat %d of %s from %s",
        player,
        list(team_players),
        model_file,
    )
    return built


def series_is_decided(decided_winners: Sequence[TeamIdentifier]) -> bool:
    return any(
        decided_winners.count(identifier) >= SESSIONS_TO_WIN
        for identifier in TEAM_IDENTIFIERS
    )
