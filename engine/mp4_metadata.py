"""Write randomized camera and iTunes metadata to MP4 containers."""

from __future__ import annotations

import secrets
import struct
from datetime import date, timedelta
from pathlib import Path


SHENZHEN_LOCATIONS = (
    ("深圳市民中心", "+22.5431+114.0579/"), ("世界之窗", "+22.5362+113.9744/"),
    ("深圳湾公园", "+22.5192+113.9517/"), ("深圳人才公园", "+22.5168+113.9419/"),
    ("莲花山公园", "+22.5549+114.0560/"), ("东门老街", "+22.5469+114.1180/"),
    ("大梅沙海滨公园", "+22.5964+114.3079/"), ("小梅沙", "+22.5932+114.3214/"),
    ("梧桐山", "+22.5836+114.2148/"), ("华侨城", "+22.5404+113.9866/"),
    ("欢乐港湾", "+22.5539+113.8835/"), ("前海石公园", "+22.5160+113.8950/"),
    ("海上世界", "+22.4854+113.9150/"), ("深圳大学", "+22.5330+113.9303/"),
    ("南头古城", "+22.5401+113.9236/"), ("福田红树林", "+22.5255+114.0129/"),
    ("甘坑古镇", "+22.6525+114.0655/"), ("杨梅坑", "+22.5557+114.5822/"),
    ("较场尾", "+22.5965+114.5077/"), ("光明虹桥公园", "+22.7524+113.9444/"),
)

ITUNES_ATOMS = {
    "title": b"\xa9nam", "artist": b"\xa9ART", "album": b"\xa9alb",
    "comment": b"\xa9cmt", "encoder": b"\xa9too",
}


def generate_camera_metadata() -> dict[str, str]:
    location_name, location = secrets.choice(SHENZHEN_LOCATIONS)
    first_day = date(2026, 6, 1)
    last_day = date(2026, 8, 31)
    capture_day = first_day + timedelta(days=secrets.randbelow((last_day - first_day).days + 1))
    capture_date = capture_day.isoformat()
    return {
        "make": "Canon", "model": "EOS R8", "location": location,
        "location_name": location_name, "capture_period": capture_date,
        "capture_date": capture_date, "metadata_status": "restored/inferred",
    }


def generate_itunes_metadata() -> dict[str, str]:
    token = secrets.token_hex(4).upper()
    return {
        "title": f"城市影像 {token}", "artist": f"影像工作室 {token[:5]}",
        "album": f"深圳记录 {token[1:7]}", "comment": f"素材整理 {token[2:]}",
        "software_name": f"MediaStudio {token[:2]}.{token[2:4]}",
        "encoder": "Wxmm_9020230",
    }


def _atom(atom_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), atom_type) + payload


def _itunes_meta(tags: dict[str, str]) -> bytes:
    values = []
    for key, atom_type in ITUNES_ATOMS.items():
        value = tags.get(key)
        if value is None:
            continue
        encoded = value.encode("utf-8")
        values.append(_atom(atom_type, struct.pack(">I4sII", 16 + len(encoded), b"data", 1, 0) + encoded))
    hdlr = _atom(b"hdlr", struct.pack(">II4s", 0, 0, b"mdir") + b"\0" * 13)
    return _atom(b"meta", struct.pack(">I", 0) + hdlr + _atom(b"ilst", b"".join(values)))


def _mdta_meta(tags: dict[str, str]) -> bytes:
    keys = []
    values = []
    for index, (key, value) in enumerate(tags.items(), 1):
        encoded_key = key.encode("utf-8")
        keys.append(_atom(b"mdta", encoded_key))
        encoded_value = str(value).encode("utf-8")
        data = struct.pack(">I4sII", 16 + len(encoded_value), b"data", 1, 0) + encoded_value
        values.append(struct.pack(">I", 8 + len(data)) + struct.pack(">I", index) + data)
    keys_atom = _atom(b"keys", struct.pack(">II", 0, len(keys)) + b"".join(keys))
    hdlr = _atom(b"hdlr", struct.pack(">II4s", 0, 0, b"mdta") + b"\0" * 13)
    return _atom(b"meta", struct.pack(">I", 0) + hdlr + keys_atom + _atom(b"ilst", b"".join(values)))


def _new_udta(itunes: dict[str, str], camera: dict[str, str]) -> bytes:
    mdta = dict(camera)
    mdta["software_name"] = itunes["software_name"]
    return _atom(b"udta", _itunes_meta(itunes) + _mdta_meta(mdta))


def _top_atom(data: bytes, wanted: bytes) -> tuple[int, int]:
    offset = 0
    while offset + 8 <= len(data):
        size, atom_type = struct.unpack_from(">I4s", data, offset)
        if size < 8 or offset + size > len(data):
            break
        if atom_type == wanted:
            return offset, size
        offset += size
    return -1, 0


def _children(data: bytes, parent_pos: int, parent_size: int):
    offset, end = parent_pos + 8, parent_pos + parent_size
    while offset + 8 <= end:
        size, atom_type = struct.unpack_from(">I4s", data, offset)
        if size < 8 or offset + size > end:
            break
        yield offset, size, atom_type
        offset += size


def _adjust_chunk_offsets(data: bytearray, moov_pos: int, moov_size: int, threshold: int, delta: int) -> None:
    containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta"}

    def visit(parent_pos: int, parent_size: int) -> None:
        for atom_pos, atom_size, atom_type in _children(data, parent_pos, parent_size):
            if atom_type in containers:
                visit(atom_pos, atom_size)
            elif atom_type in (b"stco", b"co64") and atom_size >= 16:
                count = struct.unpack_from(">I", data, atom_pos + 12)[0]
                width, fmt = (4, ">I") if atom_type == b"stco" else (8, ">Q")
                if atom_pos + 16 + count * width > atom_pos + atom_size:
                    raise ValueError(f"invalid {atom_type.decode()} atom")
                for index in range(count):
                    value_pos = atom_pos + 16 + index * width
                    value = struct.unpack_from(fmt, data, value_pos)[0]
                    if value >= threshold:
                        struct.pack_into(fmt, data, value_pos, value + delta)

    visit(moov_pos, moov_size)


def write_randomized_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Replace the movie-level udta atom and update faststart chunk offsets."""
    data = bytearray(path.read_bytes())
    moov_pos, moov_size = _top_atom(data, b"moov")
    if moov_pos < 0:
        raise ValueError(f"MP4 缺少 moov atom：{path}")
    mdat_pos, _ = _top_atom(data, b"mdat")
    camera = generate_camera_metadata()
    itunes = generate_itunes_metadata()
    udta = _new_udta(itunes, camera)

    old_pos = old_size = 0
    for atom_pos, atom_size, atom_type in _children(data, moov_pos, moov_size):
        if atom_type == b"udta":
            old_pos, old_size = atom_pos, atom_size
            break
    insert_pos = old_pos or (moov_pos + moov_size)
    data = data[:insert_pos] + udta + data[insert_pos + old_size:]
    delta = len(udta) - old_size
    new_moov_size = moov_size + delta
    struct.pack_into(">I", data, moov_pos, new_moov_size)
    if moov_pos < mdat_pos and delta:
        _adjust_chunk_offsets(data, moov_pos, new_moov_size, mdat_pos, delta)

    temporary = path.with_name(path.name + ".metadata.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"camera_metadata": camera, "itunes_metadata": itunes}
