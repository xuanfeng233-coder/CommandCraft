"""Minimal little-endian NBT encoder for Bedrock Edition .mcstructure files.

Bedrock Edition uses little-endian NBT (unlike Java's big-endian).
This module implements only the tag types needed for .mcstructure generation.
"""

from __future__ import annotations

import struct
from io import BytesIO
from typing import Any

# NBT Tag type IDs
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


class NBTWriter:
    """Writes NBT data in little-endian (Bedrock) format."""

    def __init__(self) -> None:
        self._buf = BytesIO()

    def _write(self, data: bytes) -> None:
        self._buf.write(data)

    def _write_byte(self, val: int) -> None:
        self._write(struct.pack("<b", val))

    def _write_ubyte(self, val: int) -> None:
        self._write(struct.pack("<B", val))

    def _write_short(self, val: int) -> None:
        self._write(struct.pack("<h", val))

    def _write_ushort(self, val: int) -> None:
        self._write(struct.pack("<H", val))

    def _write_int(self, val: int) -> None:
        self._write(struct.pack("<i", val))

    def _write_long(self, val: int) -> None:
        self._write(struct.pack("<q", val))

    def _write_float(self, val: float) -> None:
        self._write(struct.pack("<f", val))

    def _write_double(self, val: float) -> None:
        self._write(struct.pack("<d", val))

    def _write_string(self, val: str) -> None:
        encoded = val.encode("utf-8")
        self._write_ushort(len(encoded))
        self._write(encoded)

    def _write_tag_header(self, tag_type: int, name: str) -> None:
        self._write_ubyte(tag_type)
        self._write_string(name)

    def _detect_tag_type(self, val: Any) -> int:
        if isinstance(val, bool):
            return TAG_BYTE
        if isinstance(val, int):
            return TAG_INT
        if isinstance(val, float):
            return TAG_DOUBLE
        if isinstance(val, str):
            return TAG_STRING
        if isinstance(val, bytes):
            return TAG_BYTE_ARRAY
        if isinstance(val, list):
            return TAG_LIST
        if isinstance(val, dict):
            return TAG_COMPOUND
        if isinstance(val, NBTByte):
            return TAG_BYTE
        if isinstance(val, NBTShort):
            return TAG_SHORT
        if isinstance(val, NBTLong):
            return TAG_LONG
        if isinstance(val, NBTFloat):
            return TAG_FLOAT
        raise ValueError(f"Cannot detect NBT type for {type(val)}: {val}")

    def _write_payload(self, val: Any) -> None:
        if isinstance(val, NBTByte):
            self._write_byte(val.value)
        elif isinstance(val, NBTShort):
            self._write_short(val.value)
        elif isinstance(val, NBTLong):
            self._write_long(val.value)
        elif isinstance(val, NBTFloat):
            self._write_float(val.value)
        elif isinstance(val, bool):
            self._write_byte(1 if val else 0)
        elif isinstance(val, int):
            self._write_int(val)
        elif isinstance(val, float):
            self._write_double(val)
        elif isinstance(val, str):
            self._write_string(val)
        elif isinstance(val, bytes):
            self._write_int(len(val))
            self._write(val)
        elif isinstance(val, list):
            self._write_list(val)
        elif isinstance(val, dict):
            self._write_compound_payload(val)
        else:
            raise ValueError(f"Unsupported NBT value type: {type(val)}")

    def _write_list(self, items: list) -> None:
        if not items:
            self._write_ubyte(TAG_END)
            self._write_int(0)
            return
        element_type = self._detect_tag_type(items[0])
        self._write_ubyte(element_type)
        self._write_int(len(items))
        for item in items:
            self._write_payload(item)

    def _write_compound_payload(self, data: dict[str, Any]) -> None:
        for key, val in data.items():
            tag_type = self._detect_tag_type(val)
            self._write_tag_header(tag_type, key)
            self._write_payload(val)
        self._write_ubyte(TAG_END)

    def write_root_compound(self, name: str, data: dict[str, Any]) -> bytes:
        """Write a root-level named compound tag and return the full NBT bytes."""
        self._buf = BytesIO()
        self._write_tag_header(TAG_COMPOUND, name)
        self._write_compound_payload(data)
        return self._buf.getvalue()


# Wrapper types for explicit NBT tag types

class NBTByte:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value & 0xFF


class NBTShort:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


class NBTLong:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


class NBTFloat:
    __slots__ = ("value",)

    def __init__(self, value: float) -> None:
        self.value = value
