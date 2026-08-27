from collections.abc import Mapping, Sequence
from typing import Literal, NewType

from ..scenario.types import PlayerSeat

TeamIdentifier = Literal["a", "b"]

TeamName = NewType("TeamName", str)

CupKey = Literal[
    "mushroom_cup",
    "flower_cup",
    "star_cup",
    "special_cup",
    "shell_cup",
    "banana_cup",
    "leaf_cup",
    "lightning_cup",
]

VsSessionVerdict = Literal["a", "b", "tie"]
"""Which team took a VS session, or `tie` when the session must be replayed."""

type SeatsByTeam = Mapping[TeamIdentifier, Sequence[PlayerSeat]]
"""Which controller seats each team drives, drawn afresh for every cup."""
