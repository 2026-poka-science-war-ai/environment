from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel, ConfigDict

from .types import KartIndex, RaceCompletion, RacerCount

LIVE_RACE_COMPLETION: Final[RaceCompletion] = RaceCompletion(1.0)


class RaceProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    completions: Mapping[KartIndex, RaceCompletion]
    finished_kart_count: int
    racer_count: RacerCount

    @property
    def is_live(self) -> bool:
        return any(
            completion >= LIVE_RACE_COMPLETION
            for completion in self.completions.values()
        )

    @property
    def has_ended(self) -> bool:
        return self.finished_kart_count >= self.racer_count


class MenuState(BaseModel):
    model_config = ConfigDict(frozen=True)

    section_lifecycle_state: int
    """0 idle, 1 reinit requested, 2 section change requested, 3 reinit committed,
    4 change committed, 5 change requested during a reinit. Pushing and popping
    pages inside one section never touches it."""

    page_count: int
    page_id: int
    page_state: int
