from typing import NewType

GuestAddress = NewType("GuestAddress", int)
"""A Wii guest virtual address: `0x80xxxxxx` is MEM1, `0x90xxxxxx` is MEM2."""

KartIndex = NewType("KartIndex", int)
"""Zero-based index of a kart in the race manager's player array."""

RacerCount = NewType("RacerCount", int)
"""Karts on the grid, computer controlled ones included."""

RaceCompletion = NewType("RaceCompletion", float)
"""Course progress: 1.0 is the lap-one line, 2.0 lap two, 4.0 is finished."""

VsPoints = NewType("VsPoints", int)
