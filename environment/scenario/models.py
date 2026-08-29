from typing import Self

from pydantic import BaseModel, field_validator, model_validator

from .types import (
    Cc,
    Character,
    Course,
    CourseRule,
    Cpu,
    DriftMode,
    ItemRule,
    Mode,
    Races,
    Vehicle,
    VehicleRule,
    VehicleSize,
)

CHARACTER_SIZES: dict[Character, VehicleSize] = {
    "Baby Mario": "small",
    "Baby Luigi": "small",
    "Baby Peach": "small",
    "Baby Daisy": "small",
    "Toad": "small",
    "Toadette": "small",
    "Koopa Troopa": "small",
    "Dry Bones": "small",
    "Mario": "medium",
    "Luigi": "medium",
    "Peach": "medium",
    "Daisy": "medium",
    "Yoshi": "medium",
    "Birdo": "medium",
    "Diddy Kong": "medium",
    "Bowser Jr": "medium",
    "Wario": "large",
    "Waluigi": "large",
    "Donkey Kong": "large",
    "Bowser": "large",
    "King Boo": "large",
    "Rosalina": "large",
    "Funky Kong": "large",
    "Dry Bowser": "large",
}

_VEHICLE_SIZES: dict[Vehicle, VehicleSize] = {
    "Standard Kart S": "small",
    "Standard Bike S": "small",
    "Baby Booster": "small",
    "Bullet Bike": "small",
    "Concerto": "small",
    "Nanobike": "small",
    "Standard Kart M": "medium",
    "Standard Bike M": "medium",
    "Nostalgia 1": "medium",
    "Mach Bike": "medium",
    "Wild Wing": "medium",
    "Bon Bon": "medium",
    "Standard Kart L": "large",
    "Standard Bike L": "large",
    "Offroader": "large",
    "Bowser Bike": "large",
    "Flame Flyer": "large",
    "Wario Bike": "large",
    "Cheep Charger": "small",
    "Quacker": "small",
    "Rally Romper": "small",
    "Magikruiser": "small",
    "Blue Falcon": "small",
    "Bubble Bike": "small",
    "Turbo Blooper": "medium",
    "Rapide": "medium",
    "Royal Racer": "medium",
    "Nitrocycle": "medium",
    "B Dasher MK 2": "medium",
    "Dolphin Dasher": "medium",
    "Piranha Prowler": "large",
    "Twinkle Star": "large",
    "Aero Glider": "large",
    "Torpedo": "large",
    "Dragonetti": "large",
    "Phantom": "large",
}


def _get_vehicle_size(vehicle: Vehicle) -> VehicleSize:
    return _VEHICLE_SIZES[vehicle]


class Racer(BaseModel):
    character: Character
    vehicle: Vehicle
    drift_mode: DriftMode

    @model_validator(mode="after")
    def validate_vehicle_size(self) -> Self:
        target_size = CHARACTER_SIZES[self.character]
        selected_vehicle_size = _get_vehicle_size(self.vehicle)
        if selected_vehicle_size != target_size:
            raise ValueError(
                f"{self.vehicle} is {selected_vehicle_size} size, "
                f"but {self.character} is {target_size} size."
            )
        return self


class RaceConfiguration(BaseModel):
    racers: list[Racer]
    mode: Mode
    course: Course
    cc: Cc
    cpu: Cpu
    vehicle_rule: VehicleRule
    course_rule: CourseRule
    item_rule: ItemRule
    races: Races

    @field_validator("racers")
    @classmethod
    def validate_racers(cls, racers: list[Racer]) -> list[Racer]:
        if len(racers) not in {1, 4}:
            raise ValueError(
                f"racers must contain exactly 1 or 4 racers, got {len(racers)}"
            )
        characters = [racer.character for racer in racers]
        repeated = sorted({c for c in characters if characters.count(c) > 1})
        if repeated:
            raise ValueError(f"racers must pick distinct characters, got {repeated}")
        return racers

    @model_validator(mode="after")
    def validate_cpu(self) -> Self:
        if len(self.racers) == 1 and self.cpu == "off":
            raise ValueError("a single racer cannot race with the CPUs off")
        return self
