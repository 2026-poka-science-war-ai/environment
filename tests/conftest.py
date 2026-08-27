from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from environment.competition.functions import CUP_BY_KEY

_PICKS: Mapping[str, Mapping[str, tuple[tuple[str, str, str], ...]]] = {
    "team_a_first": {
        "a": (
            ("Mario", "Standard Kart M", "manual"),
            ("Toad", "Standard Kart S", "automatic"),
        ),
        "b": (
            ("Bowser", "Flame Flyer", "manual"),
            ("Daisy", "Nitrocycle", "automatic"),
        ),
    },
    "team_b_first": {
        "a": (
            ("Yoshi", "Bon Bon", "manual"),
            ("Birdo", "Turbo Blooper", "automatic"),
        ),
        "b": (
            ("Peach", "Wild Wing", "manual"),
            ("Toadette", "Magikruiser", "automatic"),
        ),
    },
}


def picked_racers(preset: str) -> Mapping[str, list[Mapping[str, str]]]:
    return {
        identifier: [
            {"character": character, "vehicle": vehicle, "drift_mode": drift_mode}
            for character, vehicle, drift_mode in picks
        ]
        for identifier, picks in _PICKS[preset].items()
    }


@pytest.fixture
def competition_root(tmp_path: Path) -> Path:
    (tmp_path / "MarioKartWii.iso").write_bytes(b"RMCP01" + b"\x00" * 1024)
    for name in ("a-first", "a-second", "b-first", "b-second"):
        (tmp_path / f"{name}.py").write_text(
            "class Model:\n"
            "    def __init__(self, player, team_players):\n"
            "        self.player = player\n"
            "        self.team_players = team_players\n"
            "\n"
            "    def act(self, observation):\n"
            "        return observation\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.fixture
def competition_document(competition_root: Path) -> dict[str, Any]:
    return {
        "wii_iso_file": str(competition_root / "MarioKartWii.iso"),
        "teams": {
            "a": {
                "name": "KAIST",
                "models": [
                    str(competition_root / "a-first.py"),
                    str(competition_root / "a-second.py"),
                ],
            },
            "b": {
                "name": "POSTECH",
                "models": [
                    str(competition_root / "b-first.py"),
                    str(competition_root / "b-second.py"),
                ],
            },
        },
        "cups": {
            key: {preset: picked_racers(preset) for preset in _PICKS}
            for key in CUP_BY_KEY
        },
    }
