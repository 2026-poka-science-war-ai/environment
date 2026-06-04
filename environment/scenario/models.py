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

_CHARACTER_SIZES: dict[Character, VehicleSize] = {
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


def _get_character_size(character: Character) -> VehicleSize:
    if character in _CHARACTER_SIZES:
        return _CHARACTER_SIZES[character]
    raise ValueError(
        f"{character} size cannot be inferred. "
        "Use a non-Mii character or add explicit Mii size handling."
    )


def _get_vehicle_size(vehicle: Vehicle) -> VehicleSize:
    return _VEHICLE_SIZES[vehicle]


class Player(BaseModel):
    character: Character
    vehicle: Vehicle
    drift_mode: DriftMode

    @model_validator(mode="after")
    def validate_vehicle_size(self) -> "Player":
        target_size = _get_character_size(self.character)
        selected_vehicle_size = _get_vehicle_size(self.vehicle)
        if selected_vehicle_size != target_size:
            raise ValueError(
                f"{self.vehicle} is {selected_vehicle_size} size, "
                f"but {self.character} is {target_size} size."
            )
        return self


class RaceConfiguration(BaseModel):
    players: list[Player]
    online_mode: bool
    mode: Mode
    course: Course
    cc: Cc
    cpu: Cpu
    vehicle_rule: VehicleRule
    course_rule: CourseRule
    item_rule: ItemRule
    races: Races

    @field_validator("players")
    @classmethod
    def validate_players(cls, players: list[Player]) -> list[Player]:
        if len(players) not in {1, 4, 12}:
            raise ValueError(
                f"players must contain exactly 1, 4, or 12 players, got {len(players)}"
            )
        return players
