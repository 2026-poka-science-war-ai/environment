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
