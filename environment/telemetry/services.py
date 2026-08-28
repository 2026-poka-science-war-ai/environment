import struct
from typing import Final

from wii_arena.dolphin import DolphinMemoryView

from .types import GuestAddress

MEM1_START: Final[GuestAddress] = GuestAddress(0x80000000)
MEM1_END: Final[GuestAddress] = GuestAddress(0x81800000)
MEM2_START: Final[GuestAddress] = GuestAddress(0x90000000)
MEM2_END: Final[GuestAddress] = GuestAddress(0x94000000)

_MEM2_VIEW_OFFSET: Final[int] = 0x2040000


class GuestMemoryAddressError(LookupError): ...


def is_mapped(address: GuestAddress) -> bool:
    return (MEM1_START <= address < MEM1_END) or (MEM2_START <= address < MEM2_END)


class GuestMemory:
    def __init__(self, view: DolphinMemoryView) -> None:
        self._view = view

    def _offset(self, address: GuestAddress, width: int) -> int:
        if MEM1_START <= address < MEM1_END:
            offset = address - MEM1_START
        elif MEM2_START <= address < MEM2_END:
            offset = (address - MEM2_START) + _MEM2_VIEW_OFFSET
        else:
            raise GuestMemoryAddressError(
                f"{address:#010x} is in neither MEM1 nor MEM2"
            )
        if offset + width > len(self._view):
            raise GuestMemoryAddressError(
                f"{address:#010x} reads past the end of the mapped view"
            )
        return offset

    def u8(self, address: GuestAddress) -> int:
        return struct.unpack_from(">B", self._view, self._offset(address, 1))[0]

    def u16(self, address: GuestAddress) -> int:
        return struct.unpack_from(">H", self._view, self._offset(address, 2))[0]

    def u32(self, address: GuestAddress) -> int:
        return struct.unpack_from(">I", self._view, self._offset(address, 4))[0]

    def s32(self, address: GuestAddress) -> int:
        return struct.unpack_from(">i", self._view, self._offset(address, 4))[0]

    def f32(self, address: GuestAddress) -> float:
        return struct.unpack_from(">f", self._view, self._offset(address, 4))[0]
