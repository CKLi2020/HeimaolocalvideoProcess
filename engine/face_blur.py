"""人脸检测 + 高斯模糊引擎。

使用 ONNX Runtime 进行人脸检测推理，支持 YuNet/SCRFD 模型。
对检测到的人脸区域做椭圆羽化高斯模糊。

依赖: opencv-python (cv2), onnxruntime, numpy
模型: face_detection_yunet_2023mar.onnx / scrfd_det_10g.onnx
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np
from engine import HIDDEN_SUBPROCESS


class FaceBlurEngine:
    """人脸检测与模糊处理引擎。"""

    # 模型输入尺寸映射
    INPUT_SIZES = {
        "yunet": (640, 640),
        "scrfd": (640, 640),
    }

    def __init__(
        self,
        model_path: Optional[str] = None,
        score_thresh: float = 0.5,
        detect_every: int = 1,
        blur_strength: int = 35,
        blur_expand: int = 100,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self._log = log_callback or print
        self._score_thresh = score_thresh
        self._detect_every = max(1, detect_every)
        self._blur_strength = blur_strength
        self._blur_expand = blur_expand
        self._available = False
        self._session = None
        self._detector = None
        self._model_type = "yunet"
        self._input_size = (320, 320)

        # 自动查找模型
        if model_path is None:
            candidates = [
                (
                    Path.cwd() / "resources" / "models"
                    / "face_detection_yunet_2023mar.onnx",
                    "yunet",
                ),
                (
                    Path(__file__).parent.parent.parent / "face_detection_yunet_2023mar.onnx",
                    "yunet",
                ),
                (
                    Path.cwd() / "face_detection_yunet_2023mar.onnx",
                    "yunet",
                ),
                (
                    Path(__file__).parent.parent.parent / "scrfd_det_10g.onnx",
                    "scrfd",
                ),
            ]
            for reference in Path.cwd().parent.glob("风无忧剪辑软件V1.6_1/*"):
                candidates.extend([
                    (reference / "face_detection_yunet_2023mar.onnx", "yunet"),
                    (reference / "scrfd_det_10g.onnx", "scrfd"),
                ])
            for c, mtype in candidates:
                if c.exists():
                    model_path = str(c)
                    self._model_type = mtype
                    break

        if model_path is None or not Path(model_path).exists():
            self._log("[人脸] 未找到人脸检测模型文件")
            return

        self._model_path = model_path
        self._input_size = self.INPUT_SIZES.get(self._model_type, (640, 640))

        try:
            if self._model_type == "yunet":
                if not str(model_path).isascii():
                    safe_model = (
                        Path(tempfile.gettempdir())
                        / "flowcut_face_detection_yunet.onnx"
                    )
                    shutil.copy2(model_path, safe_model)
                    model_path = str(safe_model)
                self._detector = cv2.FaceDetectorYN.create(
                    str(model_path), "", self._input_size,
                    score_threshold=self._score_thresh,
                )
            else:
                import onnxruntime as ort
                self._session = ort.InferenceSession(
                    str(model_path),
                    providers=["CPUExecutionProvider"],
                )
            self._available = True
            self._log(f"[人脸] 模型加载完成: {Path(model_path).name}")
        except Exception as e:
            self._log(f"[人脸] 模型加载失败: {e}")

    @property
    def is_available(self) -> bool:
        return self._available

    def detect_faces(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """检测图像中的所有人脸。"""
        if not self._available:
            return []

        h, w = image.shape[:2]
        iw, ih = self._input_size
        if self._model_type == "yunet" and self._detector is not None:
            self._detector.setInputSize((w, h))
            _, detections = self._detector.detect(image)
            if detections is None:
                return []
            return [
                (max(0, int(det[0])), max(0, int(det[1])),
                 min(w, int(det[2])), min(h, int(det[3])))
                for det in detections
                if float(det[-1]) >= self._score_thresh
            ]

        # 预处理
        resized = cv2.resize(image, (iw, ih))
        blob = resized.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))  # HWC → CHW
        blob = np.expand_dims(blob, axis=0)  # → NCHW

        # ONNX Runtime 推理
        outputs = self._session.run(None, {"input": blob})
        # outputs 可能有多个 (cls, bbox, kps)，取第一个
        if not outputs:
            return []

        detections = outputs[0]  # shape: (1, N, D)
        if len(detections.shape) < 3:
            return []

        faces = []
        for det in detections[0]:  # iterate over N detections
            # 根据模型类型解析输出
            if self._model_type == "scrfd":
                # SCRFD 10g: D=10, 格式: [x1,y1,x2,y2, score, kps...]
                score = float(det[4])
            else:
                # YuNet: 尝试最后一位作为置信度
                # 有些变体输出 10 维或 15 维
                if det.shape[0] >= 15:
                    score = float(det[14])
                elif det.shape[0] >= 10:
                    score = float(det[4])  # 假设类似 SCRFD 格式
                else:
                    continue

            if score < self._score_thresh:
                continue

            # 边界框 (前 4 个值归一化到 0-1)
            x1 = max(0, int(det[0] * w))
            y1 = max(0, int(det[1] * h))
            x2 = min(w, int(det[2] * w))
            y2 = min(h, int(det[3] * h))

            bw = x2 - x1
            bh = y2 - y1
            if bw > 4 and bh > 4:
                faces.append((x1, y1, bw, bh))

        return faces

    def blur_faces(
        self,
        image: np.ndarray,
        faces: List[Tuple[int, int, int, int]],
    ) -> np.ndarray:
        """对检测到的人脸区域进行椭圆羽化高斯模糊。

        Args:
            image: BGR 图像 (H, W, 3)
            faces: 人脸框列表 [(x, y, w, h), ...]

        Returns:
            处理后的图像（原地修改 + 返回）
        """
        if not faces:
            return image

        h, w = image.shape[:2]
        expand = self._blur_expand / 100.0  # 扩展比例
        sigma = max(1, int(self._blur_strength * 0.5))  # 映射强度到 sigma

        for (fx, fy, fw, fh) in faces:
            # 扩展人脸框
            ex = int(fw * expand * 0.5)
            ey = int(fh * expand * 0.5)
            x1 = max(0, fx - ex)
            y1 = max(0, fy - ey)
            x2 = min(w, fx + fw + ex)
            y2 = min(h, fy + fh + ey)
            bw = x2 - x1
            bh = y2 - y1

            if bw <= 0 or bh <= 0:
                continue

            # 提取人脸区域
            roi = image[y1:y2, x1:x2]

            # 高斯模糊（核大小自动计算，必须为奇数）
            ksize = max(3, sigma * 4 + 1)
            if ksize % 2 == 0:
                ksize += 1
            ksize = min(ksize, min(bw, bh) - 1)
            if ksize % 2 == 0:
                ksize -= 1
            if ksize < 3:
                ksize = 3

            blurred = cv2.GaussianBlur(roi, (ksize, ksize), sigma)

            # 椭圆羽化蒙版（柔化边界）
            mask = np.zeros((bh, bw), dtype=np.float32)
            center = (bw // 2, bh // 2)
            axes = (bw // 2 - 1, bh // 2 - 1)
            cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
            # 羽化边缘
            mask = cv2.GaussianBlur(mask, (ksize, ksize), sigma * 0.7)

            # 混合
            mask_3ch = np.stack([mask, mask, mask], axis=-1)
            blended = (roi * (1 - mask_3ch) + blurred * mask_3ch).astype(np.uint8)
            image[y1:y2, x1:x2] = blended

        return image

    def process_video(
        self,
        input_path: Path,
        output_path: Path,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """处理整个视频：逐帧检测人脸并模糊。

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            cancel_check: 取消检查

        Returns:
            True 表示成功
        """
        if not self._available:
            self._log("[人脸] 引擎不可用，跳过处理")
            shutil.copy2(str(input_path), str(output_path))
            return True

        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            self._log("[人脸] 无法打开视频")
            return False

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if total_frames < 1:
            total_frames = 1

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        frame_idx = 0
        last_faces: List[Tuple[int, int, int, int]] = []

        self._log(f"[人脸] 开始处理: {total_frames} 帧, {fps:.1f} fps")

        while True:
            if cancel_check and cancel_check():
                self._log("[人脸] 用户停止")
                break

            ret, frame = cap.read()
            if not ret:
                break

            # 每隔 detect_every 帧检测一次，其余帧复用上次结果
            if frame_idx % self._detect_every == 0:
                last_faces = self.detect_faces(frame)

            if last_faces:
                self.blur_faces(frame, last_faces)

            out.write(frame)
            frame_idx += 1

            # 进度日志（每 10%）
            if total_frames > 10 and frame_idx % max(1, total_frames // 10) == 0:
                pct = frame_idx * 100 // total_frames
                self._log(f"[人脸] 进度: {pct}% ({frame_idx}/{total_frames})")

        cap.release()
        out.release()

        self._log(f"[人脸] 处理完成: {frame_idx} 帧")
        return frame_idx > 0


def apply_face_blur_ffmpeg(
    input_path: Path,
    output_path: Path,
    model_path: Optional[str] = None,
    blur_strength: int = 35,
    blur_expand: int = 100,
    detect_every: int = 1,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """对视频应用人脸模糊，然后用 ffmpeg 重编码为高效的 H.264。

    工作流：
    1. OpenCV + YuNet 逐帧处理 → temp.mp4 (原始编码)
    2. ffmpeg 重编码为高效 H.264 → output_path

    Args:
        input_path: 输入视频
        output_path: 最终输出
        model_path: YuNet 模型路径
        blur_strength: 模糊强度 (1-100)
        detect_every: 检测间隔帧
        log_callback: 日志
        cancel_check: 取消检查

    Returns:
        True 表示成功
    """
    log = log_callback or print

    engine = FaceBlurEngine(
        model_path=model_path,
        blur_strength=blur_strength,
        blur_expand=blur_expand,
        detect_every=detect_every,
        log_callback=log,
    )

    if not engine.is_available:
        log("[人脸] 人脸模糊不可用")
        return False

    # Step 1: OpenCV 处理
    temp_raw = input_path.parent / f"{input_path.stem}_blur_raw.mp4"
    ok = engine.process_video(input_path, temp_raw, cancel_check=cancel_check)
    if not ok:
        return False

    # Step 2: ffmpeg 重编码（压缩 + 优化）
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("[人脸] 找不到 ffmpeg，使用原始编码输出")
        shutil.move(str(temp_raw), str(output_path))
        return True

    log("[人脸] ffmpeg 重编码...")
    cmd = [
        ffmpeg, "-y",
        "-i", str(temp_raw),
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, **HIDDEN_SUBPROCESS
    )
    if result.returncode != 0:
        log(f"[人脸] 重编码失败: {result.stderr[-200:]}")
        shutil.move(str(temp_raw), str(output_path))
    else:
        # 清理临时文件
        try:
            temp_raw.unlink()
        except OSError:
            pass

    return True
