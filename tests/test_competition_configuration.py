import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from environment.competition.models import CompetitionConfiguration


def test_a_complete_document_is_accepted(competition_document: dict[str, Any]) -> None:
    configuration = CompetitionConfiguration.model_validate(competition_document)

    assert configuration.team("a").name == "KAIST"
    assert len(configuration.team("a").models) == 2
    assert len(configuration.cups) == 8


def test_repeated_characters_in_one_line_up_are_rejected(
    competition_document: dict[str, Any],
) -> None:
    picked = competition_document["cups"]["mushroom_cup"]["team_a_first"]
    picked["b"][0] = dict(picked["a"][0])

    with pytest.raises(ValidationError, match="distinct characters"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_vehicle_of_the_wrong_size_is_rejected(
    competition_document: dict[str, Any],
) -> None:
    picked = competition_document["cups"]["star_cup"]["team_b_first"]
    picked["a"][0]["vehicle"] = "Standard Kart S"

    with pytest.raises(ValidationError, match="size"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_team_submitting_one_model_is_rejected(
    competition_document: dict[str, Any], competition_root: Path
) -> None:
    competition_document["teams"]["a"]["models"] = [
        str(competition_root / "a-first.py")
    ]

    with pytest.raises(ValidationError, match="exactly 2 models"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_missing_team_is_rejected(competition_document: dict[str, Any]) -> None:
    del competition_document["teams"]["b"]

    with pytest.raises(ValidationError, match="teams 'a' and 'b'"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_missing_cup_is_rejected(competition_document: dict[str, Any]) -> None:
    del competition_document["cups"]["lightning_cup"]

    with pytest.raises(ValidationError, match="missing cup presets"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_missing_model_file_is_rejected(
    competition_document: dict[str, Any], competition_root: Path
) -> None:
    competition_document["teams"]["a"]["models"] = [
        str(competition_root / "absent.py"),
        str(competition_root / "a-second.py"),
    ]

    with pytest.raises(ValidationError, match="does not exist"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_missing_disc_image_is_rejected(
    competition_document: dict[str, Any], competition_root: Path
) -> None:
    competition_document["wii_iso_file"] = str(competition_root / "absent.iso")

    with pytest.raises(ValidationError, match="disc image"):
        CompetitionConfiguration.model_validate(competition_document)


def test_configured_paths_are_made_absolute(
    competition_document: dict[str, Any], competition_root: Path
) -> None:
    relative = os.path.relpath(competition_root / "MarioKartWii.iso")
    competition_document["wii_iso_file"] = relative
    competition_document["teams"]["a"]["models"] = [
        os.path.relpath(competition_root / "a-first.py"),
        os.path.relpath(competition_root / "a-second.py"),
    ]

    configuration = CompetitionConfiguration.model_validate(competition_document)

    assert configuration.wii_iso_file.is_absolute()
    assert all(
        model_file.is_absolute() for model_file in configuration.team("a").models
    )


def test_a_team_picking_one_racer_for_a_cup_is_rejected(
    competition_document: dict[str, Any],
) -> None:
    picked = competition_document["cups"]["flower_cup"]["team_a_first"]
    picked["a"] = picked["a"][:1]

    with pytest.raises(ValidationError, match="exactly 2 racers"):
        CompetitionConfiguration.model_validate(competition_document)


def test_a_disc_image_from_another_region_is_rejected(
    competition_document: dict[str, Any], competition_root: Path
) -> None:
    (competition_root / "MarioKartWii.iso").write_bytes(b"RMCE01" + b"\x00" * 1024)

    with pytest.raises(ValidationError, match="RMCE01"):
        CompetitionConfiguration.model_validate(competition_document)
