"""视频处理框架 · 主入口(UI)

原版模块 docstring(已从二进制取证)描述的设计,本地版照搬:
- 八个平台面板(抖音/快手/视频号/小红书/TK/百家/哔哩/多多),每个面板一个下拉框
  下拉框列出该平台目录下的全部模式,选中哪个平台的哪个模式就激活哪个模式
- 模式前后端入口独立: 客户端 modes/<平台>/mode_*.py ⇄ mode_defs/<平台>/<通道>.json
  以后新增模式两边各丢一个文件,界面下拉框自动出现,不写死
- 主视频/辅视频: 选择文件 或 选择文件夹(批量),批量时主辅按文件名顺序逐对配对
- 辅视频按模式启停: 当前模式不需要辅视频时整行变灰不可用
- 输出格式由模式定义决定(json 的 ext),客户端不写死

本地版的刻意差异(均已在代码处注明):
- 无登录/卡密/联网环节 —— 原版的登录窗由 MapoSafe 外壳绘制、卡密走第三方授权云
- 处理日志显示 ffmpeg 明文命令 —— 原版「命令经AES加密下发,不显示明文」的前提是
  命令来自服务器;本地版命令就在 mode_defs 里,藏着只妨碍排障
- 用系统标准窗口边框,不做 overrideredirect 自绘标题栏
- 处理方式用单个下拉框,不再同时给「处理模式下拉框 + GPU/CPU 勾选框」两套等价控件
"""

import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.build_config import BASE_DIR, CONFIG_PATH, load_config, resolve_path
from core.hardware import detect_gpu_profile, gpu_summary
from core.runner import FFmpegRunner, find_ffmpeg, find_ffprobe, probe_duration, verify_output
from modes import load_modes
from modes.base_mode import VIDEO_EXTS

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "本地版"

PROCESSOR_CPU = "cpu"
PROCESSOR_NVIDIA = "nvidia"
PROCESSOR_AMD = "amd"
PROCESSOR_LABELS = {
    PROCESSOR_NVIDIA: "GPU处理 N卡",
    PROCESSOR_AMD: "GPU处理 A卡",
    PROCESSOR_CPU: "CPU处理",
}

UI_FONT = "Microsoft YaHei UI"

# 调色板(深色)。原版有约 40 个 C_* 常量,部分在镜像里已损坏,这里重建一套自洽的。
C_BG = "#1b2233"
C_PANEL = "#232c42"
C_PANEL_ALT = "#2a3450"
C_BORDER = "#33405f"
C_TEXT = "#d7e0f2"
C_TEXT_DIM = "#8e9bb8"
C_ACCENT = "#48bfd4"
C_ACCENT_HOVER = "#3aa6b9"
C_OK = "#24df3f"
C_WARN = "#ffb454"
C_ERR = "#ff6b6b"
C_ACTIVE = "#2f6f8f"

DISCLAIMER = (
    "软件使用法律免责声明\n"
    "欢迎使用小花猫多平台视频处理软件。请在使用前确认:你拥有所处理素材的合法权利,"
    "处理与发布行为符合平台规则与当地法律法规。因使用本软件产生的任何法律责任由使用者承担。\n"
)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        warnings = []
        self.cfg = load_config()
        warnings.extend(load_config.warnings)

        self.title("%s %s" % (self.cfg.get("app_title") or "小花猫视频处理", APP_VERSION))
        self.geometry("1160x880")
        self.minsize(1000, 800)
        self.configure(fg_color=C_BG)
        self._center_window(1160, 880)

        self.ffmpeg_path = find_ffmpeg(self.cfg)
        self.ffprobe_path = find_ffprobe(self.cfg)
        self.gpu_profile = detect_gpu_profile(self.ffmpeg_path)
        self.runner = FFmpegRunner(self.cfg)

        self.stop_flag = threading.Event()
        self.ui_queue = queue.Queue()
        self.log_lines = []          # 日志的内存副本,见 _append_log

        self.mode_groups = {}
        self.current_mode = None
        self.platform_widgets = {}
        self._aux_widgets = []
        self._active_platform = None

        self.var_main = tk.StringVar()
        self.var_aux = tk.StringVar()
        self.var_out = tk.StringVar(value=resolve_path(
            self.cfg.get("default_output_dir") or "output"))
        initial = self._initial_processor()
        self.var_processor = tk.StringVar(value=initial)
        self.var_processor_label = tk.StringVar(value=PROCESSOR_LABELS[initial])
        self.var_pct = tk.StringVar(value="0%")

        self._build_ui()
        self._load_modes_into_ui()

        for text in warnings:
            self.log("⚠ " + text)
        self.log(DISCLAIMER)
        self.log("本机 GPU: %s" % gpu_summary(self.gpu_profile))
        if not self.ffmpeg_path:
            self.log("✘ 未找到 ffmpeg,请把 ffmpeg.exe 放入 bin/ 目录")
        if not self.ffprobe_path:
            self.log("✘ 未找到 ffprobe,产物无法校验,请把 ffprobe.exe 放入 bin/ 目录")
        self.log("配置: %s" % CONFIG_PATH)
        self.log("就绪。选择主视频后点「▶  开始处理」。")

        self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def _center_window(self, width, height):
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
            self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        except Exception:
            pass

    def _on_close(self):
        if self.runner.is_running:
            if not messagebox.askyesno("退出", "还有任务正在处理,确定退出吗?"):
                return
            self.stop_process()
        self.destroy()

    def _font(self, size=13, bold=False):
        return ctk.CTkFont(family=UI_FONT, size=size, weight="bold" if bold else "normal")

    def _panel(self, parent, title=""):
        frame = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=8,
                             border_width=1, border_color=C_BORDER)
        if title:
            ctk.CTkLabel(frame, text=title, font=self._font(13, True),
                         text_color=C_TEXT, anchor="w").pack(
                fill="x", padx=12, pady=(8, 2))
        return frame

    def _btn(self, parent, text, command, kind="normal", width=96):
        colors = {
            "normal": (C_PANEL_ALT, C_BORDER),
            "primary": (C_ACCENT, C_ACCENT_HOVER),
            "danger": ("#7a3030", "#96403f"),
            "accent": ("#2f5d8a", "#3a6f9f"),
        }[kind]
        return ctk.CTkButton(parent, text=text, command=command, width=width,
                             font=self._font(12), corner_radius=6,
                             fg_color=colors[0], hover_color=colors[1],
                             text_color=C_TEXT)

    def _entry(self, parent, var, width=380):
        return ctk.CTkEntry(parent, textvariable=var, width=width,
                            font=self._font(12), fg_color=C_BG,
                            border_color=C_BORDER, text_color=C_TEXT)

    def log(self, message):
        """worker 线程也会调;统一走 ui_queue 保证只在 UI 线程动控件。"""
        if threading.current_thread() is threading.main_thread():
            self._append_log(message)
        else:
            self.ui_queue.put(("log", message))

    def _append_log(self, message):
        text = str(message).rstrip()
        # 除了往控件里塞,同时留一份在内存里。Tk Text 的字符偏移不可靠
        # (按偏移切片会吞掉首字符),要按位置取日志就得有个真列表。
        self.log_lines.append(text)
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", text + "\n")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        shell = ctk.CTkFrame(self, fg_color=C_BG)
        shell.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_sidebar(shell)

        content = ctk.CTkFrame(shell, fg_color=C_BG)
        content.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._build_file_panel(content)
        self._build_platform_panel(content)
        self._build_task_panel(content)
        self._build_notice_bar(content)
        self._build_log_panel(content)

    def _build_sidebar(self, parent):
        sidebar = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=8,
                               border_width=1, border_color=C_BORDER, width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="小花猫视频处理", font=self._font(14, True),
                     text_color=C_ACCENT).pack(pady=(16, 2))
        ctk.CTkLabel(sidebar, text=APP_VERSION, font=self._font(11),
                     text_color=C_TEXT_DIM).pack(pady=(0, 14))

        ctk.CTkLabel(sidebar, text="本机信息", font=self._font(12, True),
                     text_color=C_TEXT, anchor="w").pack(fill="x", padx=14, pady=(4, 2))

        available = bool(self.gpu_profile.get("available"))
        dot = C_OK if available else C_TEXT_DIM
        ctk.CTkLabel(sidebar, text="●", font=self._font(12), text_color=dot,
                     anchor="w").pack(fill="x", padx=14)
        ctk.CTkLabel(sidebar, text=gpu_summary(self.gpu_profile), font=self._font(11),
                     text_color=C_TEXT_DIM, anchor="w", wraplength=160,
                     justify="left").pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(sidebar, text="输出目录", font=self._font(12, True),
                     text_color=C_TEXT, anchor="w").pack(fill="x", padx=14, pady=(6, 2))
        ctk.CTkLabel(sidebar, text=os.path.basename(self.var_out.get()) or "output",
                     font=self._font(11), text_color=C_TEXT_DIM, anchor="w",
                     wraplength=160, justify="left").pack(fill="x", padx=14)

        # 扩展点:「通用解析下载」入口原在这里(原版按钮文案就是「通用解析下载」)。
        # 本轮不做该区 —— 原实现依赖第三方付费解析接口,本地替代方案是 yt-dlp,
        # 但它对视频号基本无解、小红书/快手时好时坏,所以先留空。
        # 要加回来:在此 _btn(sidebar, "通用解析下载", self._show_parse_view),
        # 并让它在 content 里 pack 出另一个 Frame。

    def _build_file_panel(self, parent):
        panel = self._panel(parent, "📁 文件配置(选择文件夹即批量处理)")
        panel.pack(fill="x", pady=(0, 8))

        rows = ctk.CTkFrame(panel, fg_color="transparent")
        rows.pack(fill="x", padx=12, pady=(2, 10))

        # 主视频
        ctk.CTkLabel(rows, text="主视频:", font=self._font(12), width=64,
                     anchor="e").grid(row=0, column=0, padx=(0, 8), pady=4)
        self._entry(rows, self.var_main, width=430).grid(row=0, column=1, padx=(0, 8))
        self._btn(rows, "选择文件", self._pick_main_file, "accent").grid(row=0, column=2, padx=2)
        self._btn(rows, "选择文件夹", self._pick_main_dir, "accent", 104).grid(row=0, column=3, padx=2)

        # 辅视频
        ctk.CTkLabel(rows, text="辅视频:", font=self._font(12), width=64,
                     anchor="e").grid(row=1, column=0, padx=(0, 8), pady=4)
        self.aux_entry = self._entry(rows, self.var_aux, width=430)
        self.aux_entry.grid(row=1, column=1, padx=(0, 8))
        self.aux_file_btn = self._btn(rows, "选择文件", self._pick_aux_file)
        self.aux_file_btn.grid(row=1, column=2, padx=2)
        self.aux_dir_btn = self._btn(rows, "选择文件夹", self._pick_aux_dir, "normal", 104)
        self.aux_dir_btn.grid(row=1, column=3, padx=2)
        self._aux_widgets = [self.aux_entry, self.aux_file_btn, self.aux_dir_btn]

        # 输出路径
        ctk.CTkLabel(rows, text="输出路径:", font=self._font(12), width=64,
                     anchor="e").grid(row=2, column=0, padx=(0, 8), pady=4)
        self._entry(rows, self.var_out, width=430).grid(row=2, column=1, padx=(0, 8))
        self._btn(rows, "选择输出目录", self._pick_out, width=110).grid(row=2, column=2, padx=2)
        self._btn(rows, "打开文件夹", self._open_path, width=104).grid(row=2, column=3, padx=2)

        rows.grid_columnconfigure(1, weight=1)

    def _build_platform_panel(self, parent):
        panel = self._panel(parent, "处理平台 / 模式")
        panel.pack(fill="x", pady=(0, 8))

        self.platform_container = ctk.CTkFrame(panel, fg_color="transparent")
        self.platform_container.pack(fill="x", padx=12, pady=(2, 10))

    def _build_task_panel(self, parent):
        panel = self._panel(parent, "任务执行")
        panel.pack(fill="x", pady=(0, 8))

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(row, text="处理模式:", font=self._font(12)).pack(side="left", padx=(0, 8))
        self.processor_combo = ctk.CTkComboBox(
            row, values=self._available_processors(), width=170,
            variable=self.var_processor_label, state="readonly",
            font=self._font(12), dropdown_font=self._font(12),
            fg_color=C_BG, border_color=C_BORDER, button_color=C_PANEL_ALT,
            command=self._select_processor_label)
        self.processor_combo.pack(side="left")

        self.processor_status_label = ctk.CTkLabel(
            row, text=self._processor_text(), font=self._font(11),
            text_color=C_TEXT_DIM)
        self.processor_status_label.pack(side="left", padx=12)

        self.pbar = ctk.CTkProgressBar(panel, height=14, corner_radius=6,
                                       fg_color=C_BG, progress_color=C_ACCENT)
        self.pbar.set(0)
        self.pbar.pack(fill="x", padx=12, pady=(2, 6))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_start = self._btn(buttons, "▶  开始处理", self.start_process, "primary", 130)
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = self._btn(buttons, "■  停止处理", self.stop_process, "danger", 130)
        self.btn_stop.pack(side="left")
        ctk.CTkLabel(buttons, textvariable=self.var_pct, font=self._font(12),
                     text_color=C_TEXT_DIM).pack(side="left", padx=12)

    def _build_notice_bar(self, parent):
        # 原版是可滚动跑马灯(notice_canvas/_tick_notice_marquee)。本地版用静态条:
        # 跑马灯需要常驻 after() 循环,收益只是观感,不值这个复杂度。
        bar = ctk.CTkFrame(parent, fg_color=C_PANEL_ALT, corner_radius=6, height=30)
        bar.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            bar, text="公告：欢迎使用小花猫多平台软件，请遵守法律法规，合理合法使用本软件。",
            font=self._font(11), text_color=C_TEXT_DIM).pack(padx=12, pady=5)

    def _build_log_panel(self, parent):
        panel = self._panel(parent, "处理日志(本地版显示明文命令,便于排障)")
        panel.pack(fill="both", expand=True)

        self.txt_log = ctk.CTkTextbox(
            panel, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=C_BG, text_color=C_TEXT, border_width=0, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------------
    # 模式
    # ------------------------------------------------------------------
    def _load_modes_into_ui(self):
        try:
            self.mode_groups = load_modes()
        except Exception:
            self.mode_groups = {}
            self.log("✘ 模式加载异常:\n" + traceback.format_exc())

        for err in getattr(load_modes, "errors", []):
            self.log("⚠ " + str(err))

        for child in self.platform_container.winfo_children():
            child.destroy()
        self.platform_widgets = {}

        titles = list(self.mode_groups.keys())
        columns = 4
        for idx, title in enumerate(titles):
            modes = self.mode_groups[title]
            row, col = divmod(idx, columns)
            self._create_platform_panel(title, modes, row, col)

        for col in range(columns):
            self.platform_container.grid_columnconfigure(col, weight=1, uniform="plat")

        # 默认激活第一个平台的第一个模式
        if titles:
            first = titles[0]
            self._activate_platform(first)
        else:
            self.log("✘ 没有加载到任何处理模式:请检查 mode_defs/ 目录是否完整")

    def _create_platform_panel(self, title, modes, row, col):
        frame = ctk.CTkFrame(self.platform_container, fg_color=C_PANEL_ALT,
                             corner_radius=6, border_width=1, border_color=C_BORDER)
        frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        label = ctk.CTkLabel(frame, text=title, font=self._font(12, True),
                             text_color=C_TEXT)
        label.pack(padx=8, pady=(6, 2))

        names = [m.name for m in modes]
        var = tk.StringVar(value=names[0] if names else "")
        combo = ctk.CTkComboBox(
            frame, values=names or ["—"], variable=var, state="readonly",
            font=self._font(11), dropdown_font=self._font(11), width=180,
            fg_color=C_BG, border_color=C_BORDER, button_color=C_BORDER,
            command=lambda _v, t=title: self._activate_platform(t))
        combo.pack(padx=8, pady=(0, 8))

        self.platform_widgets[title] = {
            "frame": frame, "label": label, "combo": combo, "var": var, "modes": modes,
        }

    def _activate_platform(self, title):
        info = self.platform_widgets.get(title)
        if not info:
            return

        name = info["var"].get()
        mode = next((m for m in info["modes"] if m.name == name), None)
        if mode is None and info["modes"]:
            mode = info["modes"][0]

        self._active_platform = title
        self.current_mode = mode

        for other, data in self.platform_widgets.items():
            active = other == title
            data["frame"].configure(border_color=C_ACCENT if active else C_BORDER,
                                    fg_color=C_ACTIVE if active else C_PANEL_ALT)
            data["label"].configure(text_color=C_ACCENT if active else C_TEXT)

        self._update_aux_state()
        if mode is not None:
            self.log("当前模式: %s · %s" % (title, mode.name))
            help_text = self._mode_help_from_item(mode)
            if help_text:
                self.log("  " + help_text)

    def _mode_help_from_item(self, mode):
        """取值顺序照原版 _mode_help_from_item:help → heip → notice →
        announcement → gonggao → desc → description。

        `heip` 是原码里的错别字,保留 —— 团队的模式定义 json 里可能真写了这个键。
        """
        for key in ("help", "heip", "notice", "announcement", "gonggao", "desc", "description"):
            value = getattr(mode, key, None)
            if value:
                return str(value)
        return ""

    def _update_aux_state(self):
        """当前模式不需要辅视频时,整行置灰不可用。

        只置灰、不清空:清空会把用户已经选好的辅视频弄丢 ——
        点一下别的平台再点回来就得重选一遍。留着的旧值不会被用到,
        worker 只在 mode.needs_aux 为真时才读辅视频。
        """
        needs = bool(self.current_mode.needs_aux) if self.current_mode else False
        for widget in self._aux_widgets:
            try:
                widget.configure(state="normal" if needs else "disabled")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 处理方式
    # ------------------------------------------------------------------
    def _available_processors(self):
        options = []
        if self.gpu_profile.get("available"):
            vendor = self.gpu_profile.get("vendor")
            if vendor in PROCESSOR_LABELS:
                options.append(PROCESSOR_LABELS[vendor])
        options.append(PROCESSOR_LABELS[PROCESSOR_CPU])
        return options

    def _initial_processor(self):
        """启动时的默认处理方式,由配置决定。

        原版 config 里的 default_gpu / default_cpu 就是干这个的
        (内嵌默认值 default_gpu=True、default_cpu=False,即默认走 GPU)。
        default_cpu 优先:显式要求 CPU 时不因为检测到显卡就自作主张。
        """
        available = bool(self.gpu_profile.get("available"))
        vendor = self.gpu_profile.get("vendor")
        if available and vendor in PROCESSOR_LABELS and not self.cfg.get("default_cpu"):
            if self.cfg.get("default_gpu", True):
                return vendor
        return PROCESSOR_CPU

    def _select_processor_label(self, _label=None):
        label = self.var_processor_label.get()
        if label == PROCESSOR_LABELS[PROCESSOR_NVIDIA]:
            self.var_processor.set(PROCESSOR_NVIDIA)
        elif label == PROCESSOR_LABELS[PROCESSOR_AMD]:
            self.var_processor.set(PROCESSOR_AMD)
        else:
            self.var_processor.set(PROCESSOR_CPU)
        self.processor_status_label.configure(text=self._processor_text())

    def _processor_text(self):
        if not self.gpu_profile.get("available"):
            # 「自効」是原码错别字,照抄恢复出的原文,不改
            return "未检测到可用 GPU，已自効切到CPU处理"
        vendor = self.gpu_profile.get("vendor")
        label = PROCESSOR_LABELS.get(vendor, PROCESSOR_LABELS[PROCESSOR_CPU])
        if self.var_processor.get() == PROCESSOR_CPU:
            return "处理优先级: CPU处理"
        return "处理优先级: GPU优先(%s)，失败后自动转CPU" % label

    def _use_gpu(self):
        return (self.var_processor.get() in (PROCESSOR_NVIDIA, PROCESSOR_AMD)
                and bool(self.gpu_profile.get("available")))

    # ------------------------------------------------------------------
    # 文件选择
    # ------------------------------------------------------------------
    def _video_filetypes(self):
        exts = " ".join("*" + e for e in VIDEO_EXTS)
        return [("视频文件", exts), ("所有文件", "*.*")]

    def _pick_main_file(self):
        path = filedialog.askopenfilename(title="选择主视频", filetypes=self._video_filetypes())
        if path:
            self.var_main.set(path)

    def _pick_main_dir(self):
        path = filedialog.askdirectory(title="选择主视频文件夹(批量处理)")
        if path:
            self.var_main.set(path)

    def _pick_aux_file(self):
        path = filedialog.askopenfilename(title="选择辅视频", filetypes=self._video_filetypes())
        if path:
            self.var_aux.set(path)

    def _pick_aux_dir(self):
        path = filedialog.askdirectory(title="选择辅视频文件夹(批量时与主视频按顺序配对)")
        if path:
            self.var_aux.set(path)

    def _pick_out(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.var_out.set(path)

    def _open_path(self):
        path = self.var_out.get()
        if path and os.path.isdir(path):
            try:
                os.startfile(path)
            except Exception as exc:
                self.log("✘ 打开目录失败: %s" % exc)
        else:
            self.log("⚠ 输出目录还不存在: %s" % path)

    # ------------------------------------------------------------------
    # 收集状态 / 启动
    # ------------------------------------------------------------------
    @staticmethod
    def _list_videos(path):
        if not path or not os.path.isdir(path):
            return []
        found = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isfile(full) and name.lower().endswith(VIDEO_EXTS):
                found.append(full)
        return found

    def collect_state(self):
        return {
            "main_video": self.var_main.get().strip(),
            "aux_video": self.var_aux.get().strip(),
            "output_dir": self.var_out.get().strip() or "output",
            "threads": int(self.cfg.get("default_threads") or 6),
            "bitrate": str(self.cfg.get("default_bitrate") or "6000k"),
            "use_gpu": self._use_gpu(),
            "gpu_profile": self.gpu_profile,
            "output_naming": str(self.cfg.get("output_naming") or "hash"),
        }

    def start_process(self):
        if self.runner.is_running:
            self.log("⚠ 已有任务在跑,先停止再开始")
            return

        state = self.collect_state()
        mode = self.current_mode

        if mode is None:
            messagebox.showwarning("提示", "请先在平台下拉框选择一个处理模式")
            return
        if not state["main_video"]:
            messagebox.showwarning("提示", "请先选择主视频文件或文件夹")
            return
        if not self.ffmpeg_path:
            messagebox.showerror("提示", "未找到 ffmpeg,请把 ffmpeg.exe 放入 bin/ 目录")
            return
        if not self.ffprobe_path:
            messagebox.showerror("提示", "未找到 ffprobe,请把 ffprobe.exe 放入 bin/ 目录")
            return

        main_path = state["main_video"]
        if os.path.isdir(main_path):
            files = self._list_videos(main_path)
            if not files:
                messagebox.showwarning("提示", "主视频文件夹内没有视频文件")
                return
        elif os.path.isfile(main_path):
            files = [main_path]
        else:
            messagebox.showwarning("提示", "主视频路径不存在: %s" % main_path)
            return

        aux_list = []
        aux_path = state["aux_video"]
        if mode.needs_aux:
            if not aux_path:
                messagebox.showwarning("提示", "需要选择辅视频(文件或文件夹)")
                return
            if os.path.isdir(aux_path):
                aux_list = self._list_videos(aux_path)
                if not aux_list:
                    messagebox.showwarning("提示", "辅视频文件夹内没有视频文件")
                    return
            elif os.path.isfile(aux_path):
                aux_list = [aux_path]
            else:
                messagebox.showwarning("提示", "辅视频路径不存在: %s" % aux_path)
                return

        out_dir = resolve_path(state["output_dir"])
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("提示", "输出目录建不出来: %s" % exc)
            return

        if mode.needs_aux and len(aux_list) < len(files):
            self.log("提示: 辅视频 %d 个,少于主视频 %d 个,将循环复用配对"
                     % (len(aux_list), len(files)))

        self.stop_flag.clear()
        self.pbar.set(0)
        self.var_pct.set("0%")
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        self.log("")
        self.log("▶ 开始处理 [%s · %s] 共 %d 个任务%s"
                 % (self._active_platform or "-", mode.name, len(files),
                    " (批量)" if len(files) > 1 else ""))

        threading.Thread(target=self._worker,
                         args=(state, mode, files, aux_list, out_dir),
                         daemon=True).start()

    def stop_process(self):
        self.stop_flag.set()
        self.runner.stop()
        self.log("■ 已发送停止指令")

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------
    def _worker(self, state, mode, files, aux_list, out_dir):
        ok_cnt = fail_cnt = 0
        total = len(files)
        gpu_disabled_batch = False

        for idx, fpath in enumerate(files):
            if self.stop_flag.is_set():
                break

            aux_path = aux_list[idx % len(aux_list)] if aux_list else ""
            final_base = self._output_base(mode, fpath, out_dir, state)
            # 先写临时文件,校验通过再原子改名,避免中断留下半成品
            tmp_base = final_base + ".part"

            base_progress = 100.0 * idx / total
            span = 100.0 / total

            def on_progress(pct, base=base_progress, s=span):
                self.ui_queue.put(("progress", base + s * pct / 100.0))

            duration = probe_duration(self.cfg, fpath)
            attempts = []

            gpu_requested = bool(state.get("use_gpu")) and not gpu_disabled_batch
            want_gpu = gpu_requested and bool(mode.gpu_supported)
            if gpu_requested and not mode.gpu_supported:
                attempts.append((False, "当前模式仅支持CPU处理，已使用CPU原命令处理"))
            elif want_gpu and not mode.has_gpu_command():
                attempts.append((False, "当前模式未提供GPU编码命令，已使用CPU原命令处理"))
            elif want_gpu:
                attempts.append((True, None))
                attempts.append((False, "GPU处理失败，重新获取CPU原命令重试；本批次后续直接使用CPU"))
            else:
                attempts.append((False, None))

            code = None
            for attempt_i, (use_gpu, note) in enumerate(attempts):
                if self.stop_flag.is_set():
                    break
                if note:
                    self.log("  " + note)

                command, is_gpu, err = mode.render(
                    state, fpath, aux_path or None, use_gpu=use_gpu, out_base=tmp_base)
                if err:
                    # 模板本身渲不出来也走回退:GPU 模板写坏了不该让整个任务断在这里,
                    # CPU 模板还能跑就接着跑
                    self.log("  ✘ %s" % err)
                    code = -1
                    continue

                if attempt_i > 0 and not use_gpu and gpu_disabled_batch is False:
                    gpu_disabled_batch = True

                self._remove(tmp_base, mode.ext)
                code = self.runner.run(command, duration=duration,
                                       on_log=self.log, on_progress=on_progress)
                if code == 0:
                    break

            if self.stop_flag.is_set():
                self._remove(tmp_base, mode.ext)
                break

            if code != 0:
                tail = self.runner.tail(6)
                self.log("  ✘ 失败(退出码 %s)" % code)
                if tail:
                    self.log("    " + tail.replace("\n", "\n    "))
                self._remove(tmp_base, mode.ext)
                fail_cnt += 1
                continue

            tmp_file = "%s.%s" % (tmp_base, mode.ext)
            good, message = verify_output(
                self.cfg, tmp_file,
                expected_audio_tracks=getattr(mode, "expected_audio_tracks", None),
            )
            if not good:
                self.log("  ✘ 产物校验未通过: %s" % message)
                self.log("    已丢弃该产物 —— 宁可少一个,也不交付播不动的文件")
                self._remove(tmp_base, mode.ext)
                fail_cnt += 1
                continue

            final_file = "%s.%s" % (final_base, mode.ext)
            try:
                os.replace(tmp_file, final_file)
            except Exception as exc:
                self.log("  ✘ 产物改名失败: %s" % exc)
                self._remove(tmp_base, mode.ext)
                fail_cnt += 1
                continue

            ok_cnt += 1
            self.log("  ✔ 完成(%s): %s → %s   [%s]"
                     % (mode.name, os.path.basename(fpath),
                        os.path.basename(final_file), message))

        if self.stop_flag.is_set():
            self.log("■ 批量任务被手动停止")

        self.ui_queue.put(("done", ok_cnt, fail_cnt, total, out_dir))

    def _output_base(self, mode, src, out_dir, state):
        """产物路径(不带扩展名)。命名规则与 base_mode.build_params 保持一致。"""
        from modes.base_mode import source_basename, source_stem
        naming = getattr(mode, "output_naming", None) or state.get("output_naming") or "hash"
        if str(naming).lower() == "source":
            prefix = source_basename(src)
        else:
            prefix = source_stem(src)
        return os.path.join(out_dir, prefix + str(mode.output_suffix or ""))

    @staticmethod
    def _remove(base, ext):
        path = "%s.%s" % (base, ext)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI 轮询
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                message = self.ui_queue.get_nowait()
                kind = message[0]
                if kind == "log":
                    self._append_log(message[1])
                elif kind == "progress":
                    pct = float(message[1])
                    self.pbar.set(max(0.0, min(100.0, pct)) / 100.0)
                    self.var_pct.set("%.0f%%" % pct)
                elif kind == "done":
                    self._on_done(*message[1:])
        except queue.Empty:
            pass
        except Exception:
            self._append_log("⚠ 界面刷新异常:\n" + traceback.format_exc())

        self.after(120, self._poll_queue)

    def _on_done(self, ok_cnt, fail_cnt, total, out_dir):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self.pbar.set(1.0 if fail_cnt == 0 and ok_cnt else 0.0)
        self.var_pct.set("100%" if ok_cnt and not fail_cnt else "%d%%" % (
            100.0 * ok_cnt / total if total else 0))

        self.log("══ 任务结束: 成功 %d / 失败 %d / 共 %d ══" % (ok_cnt, fail_cnt, total))

        if fail_cnt == 0 and ok_cnt:
            messagebox.showinfo("处理完成",
                               "全部处理完成!\n成功: %d 个\n输出目录: %s" % (ok_cnt, out_dir))
        elif ok_cnt or fail_cnt:
            messagebox.showinfo("处理结束",
                               "处理结束\n成功: %d 个\n失败: %d 个\n详见日志"
                               % (ok_cnt, fail_cnt))


if __name__ == "__main__":
    App().mainloop()
