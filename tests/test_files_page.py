"""左栏「文件夹设置」：框要够大、两行离得够开、危险开关不在界面上。

用户 2026-09-25 提的两件事：① 文件夹设置那个框太小、两行挤在一起，搞大一点、
距离拉远一点；② 「删除已用辅助视频」这一项去掉。

① 的间距是**可伸缩**的（两行之间塞了一个 Expanding 空档），不是写死的像素，
所以这里断言的是「至少拉开这么多」而不是等于某个数：字体、分辨率、以后调框高
都不该让这个用例变红，只有真的又挤回一条才算坏。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel

app = QApplication.instance() or QApplication([])

from app.main_window import MainWindow  # noqa: E402  (要在 QApplication 之后)
from config import AppConfig  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
window = MainWindow(AppConfig(), ROOT)
window.resize(1600, 950)
window.show()
app.processEvents()

page = window._files_page
config = window.config

# ── 只有「文件夹设置」这一个分组框 ──
groups = page.findChildren(QGroupBox)
assert len(groups) == 1, [g.title() for g in groups]
box = groups[0]
assert box.title() == "文件夹设置", box.title()

# ── 框要够高（原来只按内容撑到一百来像素） ──
assert box.height() >= 300, f"文件夹设置的框还是太小：{box.height()}px"

# ── 两行之间的距离要拉得开 ──
main_row = page._rows["main_folder"]
out_row = page._rows["output_folder"]
assert main_row.isVisible() and out_row.isVisible()
main_top = main_row.mapTo(box, main_row.rect().topLeft()).y()
out_top = out_row.mapTo(box, out_row.rect().topLeft()).y()
gap = out_top - (main_top + main_row.height())
assert main_top > 0, main_top
assert gap >= 80, f"两行还是挤在一起：{gap}px"
# 最后一行不许贴着框的下边缘
bottom_gap = box.height() - (out_top + out_row.height())
assert bottom_gap >= 16, f"最后一行贴着框底了：{bottom_gap}px"

# ── 辅助视频那一行仍然整行收起（label 和输入框都不占位），字段本身没被丢掉 ──
aux_row = page._rows["background_folder"]
assert not aux_row.isVisible(), "辅助视频那行该收起"
labels = {lb.text(): lb for lb in box.findChildren(QLabel)}
assert "辅助视频文件夹" in labels, "标签都没建出来，setRowVisible 无从谈起"
assert not labels["辅助视频文件夹"].isVisible(), "label 还露着"
# 留在 _rows 里：config.json 与预设继续读写往返
assert aux_row.path == str(config.background_folder)
# 可见的两行仍然可以查看/粘贴路径（只是「固定模板」那种才要只读）
assert not main_row.edit.isReadOnly() and not out_row.edit.isReadOnly()

# ── 重排之后两行都还得写到 config 上（path_changed → _set_folder） ──
fired = []
page.paths_changed.connect(lambda: fired.append(1))
main_row.edit.setText(str(ROOT / "主视频"))
out_row.edit.setText(str(ROOT / "蒙版成品"))
assert config.main_folder == str(ROOT / "主视频"), config.main_folder
assert config.output_folder == str(ROOT / "蒙版成品"), config.output_folder
assert len(fired) == 2, f"paths_changed 该发两次，实得 {len(fired)}"

# ── 「删除已用辅助视频」界面上没有了 ──
texts = [c.text() for c in window.findChildren(QCheckBox)]
assert "删除已用辅助视频" not in texts, texts
assert not hasattr(window, "_delete_aux"), "开关还在，只是没显示"
# 能力与字段本身留着：老配置/预设里的值不许因为这个改动被丢掉
assert config.delete_used_aux is False
config.delete_used_aux = True
assert AppConfig.from_dict(config.to_dict()).delete_used_aux is True, "字段往返丢了"

# ── 同一行里的「裂变」没被误删 ──
assert window._repeat_count is not None
window._repeat_count.setValue(3)
assert config.repeat_count == 3, config.repeat_count

window.close()
print(f"files page test: OK (gap {gap}px, bottom {bottom_gap}px, box {box.height()}px)")
