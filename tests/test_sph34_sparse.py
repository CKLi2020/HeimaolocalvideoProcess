"""黑猫03（SPH34后置稀疏时间轴）冒烟测试。"""

import json
import random
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from engine.sph34_sparse import build_sph34_sparse_command


def _ffmpeg(*args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
        check=True,
    )


def demo():
    with TemporaryDirectory(prefix="blackcat03_test_") as folder:
        folder = Path(folder)
        main, auxiliary, output = folder / "a.mp4", folder / "b.mp4", folder / "out.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "color=red:s=64x96:d=2",
            "-f", "lavfi", "-i", "sine=440:d=2",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", main,
        )
        _ffmpeg(
            "-f", "lavfi", "-i", "color=blue:s=64x96:d=35",
            "-f", "lavfi", "-i", "sine=880:d=35",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", auxiliary,
        )
        command = build_sph34_sparse_command(
            main, auxiliary, output, 64, 96, 2.0, 35.0,
            rng=random.Random(34),
        )
        no_insert_command = build_sph34_sparse_command(
            main, auxiliary, output, 64, 96, 2.0, 35.0,
            insert_duration=0.0,
        )
        no_insert_graph = no_insert_command[no_insert_command.index("-filter_complex") + 1]
        assert "[iv0]" not in no_insert_graph
        subprocess.run([str(value) for value in command], check=True, capture_output=True)
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "format=duration:stream=nb_read_frames",
                "-of", "json", str(output),
            ],
            check=True, capture_output=True, text=True,
        )
        info = json.loads(probe.stdout)
        duration = float(info["format"]["duration"])
        frames = int(info["streams"][0]["nb_read_frames"])
        assert 36.8 <= duration <= 37.2, duration
        assert 80 <= frames <= 120, frames
        assert output.stat().st_size > 1000


if __name__ == "__main__":
    demo()
    print("BlackCat03 SPH34 sparse timeline smoke test: OK")
