"""Every address here is for RMCP01, the PAL disc image."""

import logging
from collections.abc import Mapping
from typing import Final

from .models import (
    RULE_ROW_COUNT,
    MenuState,
    RaceProgress,
    RuleRow,
    RulesPage,
)
from .services import GuestMemory, is_mapped
from .types import GuestAddress, KartIndex, RaceCompletion, RacerCount, VsPoints

_LOGGER = logging.getLogger(__name__)

GAME_ID: Final[bytes] = b"RMCP01"

_RULES_SEAT: Final[int] = 1

RACE_MANAGER_POINTER: Final[GuestAddress] = GuestAddress(0x809BD730)

RACE_CONFIG_POINTER: Final[GuestAddress] = GuestAddress(0x809BD728)

SECTION_MANAGER_POINTER: Final[GuestAddress] = GuestAddress(0x809C1E38)

_SECTION_LIFECYCLE_STATE_OFFSET: Final[int] = 0x30

_SECTION_PAGE_ARRAY_OFFSET: Final[int] = 0x354

_SECTION_PAGE_COUNT_OFFSET: Final[int] = 0x37C

_PAGE_ID_OFFSET: Final[int] = 0x04

_PAGE_STATE_OFFSET: Final[int] = 0x08

_PAGE_INPUT_MANAGER_OFFSET: Final[int] = 0x38
"""`Page::m_inputManager`, written by `setInputManager` at 0x80602474."""

_INPUT_MANAGER_LOCK_OFFSET: Final[int] = 0x0C
"""`MultiControlInputManager::calc` (0x805F0EC8) and `PageInputManager::calc`
(0x805EF450) return before touching a button while this byte is set."""

_INPUT_MANAGER_SEAT_CHOOSING_OFFSET: Final[int] = 0xA4
"""`MultiControlInputManager::setPerControl` (0x805F2100) stores one byte per seat
here; `MenuPage::checkAllMulti` (0x808388F0) reads them back."""

_SEAT_STRIDE: Final[int] = 0x5C

_PAGE_SEAT_CONTROL_OFFSET: Final[int] = 0x484

_CONTROL_SELECTED_ENTRY_OFFSET: Final[int] = 0xCC

_PAGE_JOINED_PLAYER_COUNT_OFFSET: Final[int] = 0xD68
"""Reads -1 once the page has every player it was opened to collect."""

_RULE_ROW_OFFSET: Final[int] = 0x6C4

_RULE_ROW_STRIDE: Final[int] = 0x298

_RULE_ROW_OPTION_COUNT_OFFSET: Final[int] = 0x200

_RULE_ROW_LIVE_OPTION_OFFSET: Final[int] = 0x208

_RULE_ROW_CONTROL_OFFSET: Final[int] = 0x210

_RACE_COUNT_CONTROL_OFFSET: Final[int] = 0x15C0

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

_SECTION_PAGE_CAPACITY: Final[int] = (
    _SECTION_PAGE_COUNT_OFFSET - _SECTION_PAGE_ARRAY_OFFSET
) // _POINTER_WIDTH


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


def section_manager(memory: GuestMemory) -> GuestAddress | None:
    return _follow(memory, SECTION_MANAGER_POINTER)


def _focused_page(
    memory: GuestMemory, section: GuestAddress, page_count: int
) -> GuestAddress | None:
    slot = _SECTION_PAGE_ARRAY_OFFSET + _POINTER_WIDTH * (page_count - 1)
    return _follow(memory, GuestAddress(section + slot))


def focused_page(memory: GuestMemory) -> GuestAddress | None:
    manager = section_manager(memory)
    if manager is None:
        return None
    section = _follow(memory, manager)
    if section is None:
        return None
    page_count = memory.s32(GuestAddress(section + _SECTION_PAGE_COUNT_OFFSET))
    if not 1 <= page_count <= _SECTION_PAGE_CAPACITY:
        return None
    return _focused_page(memory, section, page_count)


def read_menu_state(memory: GuestMemory) -> MenuState | None:
    manager = section_manager(memory)
    if manager is None:
        return None
    section = _follow(memory, manager)
    if section is None:
        return None

    page_count = memory.s32(GuestAddress(section + _SECTION_PAGE_COUNT_OFFSET))
    if not 1 <= page_count <= _SECTION_PAGE_CAPACITY:
        return None
    page = _focused_page(memory, section, page_count)
    if page is None:
        return None

    return MenuState(
        section_lifecycle_state=memory.s32(
            GuestAddress(manager + _SECTION_LIFECYCLE_STATE_OFFSET)
        ),
        page_count=page_count,
        page_id=memory.s32(GuestAddress(page + _PAGE_ID_OFFSET)),
        page_state=memory.s32(GuestAddress(page + _PAGE_STATE_OFFSET)),
        accepts_input=page_accepts_input(memory, page),
    )


def _page_input_manager(memory: GuestMemory, page: GuestAddress) -> GuestAddress | None:
    return _follow(memory, GuestAddress(page + _PAGE_INPUT_MANAGER_OFFSET))


def page_accepts_input(memory: GuestMemory, page: GuestAddress) -> bool:
    manager = _page_input_manager(memory, page)
    if manager is None:
        return False
    return memory.u8(GuestAddress(manager + _INPUT_MANAGER_LOCK_OFFSET)) == 0


def seat_is_choosing(memory: GuestMemory, seat: int) -> bool | None:
    page = focused_page(memory)
    if page is None:
        return None
    manager = _page_input_manager(memory, page)
    if manager is None:
        return None
    return (
        memory.u8(
            GuestAddress(
                manager
                + _INPUT_MANAGER_SEAT_CHOOSING_OFFSET
                + _SEAT_STRIDE * (seat - 1)
            )
        )
        == 1
    )


def _seat_control(
    memory: GuestMemory, page: GuestAddress, seat: int
) -> GuestAddress | None:
    return _follow(
        memory,
        GuestAddress(page + _PAGE_SEAT_CONTROL_OFFSET + _SEAT_STRIDE * (seat - 1)),
    )


def read_selected_entry(memory: GuestMemory, seat: int) -> int | None:
    page = focused_page(memory)
    if page is None:
        return None
    control = _seat_control(memory, page, seat)
    if control is None:
        return None
    return memory.s32(GuestAddress(control + _CONTROL_SELECTED_ENTRY_OFFSET))


def read_joined_player_count(memory: GuestMemory) -> int | None:
    page = focused_page(memory)
    if page is None:
        return None
    return memory.s32(GuestAddress(page + _PAGE_JOINED_PLAYER_COUNT_OFFSET))


def _rule_row(memory: GuestMemory, page: GuestAddress, row: int) -> RuleRow:
    address = GuestAddress(page + _RULE_ROW_OFFSET + _RULE_ROW_STRIDE * row)
    return RuleRow(
        option_count=memory.s32(GuestAddress(address + _RULE_ROW_OPTION_COUNT_OFFSET)),
        live_option=memory.s32(GuestAddress(address + _RULE_ROW_LIVE_OPTION_OFFSET)),
    )


def read_rules_page(memory: GuestMemory) -> RulesPage | None:
    page = focused_page(memory)
    if page is None:
        return None
    control = _seat_control(memory, page, _RULES_SEAT)
    if control is None:
        return None
    first_control = page + _RULE_ROW_OFFSET + _RULE_ROW_CONTROL_OFFSET
    return RulesPage(
        rule_rows=tuple(_rule_row(memory, page, row) for row in range(RULE_ROW_COUNT)),
        race_count_option=memory.s32(GuestAddress(page + _RACE_COUNT_CONTROL_OFFSET)),
        focused_row=(control - first_control) // _RULE_ROW_STRIDE,
    )
