"""Mode-scoped reproduction of Qilin's platform-validated, nonstandard SPS tail."""

from __future__ import annotations

from dataclasses import dataclass
from mmap import mmap
from pathlib import Path

from engine.mp4_tool import iter_mp4_boxes
from engine.native_core import core as _native_core


_CONTAINERS = (b"moov", b"trak", b"mdia", b"minf", b"stbl")


class SPSCompatibilityError(ValueError):
    pass


@dataclass(frozen=True)
class SPSCompatibilityResult:
    offset: int
    before: int
    after: int

    @property
    def changed(self) -> bool:
        return self.before != self.after


def _find_configurations(data: mmap) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []

    def visit(start: int, end: int, depth: int) -> None:
        for kind, position, header, size in iter_mp4_boxes(data, start, end):
            payload = position + header
            limit = position + size
            if depth < len(_CONTAINERS) and kind == _CONTAINERS[depth]:
                visit(payload, limit, depth + 1)
            elif depth == len(_CONTAINERS) and kind == b"stsd":
                if limit - payload < 8 or data[payload:payload + 4] != b"\0" * 4:
                    raise SPSCompatibilityError("Unsupported or truncated stsd header")
                entries = list(iter_mp4_boxes(data, payload + 8, limit))
                if len(entries) != int.from_bytes(data[payload + 4:payload + 8], "big"):
                    raise SPSCompatibilityError("Invalid stsd entry count")
                for entry_kind, entry_pos, entry_header, entry_size in entries:
                    if entry_kind not in (b"hvc1", b"hev1"):
                        continue
                    children = entry_pos + entry_header + 78
                    entry_end = entry_pos + entry_size
                    if children > entry_end:
                        raise SPSCompatibilityError("Truncated HEVC visual sample entry")
                    for child_kind, child_pos, child_header, child_size in iter_mp4_boxes(
                        data, children, entry_end
                    ):
                        if child_kind == b"hvcC":
                            found.append((child_pos + child_header, child_pos + child_size))

    visit(0, len(data), 0)
    if len(found) != 1:
        raise SPSCompatibilityError(
            f"Expected one HEVC configuration, found {len(found)}"
        )
    return found


def _sps_offset(data: mmap, start: int, end: int) -> tuple[int, int]:
    if end - start < 23:
        raise SPSCompatibilityError("Truncated HEVC configuration")
    if (
        data[start] != 1
        or data[start + 1] & 31 != 1
        or data[start + 16] & 3 != 1
        or data[start + 17] & 7 != 0
        or data[start + 18] & 7 != 0
        or data[start + 21] & 3 != 3
    ):
        raise SPSCompatibilityError("Only Main 8-bit 4:2:0 HEVC with 4-byte NAL lengths is supported")
    position = start + 23
    units: dict[int, tuple[int, int]] = {}
    for _ in range(data[start + 22]):
        if end - position < 3:
            raise SPSCompatibilityError("Truncated HEVC NAL array")
        kind = data[position] & 63
        count = int.from_bytes(data[position + 1:position + 3], "big")
        position += 3
        if kind not in (32, 33, 34) or kind in units or count != 1:
            raise SPSCompatibilityError("Expected exactly one VPS, SPS and PPS")
        if end - position < 2:
            raise SPSCompatibilityError("Truncated HEVC NAL length")
        length = int.from_bytes(data[position:position + 2], "big")
        position += 2
        if length < 3 or position + length > end:
            raise SPSCompatibilityError("Invalid HEVC NAL length")
        if data[position:position + 2] != bytes((kind << 1, 1)):
            raise SPSCompatibilityError("Unsupported HEVC NAL header")
        units[kind] = (position, position + length)
        position += length
    if position != end or set(units) != {32, 33, 34}:
        raise SPSCompatibilityError("Incomplete HEVC configuration")
    return units[33]


def apply_qilin_sps_compatibility(path: Path) -> SPSCompatibilityResult:
    """Change only the recognized SPS stop-bit byte; reject unknown layouts."""
    with path.open("r+b") as file:
        if file.seek(0, 2) == 0:
            raise SPSCompatibilityError("Empty Qilin output")
        with mmap(file.fileno(), 0) as data:
            start, end = _find_configurations(data)[0]
            sps_start, sps_end = _sps_offset(data, start, end)
            if sps_end - sps_start < 10:
                raise SPSCompatibilityError("Truncated SPS")
            before = data[sps_end - 1]
            try:
                after = int(_native_core.qilin_sps_compat_byte(data[sps_end - 8:sps_end]))
            except (TypeError, ValueError) as error:
                raise SPSCompatibilityError(str(error)) from error
            if not 0 <= after <= 255:
                raise SPSCompatibilityError("Native Qilin SPS result is outside one byte")
            if after == before:
                return SPSCompatibilityResult(sps_end - 1, before, before)
            data[sps_end - 1] = after
            data.flush()
            return SPSCompatibilityResult(sps_end - 1, before, after)
