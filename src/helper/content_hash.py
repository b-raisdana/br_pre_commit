"""CRC-32 filename hash helpers shared by content-addressed stores."""

from __future__ import annotations

import zlib


def crc32_hex(payload: bytes) -> str:
    """Return the full lowercase eight-character CRC-32 representation."""
    return f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"
