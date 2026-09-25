"""「模板」页：模板/辅助视频二选一，两者共用随机/固定选法。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from config import AppConfig


def _make_templates(folder: Path, names: list[str]) -> Path:
    tpl = folder / "模板"
    tpl.mkdir(parents=True, exist_ok=True)
    for name in names:
        # 不真编码：load_library 只做后缀过滤与存在性，不读内容。
        (tpl / name).write_bytes(b"\x00" * 16)
    return tpl


app = QApplication.instance() or QApplication([])
window = MainWindow(AppConfig(), Path(__file__).resolve().parent.parent)
files_page = window._files_page
page = window._pages["模板"]
config = window.config
row = page._fixed_row
source = page._source_row

assert (
    config.tpl_window_w,
    config.tpl_window_h,
    config.tpl_window_center_x,
    config.tpl_window_center_y,
    config.tpl_window_feather,
) == (80, 100, 50, 50, 200)

# ── 左侧的「贴纸文件夹」整行去掉（「移动贴图文件夹」上一轮已挪走） ──
assert "sticker_folder" not in files_page._rows, files_page._rows.keys()
assert "moving_sticker_folder" not in files_page._rows
assert "main_folder" in files_page._rows and "output_folder" in files_page._rows
assert "tpl_folder" in page._rows and "background_folder" in page._rows

# ── 模板/辅助视频必须互斥，默认启用模板 ──
assert source.template.isChecked() and not source.auxiliary.isChecked()
assert config.tpl_enabled
assert page._win_group.isEnabled()

# ── 模板页：清单文件名那一行没了 ──
assert "tpl_manifest" not in page._rows, page._rows.keys()
# 字段本身留着（预设与老配置仍要读写往返），只是界面上没有入口
assert isinstance(config.tpl_manifest, str)

# ── 选择方式只有 随机 / 固定 两项 ──
pick_row = page._rows["tpl_pick"]
options = [
    pick_row._widget.itemText(i) for i in range(pick_row._widget.count())
]
assert options == ["随机", "固定"], options
assert config.tpl_pick == "随机", config.tpl_pick

# ── 老的「顺序」配置要被归成「随机」，界面显示的才是真跑的那套 ──
config.tpl_pick = "顺序"
page._normalize_pick()
assert config.tpl_pick == "随机", config.tpl_pick

# ── 固定模板那一行：显示框 + 选择按钮，且不给手打 ──
assert row.edit.isReadOnly(), "固定模板不该能手打（打错只会静默退回随机）"
assert row.button.text() == "选择"

with TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tpl = _make_templates(tmp, ["甲.mp4", "乙.mp4", "丙.mp4"])
    aux = tmp / "辅助视频"
    aux.mkdir()
    for name in ("背景甲.mp4", "背景乙.mp4"):
        (aux / name).write_bytes(b"\x00" * 16)
    config.tpl_folder = str(tpl)
    config.background_folder = str(aux)
    source.template.setChecked(True)
    page.reload_templates()

    # 选项来自磁盘：对话框里能挑到的就是这些
    assert sorted(row.available) == ["丙.mp4", "乙.mp4", "甲.mp4"], row.available

    # ── 随机 → 整行灰的（填了也不生效） ──
    config.tpl_pick = "随机"
    page._update_fixed_enabled()
    assert not row.isEnabled()
    assert page._fixed_hint.text() == "", page._fixed_hint.text()

    # ── 固定 → 可用，且提示还没选 ──
    config.tpl_pick = "固定"
    page._update_fixed_enabled()
    assert row.isEnabled()
    assert "还没选" in page._fixed_hint.text(), page._fixed_hint.text()

    # ── 选中即写进 config，且只显示文件名、不显示路径 ──
    row.value = row.resolve_choice(str(tpl / "乙.mp4"))
    assert config.tpl_fixed == "乙.mp4", config.tpl_fixed

    # ── 切到辅助视频：互斥状态、库列表、随机/固定全部共用 ──
    source.auxiliary.setChecked(True)
    assert source.auxiliary.isChecked() and not source.template.isChecked()
    assert not config.tpl_enabled
    assert not page._win_group.isEnabled(), "辅助视频不使用模板中央窗口"
    assert sorted(row.available) == ["背景乙.mp4", "背景甲.mp4"], row.available
    config.tpl_pick = "固定"
    page._update_fixed_enabled()
    row.value = row.resolve_choice(str(aux / "背景乙.mp4"))
    assert config.tpl_fixed == "背景乙.mp4"
    assert "都用这一个素材" in page._fixed_hint.text()

    # 切回模板后依然只能从模板目录挑。
    source.template.setChecked(True)
    row.value = "乙.mp4"
    assert row.edit.text() == "乙.mp4", row.edit.text()
    assert str(tmp) not in row.edit.text(), row.edit.text()
    assert "都用这一个素材" in page._fixed_hint.text(), page._fixed_hint.text()

    # 这一行也要参与实时预览（和 ParamRow 一样靠 value_changed 被连上）
    assert window._preview._debounce.isActive(), "固定模板改动没有触发预览刷新"

    # ── 库外的文件不许被选进来：引擎只会按名字在 tpl_folder 里找 ──
    outsider = tmp / "外面的模板.mp4"
    outsider.write_bytes(b"\x00" * 16)
    assert row.resolve_choice(str(outsider)) is None
    assert row.resolve_choice(str(tmp / "根本没有这个文件.mp4")) is None
    assert row.resolve_choice(str(tpl)) is None  # 目录也不是模板
    assert config.tpl_fixed == "乙.mp4", "选库外的东西不该改到已选的模板"

    # ── 引擎照这个选择取模板：每次都必须是同一张 ──
    from engine.template_lib import load_library

    library = load_library(config.tpl_folder, config.tpl_manifest)
    assert library.has(config.tpl_fixed)
    assert {library.pick(config.tpl_pick, config.tpl_fixed).path.name
            for _ in range(10)} == {"乙.mp4"}

    # 重扫磁盘（切回本页会调）不应把已选的那张弄丢，也不该改 value
    page.reload_templates()
    assert config.tpl_fixed == "乙.mp4", config.tpl_fixed
    assert row.value == "乙.mp4", row.value

    # ── 固定项被删掉了：当场说明会退回随机，位置留着让人看见是哪张没了 ──
    (tpl / "乙.mp4").unlink()
    page.reload_templates()
    assert "不在当前素材文件夹里" in page._fixed_hint.text(), page._fixed_hint.text()
    assert row.value == "乙.mp4", row.value   # 不改配置，用户可能只是改了个名
    library = load_library(config.tpl_folder, config.tpl_manifest)
    assert not library.has("乙.mp4")
    fallback = library.pick(config.tpl_pick, config.tpl_fixed)
    assert fallback is not None, "固定项缺失时不该返回 None"
    assert fallback.path.name in {"甲.mp4", "丙.mp4"}, fallback.path.name

    # ── 空目录：按钮没得选就置灰，占位说明原因 ──
    config.tpl_folder = str(tmp / "空目录")
    page.reload_templates()
    assert not row.button.isEnabled()
    assert "没有视频" in row.edit.placeholderText(), row.edit.placeholderText()
    # 值原样保留：模板目录只是临时填错，不该顺手把用户选好的模板清掉
    assert config.tpl_fixed == "乙.mp4", config.tpl_fixed

window.close()
print(f"template page test: OK (模板/辅助视频互斥，选法={options})")
