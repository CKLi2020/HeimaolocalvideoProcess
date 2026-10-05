from pathlib import Path
import json
import struct
import sys

import pytest

from modes.douyin.qilin_sps_compat import (
    SPSCompatibilityError,
    apply_qilin_sps_compatibility,
)


CAPTURED_EXTRA = bytes.fromhex(
    "01016000000090000000000078f000fc"
    "fdf8f800000f03200001001840010c01"
    "ffff0160000003009000000300000300"
    "78959809210001002442010101600000"
    "0300900000030000030078a003c08010"
    "e596566924caf016a040402010220001"
    "00074401c172b46240"
)
VPS = bytes.fromhex("40010c01ffff016000000300900000030000030078959809")
SPS = bytes.fromhex("420101016000000300900000030000030078a003c08010e596566924caf016a040402010")
PPS = bytes.fromhex("4401c172b46240")
VUI = "11010100000010000000100000000100000000"


def _box(kind: bytes, payload: bytes, extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _configuration(sps: bytes = SPS) -> bytes:
    return CAPTURED_EXTRA[:23] + b"".join(
        bytes((kind,)) + b"\0\1" + struct.pack(">H", len(nal)) + nal
        for kind, nal in ((32, VPS), (33, sps), (34, PPS))
    )


def _movie(extra: bytes = CAPTURED_EXTRA, tag: bytes = b"hev1", extended: bool = False) -> bytes:
    entry = _box(tag, b"\0" * 78 + _box(b"hvcC", extra, extended))
    nested = _box(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + entry)
    for kind in (b"stbl", b"minf", b"mdia", b"trak", b"moov"):
        nested = _box(kind, nested, extended)
    return _box(b"ftyp", b"isom\0\0\2\0") + nested + _box(b"mdat", b"unchanged media packets")


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "output.part.mp4"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("tag", [b"hev1", b"hvc1"])
@pytest.mark.parametrize("extended", [False, True])
def test_matches_captured_byte_change_and_preserves_every_other_byte(tmp_path, tag, extended):
    assert len(CAPTURED_EXTRA) == 105
    assert _configuration() == CAPTURED_EXTRA
    original = _movie(tag=tag, extended=extended)
    path = _write(tmp_path, original)
    result = apply_qilin_sps_compatibility(path)
    expected_offset = original.index(CAPTURED_EXTRA) + 92
    expected = bytearray(original)
    expected[expected_offset] = 0x08
    assert (result.offset, result.before, result.after, result.changed) == (
        expected_offset, 0x10, 0x08, True
    )
    assert path.read_bytes() == expected
    repeated = apply_qilin_sps_compatibility(path)
    assert not repeated.changed
    assert path.read_bytes() == expected


@pytest.mark.parametrize("padding", [2, 4, 6])
def test_locates_variable_sps_lengths_and_stop_bit_positions(tmp_path, padding):
    bits = VUI + "1"
    bits = "1" * ((-len(bits) - padding) % 8) + bits + "0" * padding
    tail = int(bits, 2).to_bytes(len(bits) // 8, "big")
    sps = SPS[:-8] + b"\x55" * padding + tail
    original = _movie(_configuration(sps))
    path = _write(tmp_path, original)
    result = apply_qilin_sps_compatibility(path)
    stop = 1 << padding
    assert result.before ^ result.after == stop | (stop >> 1)
    actual = path.read_bytes()
    assert len(actual) == len(original)
    assert [i for i, (left, right) in enumerate(zip(original, actual)) if left != right] == [
        result.offset
    ]
    assert not apply_qilin_sps_compatibility(path).changed


def test_already_captured_sps_is_unchanged(tmp_path):
    extra = bytearray(CAPTURED_EXTRA)
    extra[92] = 0x08
    original = _movie(bytes(extra))
    path = _write(tmp_path, original)
    assert not apply_qilin_sps_compatibility(path).changed
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"broken",
        struct.pack(">I4s", 1, b"moov"),
        _box(b"free", _box(b"hvcC", CAPTURED_EXTRA)),
        _box(b"mdat", _box(b"hvcC", CAPTURED_EXTRA)),
        _movie(tag=b"avc1"),
        _movie(CAPTURED_EXTRA[:22]),
        _movie(CAPTURED_EXTRA[:1] + b"\x02" + CAPTURED_EXTRA[2:]),
        _movie(CAPTURED_EXTRA + b"\0"),
        _movie(CAPTURED_EXTRA[:92] + b"\0" + CAPTURED_EXTRA[93:]),
        _movie(CAPTURED_EXTRA[:92] + b"\x11" + CAPTURED_EXTRA[93:]),
        _movie(_configuration(SPS[:-1] + b"\xff")),
        _movie() + _movie(),
    ],
)
def test_rejects_unknown_or_malformed_layout_without_writing(tmp_path, data):
    path = _write(tmp_path, data)
    with pytest.raises(ValueError):
        apply_qilin_sps_compatibility(path)
    assert path.read_bytes() == data


def test_reports_missing_alignment_space_without_writing(tmp_path):
    bits = VUI + "1"
    bits = "1" * (-len(bits) % 8) + bits
    sps = SPS[:-8] + int(bits, 2).to_bytes(len(bits) // 8, "big")
    original = _movie(_configuration(sps))
    path = _write(tmp_path, original)
    with pytest.raises(SPSCompatibilityError, match="alignment space"):
        apply_qilin_sps_compatibility(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("supported", [False, True])
def test_standalone_worker_applies_compatibility_or_reports_failure(
    tmp_path, monkeypatch, capsys, supported
):
    from modes.douyin import mode_douyin_qilin_worker as worker

    source = tmp_path / "input.mp4"
    reference = tmp_path / "reference.mp4"
    output = tmp_path / "processed.mp4"
    report = tmp_path / "verification.json"
    source.write_bytes(b"input")
    reference.write_bytes(b"reference")
    original = _movie() if supported else _movie(tag=b"avc1")
    monkeypatch.setattr(worker, "resolve_tool", lambda name: Path(name))
    monkeypatch.setattr(
        worker, "probe",
        lambda *_args: {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]},
    )
    monkeypatch.setattr(worker, "build_commands", lambda *_args: [[str(output)]])
    monkeypatch.setattr(worker, "run_command", lambda args: Path(args[0]).write_bytes(original))
    monkeypatch.setattr(
        sys, "argv",
        ["qilin", str(source), str(output), "--reference", str(reference), "--report", str(report)],
    )
    assert worker.main() == (0 if supported else 1)
    result = json.loads(report.read_text(encoding="utf-8"))
    messages = capsys.readouterr()
    if supported:
        assert result["status"] == "passed"
        assert result["platform_compatibility"]["nonstandard_sps"] is True
        assert "nonstandard SPS" in messages.err
        assert not apply_qilin_sps_compatibility(output).changed
    else:
        assert result["status"] == "processing_error"
        assert "HEVC configuration" in result["error"]
        assert "Processing failed" in messages.err
        assert output.read_bytes() == original
