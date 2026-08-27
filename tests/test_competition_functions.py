from pathlib import Path
from random import Random
from typing import Any

import pytest

from environment.competition.functions import (
    CUP_BY_KEY,
    ModelClassNotFoundError,
    ModelProtocolError,
    competition_racer_count,
    first_picking_team,
    key_of_cup,
    load_model,
    race_configuration_for,
    select_cups,
    select_opening_team,
    select_seat_assignment,
)
from environment.competition.models import CompetitionConfiguration
from environment.competition.types import SeatsByTeam
from environment.scenario.functions import first_course_of_cup


def test_every_cup_starts_at_its_own_first_course() -> None:
    assert [first_course_of_cup(cup) for cup in CUP_BY_KEY.values()] == [
        "Luigi Circuit",
        "Mario Circuit",
        "Daisy Circuit",
        "Dry Dry Ruins",
        "GCN Peach Beach",
        "N64 Sherbet Land",
        "DS Desert Street",
        "SNES Mario Circuit 3",
    ]


def test_cup_keys_round_trip() -> None:
    for key, cup in CUP_BY_KEY.items():
        assert key_of_cup(cup) == key


def test_three_distinct_cups_are_drawn() -> None:
    drawn = select_cups(Random(20260825))

    assert len(drawn) == 3
    assert len(set(drawn)) == 3


def test_the_opening_team_is_drawn() -> None:
    drawn = {select_opening_team(Random(seed)) for seed in range(40)}

    assert drawn == {"a", "b"}


def test_the_opening_team_picks_first_in_the_opening_race() -> None:
    assert first_picking_team(0, "a", []) == "a"
    assert first_picking_team(0, "b", []) == "b"


def test_the_loser_picks_first_after_the_opening_race() -> None:
    assert first_picking_team(1, "b", ["a"]) == "b"
    assert first_picking_team(1, "b", ["b"]) == "a"
    assert first_picking_team(2, "b", ["a", "b"]) == "a"
    assert first_picking_team(2, "a", ["b", "a"]) == "b"


def test_the_race_setup_follows_the_competition_rules(
    competition_document: dict[str, Any],
) -> None:
    configuration = CompetitionConfiguration.model_validate(competition_document)

    race = race_configuration_for(
        configuration, "Special Cup", "b", {"a": (1, 3), "b": (2, 4)}
    )

    assert race.course == "Dry Dry Ruins"
    assert race.races == 4
    assert race.course_rule == "in order"
    assert race.mode == "solo"
    assert race.cc == 150
    assert race.cpu == "normal"
    assert len(race.racers) == 4


def test_the_grid_is_filled_when_computer_racers_are_on(
    competition_document: dict[str, Any],
) -> None:
    configuration = CompetitionConfiguration.model_validate(competition_document)

    assert competition_racer_count(configuration) == 12


def test_a_model_is_built_with_the_seat_it_drives(competition_root: Path) -> None:
    model = load_model(competition_root / "a-first.py", 3, (1, 3))

    assert vars(model) == {"player": 3, "team_players": [1, 3]}


def test_a_file_without_a_model_class_is_rejected(tmp_path: Path) -> None:
    model_file = tmp_path / "empty.py"
    model_file.write_text("class Helper:\n    pass\n", encoding="utf-8")

    with pytest.raises(ModelClassNotFoundError):
        load_model(model_file, 1, (1, 2))


def test_a_model_without_an_act_method_is_rejected(tmp_path: Path) -> None:
    model_file = tmp_path / "silent.py"
    model_file.write_text(
        "class Model:\n    def __init__(self, player, team_players):\n        pass\n",
        encoding="utf-8",
    )

    with pytest.raises(ModelProtocolError):
        load_model(model_file, 2, (2, 4))


def test_the_seats_are_split_two_and_two() -> None:
    for seed in range(20):
        assignment = select_seat_assignment(Random(seed))

        assert len(assignment["a"]) == 2
        assert len(assignment["b"]) == 2
        assert set(assignment["a"]) | set(assignment["b"]) == {1, 2, 3, 4}
        assert not set(assignment["a"]) & set(assignment["b"])


def test_each_team_gets_its_seats_in_ascending_order() -> None:
    for seed in range(20):
        assignment = select_seat_assignment(Random(seed))

        assert list(assignment["a"]) == sorted(assignment["a"])
        assert list(assignment["b"]) == sorted(assignment["b"])


def test_the_draw_reaches_every_split() -> None:
    splits = {tuple(select_seat_assignment(Random(seed))["a"]) for seed in range(200)}

    assert splits == {(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4)}


def test_each_team_takes_its_drawn_seats_in_the_order_it_picked(
    competition_document: dict[str, Any],
) -> None:
    configuration = CompetitionConfiguration.model_validate(competition_document)

    race = race_configuration_for(
        configuration, "Mushroom Cup", "a", {"a": (1, 4), "b": (2, 3)}
    )

    assert [racer.character for racer in race.racers] == [
        "Mario",
        "Bowser",
        "Daisy",
        "Toad",
    ]


def test_the_picking_team_decides_which_line_up_is_used(
    competition_document: dict[str, Any],
) -> None:
    configuration = CompetitionConfiguration.model_validate(competition_document)
    seats: SeatsByTeam = {"a": (1, 4), "b": (2, 3)}

    picked_by_a = race_configuration_for(configuration, "Mushroom Cup", "a", seats)
    picked_by_b = race_configuration_for(configuration, "Mushroom Cup", "b", seats)

    assert [racer.character for racer in picked_by_b.racers] == [
        "Yoshi",
        "Peach",
        "Toadette",
        "Birdo",
    ]
    assert picked_by_a.racers != picked_by_b.racers
