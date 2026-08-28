import struct
from collections.abc import Sequence

import pytest
from wii_arena.dolphin import DolphinMemoryView

from environment.telemetry.functions import read_menu_state, read_vs_points
from environment.telemetry.services import (
    MEM1_START,
    MEM2_START,
    GuestMemory,
    GuestMemoryAddressError,
    is_mapped,
)
from environment.telemetry.types import GuestAddress, KartIndex, RacerCount

_MEM2_VIEW_OFFSET = 0x2040000
_VIEW_SIZE = _MEM2_VIEW_OFFSET + 0x4000

_RACE_CONFIG_POINTER = GuestAddress(0x809BD728)
_RACE_CONFIG = GuestAddress(0x90000100)
_MENU_SCENARIO_PLAYER = 0xC18
_PLAYER_STRIDE = 0xF0
_GP_SCORE = 0xDA


def _view_offset(address: GuestAddress) -> int:
    if address >= MEM2_START:
        return (address - MEM2_START) + _MEM2_VIEW_OFFSET
    return address - MEM1_START


def _memory_with_points(points: Sequence[int]) -> GuestMemory:
    raw = bytearray(_VIEW_SIZE)
    struct.pack_into(">I", raw, _view_offset(_RACE_CONFIG_POINTER), _RACE_CONFIG)
    for index, value in enumerate(points):
        struct.pack_into(
            ">H",
            raw,
            _view_offset(_RACE_CONFIG)
            + _MENU_SCENARIO_PLAYER
            + _PLAYER_STRIDE * index
            + _GP_SCORE,
            value,
        )
    return GuestMemory(DolphinMemoryView(memoryview(raw)))


def test_only_the_two_arenas_are_mapped() -> None:
    assert is_mapped(GuestAddress(0x80000000))
    assert is_mapped(GuestAddress(0x809BD728))
    assert is_mapped(GuestAddress(0x90000000))
    assert not is_mapped(GuestAddress(0x00000000))
    assert not is_mapped(GuestAddress(0x85000000))


def test_values_are_read_big_endian_out_of_both_arenas() -> None:
    raw = bytearray(_VIEW_SIZE)
    struct.pack_into(">I", raw, _view_offset(GuestAddress(0x80100000)), 0xDEADBEEF)
    struct.pack_into(">f", raw, _view_offset(GuestAddress(0x90000200)), 4.0)
    memory = GuestMemory(DolphinMemoryView(memoryview(raw)))

    assert memory.u32(GuestAddress(0x80100000)) == 0xDEADBEEF
    assert memory.u8(GuestAddress(0x80100000)) == 0xDE
    assert memory.u16(GuestAddress(0x80100000)) == 0xDEAD
    assert memory.f32(GuestAddress(0x90000200)) == pytest.approx(4.0)


def test_an_unmapped_address_is_refused() -> None:
    memory = GuestMemory(DolphinMemoryView(memoryview(bytearray(_VIEW_SIZE))))

    with pytest.raises(GuestMemoryAddressError, match="neither MEM1 nor MEM2"):
        memory.u32(GuestAddress(0x00000000))


def test_a_read_past_the_view_is_refused() -> None:
    memory = GuestMemory(DolphinMemoryView(memoryview(bytearray(0x1000))))

    with pytest.raises(GuestMemoryAddressError, match="past the end"):
        memory.u32(GuestAddress(0x80100000))


def test_points_are_read_for_every_racer_on_the_grid() -> None:
    memory = _memory_with_points([15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1, 0])

    points = read_vs_points(memory, RacerCount(12))

    assert points is not None
    assert points[KartIndex(0)] == 15
    assert points[KartIndex(3)] == 8
    assert points[KartIndex(11)] == 0
    assert len(points) == 12


def test_points_are_absent_while_no_race_configuration_is_loaded() -> None:
    memory = GuestMemory(DolphinMemoryView(memoryview(bytearray(_VIEW_SIZE))))

    assert read_vs_points(memory, RacerCount(12)) is None


def _menu_memory(*, page_count: int, page_id: int, page_state: int) -> GuestMemory:
    raw = bytearray(_VIEW_SIZE)

    def put_u32(address: GuestAddress, value: int) -> None:
        struct.pack_into(">I", raw, _view_offset(address), value & 0xFFFFFFFF)

    manager = GuestAddress(0x80620000)
    section = GuestAddress(0x80630000)
    page = GuestAddress(0x80640000)
    decoy = GuestAddress(0x80650000)

    put_u32(GuestAddress(0x809C1E38), manager)
    put_u32(manager, section)
    put_u32(GuestAddress(manager + 0x30), 0)
    put_u32(GuestAddress(decoy + 0x04), 0x01)
    put_u32(GuestAddress(decoy + 0x08), 0x01)
    for slot in range(10):
        put_u32(GuestAddress(section + 0x354 + 4 * slot), decoy)
    put_u32(GuestAddress(section + 0x380), decoy)
    if 1 <= page_count <= 10:
        put_u32(GuestAddress(section + 0x354 + 4 * (page_count - 1)), page)
    put_u32(GuestAddress(section + 0x37C), page_count)
    put_u32(GuestAddress(page + 0x04), page_id)
    put_u32(GuestAddress(page + 0x08), page_state)
    return GuestMemory(DolphinMemoryView(memoryview(raw)))


def test_the_focused_page_is_the_last_one_on_the_section() -> None:
    state = read_menu_state(_menu_memory(page_count=3, page_id=0x6E, page_state=4))

    assert state is not None
    assert (state.page_id, state.page_state, state.page_count) == (0x6E, 4, 3)
    assert state.section_lifecycle_state == 0


@pytest.mark.parametrize("page_count", [0, -1, 11, 12])
def test_a_page_count_outside_the_section_array_has_no_menu_state(
    page_count: int,
) -> None:
    memory = _menu_memory(page_count=page_count, page_id=0, page_state=0)

    assert read_menu_state(memory) is None
