"""黑猫02（SPH34）媒体结构冒烟测试。"""

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from engine.sph_channels import build_sph34_command, hide_sph34_edges


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def demo():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        main, auxiliary, output = root / "a.mp4", root / "b.mp4", root / "out.mp4"
        _ffmpeg("-f", "lavfi", "-i", "color=red:s=180x320:d=1",
                "-f", "lavfi", "-i", "sine=440:d=1", "-shortest",
                "-c:v", "libx264", "-c:a", "aac", main)
        _ffmpeg("-f", "lavfi", "-i", "color=blue:s=180x320:d=1",
                "-f", "lavfi", "-i", "sine=880:d=1", "-shortest",
                "-c:v", "libx264", "-c:a", "aac", auxiliary)
        subprocess.run(build_sph34_command(main, auxiliary, output, 180, 320), check=True, capture_output=True)
        hide_sph34_edges(output, 1.0)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", output],
            check=True, capture_output=True, text=True,
        )
        assert abs(float(probe.stdout) - 1.0) < 0.1
        assert output.stat().st_size > 1000


if __name__ == "__main__":
    demo()
    print("SPH34 channel smoke test: OK")
