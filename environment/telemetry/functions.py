"""Every address here is for RMCP01, the PAL disc image."""

import logging
from collections.abc import Mapping
from typing import Final

from .models import RaceProgress
from .services import GuestMemory, is_mapped
from .types import GuestAddress, KartIndex, RaceCompletion, RacerCount, VsPoints

_LOGGER = logging.getLogger(__name__)

RACE_MANAGER_POINTER: Final[GuestAddress] = GuestAddress(0x809BD730)

RACE_CONFIG_POINTER: Final[GuestAddress] = GuestAddress(0x809BD728)

_KART_ARRAY_OFFSET: Final[int] = 0x0C

_FINISHED_KART_COUNT_OFFSET: Final[int] = 0x1C

_RACE_COMPLETION_MAX_OFFSET: Final[int] = 0x10

_RACE_STAGE_OFFSET: Final[int] = 0x28

_RACE_SCENARIO_OFFSET: Final[int] = 0x20

_SCENARIO_SIZE: Final[int] = 0xBF0

_MENU_SCENARIO_OFFSET: Final[int] = _RACE_SCENARIO_OFFSET + _SCENARIO_SIZE

_SCENARIO_PLAYER_OFFSET: Final[int] = 0x08

_SCENARIO_PLAYER_STRIDE: Final[int] = 0xF0

_PLAYER_GP_SCORE_OFFSET: Final[int] = 0xDA

_PLAYER_PREVIOUS_SCORE_OFFSET: Final[int] = 0xD8

_PLAYER_FINISH_POSITION_OFFSET: Final[int] = 0xE2

_POINTER_WIDTH: Final[int] = 4


def _follow(memory: GuestMemory, address: GuestAddress) -> GuestAddress | None:
    if not is_mapped(address):
        return None
    target = GuestAddress(memory.u32(address))
    return target if is_mapped(target) else None


def race_manager(memory: GuestMemory) -> GuestAddress | None:
    return _follow(memory, RACE_MANAGER_POINTER)


def race_configuration(memory: GuestMemory) -> GuestAddress | None:
    return _follow(memory, RACE_CONFIG_POINTER)


def kart_address(
    memory: GuestMemory, manager: GuestAddress, kart: KartIndex
) -> GuestAddress | None:
    kart_array = _follow(memory, GuestAddress(manager + _KART_ARRAY_OFFSET))
    if kart_array is None:
        return None
    return _follow(memory, GuestAddress(kart_array + _POINTER_WIDTH * kart))


def read_race_progress(
    memory: GuestMemory, racer_count: RacerCount
) -> RaceProgress | None:
    manager = race_manager(memory)
    if manager is None:
        return None

    completions: dict[KartIndex, RaceCompletion] = {}
    for index in range(racer_count):
        kart = KartIndex(index)
        address = kart_address(memory, manager, kart)
        if address is None:
            continue
        completions[kart] = RaceCompletion(
            memory.f32(GuestAddress(address + _RACE_COMPLETION_MAX_OFFSET))
        )

    if not completions:
        return None

    return RaceProgress(
        completions=completions,
        finished_kart_count=memory.u8(
            GuestAddress(manager + _FINISHED_KART_COUNT_OFFSET)
        ),
        racer_count=racer_count,
    )


def _scenario_player(
    configuration: GuestAddress, scenario_offset: int, kart: KartIndex
) -> GuestAddress:
    return GuestAddress(
        configuration
        + scenario_offset
        + _SCENARIO_PLAYER_OFFSET
        + _SCENARIO_PLAYER_STRIDE * kart
    )


def read_race_stage(memory: GuestMemory) -> int | None:
    manager = race_manager(memory)
    if manager is None:
        return None
    return memory.u32(GuestAddress(manager + _RACE_STAGE_OFFSET))


def read_vs_points(
    memory: GuestMemory, racer_count: RacerCount
) -> Mapping[KartIndex, VsPoints] | None:
    configuration = race_configuration(memory)
    if configuration is None:
        return None

    points = {
        KartIndex(index): VsPoints(
            memory.u16(
                GuestAddress(
                    _scenario_player(
                        configuration, _MENU_SCENARIO_OFFSET, KartIndex(index)
                    )
                    + _PLAYER_GP_SCORE_OFFSET
                )
            )
        )
        for index in range(racer_count)
    }
    _LOGGER.debug("Read VS points %s", points)
    return points


def read_previous_vs_points(
    memory: GuestMemory, racer_count: RacerCount
) -> Mapping[KartIndex, VsPoints] | None:
    configuration = race_configuration(memory)
    if configuration is None:
        return None
    return {
        KartIndex(index): VsPoints(
            memory.u16(
                GuestAddress(
                    _scenario_player(
                        configuration, _MENU_SCENARIO_OFFSET, KartIndex(index)
                    )
                    + _PLAYER_PREVIOUS_SCORE_OFFSET
                )
            )
        )
        for index in range(racer_count)
    }


def read_finish_positions(
    memory: GuestMemory, racer_count: RacerCount
) -> Mapping[KartIndex, int] | None:
    configuration = race_configuration(memory)
    if configuration is None:
        return None
    return {
        KartIndex(index): memory.u8(
            GuestAddress(
                _scenario_player(configuration, _MENU_SCENARIO_OFFSET, KartIndex(index))
                + _PLAYER_FINISH_POSITION_OFFSET
            )
        )
        for index in range(racer_count)
    }
