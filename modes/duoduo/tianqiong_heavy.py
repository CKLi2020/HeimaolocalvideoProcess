#!/usr/bin/env python3
"""Clean-room reproduction of the observed Wangdian v3.2 heavy pipeline.

Every output redraws the observed parameter families. Pass --seed to make a
batch reproducible.
"""
from __future__ import annotations

import argparse, json, os, random, secrets, shutil, string, subprocess, tempfile
from datetime import datetime
from pathlib import Path

from engine.native_core import core

def run_process(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT)

ROOT = Path(__file__).resolve().parents[1] / "resources" / "tianqiong"
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"


def run(cmd: list[str], label: str) -> None:
    print(f"\n[{label}]\n{subprocess.list2cmdline(cmd)}", flush=True)
    run_process(cmd)


def probe(path: Path) -> dict:
    output = run_process([str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(output.decode("utf-8", "replace"))


def token(rng: random.Random, n=6) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(rng.choice(chars) for _ in range(n))


def make_variant(source: Path, output: Path, rng: random.Random, seed: int,
                 crf_override: float | None, keep_temp: bool) -> dict:
    duration = float(probe(source)["format"]["duration"])
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".temp_python_clone_", dir=output.parent))
    audio, effects, micro, video = (tmp / n for n in ("audio.m4a", "effects.m4a", "micro.m4a", "video.mp4"))
    muxed, raw_h264, clean_h264, remuxed, s1, s2, tagged = (
        tmp / n for n in ("muxed.mp4", "raw.h264", "clean.h264", "heavy_remux.mp4", "s1.mp4", "s2.mp4", "tagged.mp4")
    )
    noises = sorted(p for p in (ROOT / "noises").rglob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"})
    if not noises:
        raise RuntimeError("noises 目录中没有音频")

    plan = core.manluo_jinghong_plan("heavy", duration, len(noises), seed, crf_override)
    fps, crf, dct8 = plan["fps"], plan["crf"], plan["dct8"]
    x264, psy, gop = plan["x264"], plan["psy_rd"], plan["gop"]
    key_times = plan["forced_keyframes"]
    rate, extra_tempo, micro_tempo = plan["rate_factor"], plan["extra_tempo"], plan["micro_tempo"]
    chosen = [noises[index] for index in plan["noise_indices"]]
    delays, weights = plan["delays_ms"], plan["weights"]
    eq_freqs, eqs = plan["eq_frequencies"], plan["eq_filter"]
    effect_br, final_br = plan["effect_bitrate_k"], plan["final_bitrate_k"]
    tags, sei = plan["metadata"], plan["sei"]
    audio_title, audio_artist, fake_lavf = plan["audio_title"], plan["audio_artist"], plan["fake_lavf"]
    left, right = plan["echo_left"], plan["echo_right"]
    manifest = {"seed": seed, "fps": fps, "crf": crf, "x264": x264, "psy_rd": psy, "gop": gop,
                "forced_keyframes": key_times, "audio": {"rate_factor": rate, "extra_tempo": extra_tempo,
                "micro_tempo": micro_tempo, "noises": [str(x) for x in chosen], "delays_ms": delays,
                "weights": weights, "eq_frequencies": eq_freqs, "effect_bitrate_k": effect_br, "final_bitrate_k": final_br},
                "sei": sei, "metadata": tags, "audio_title": audio_title, "audio_artist": audio_artist, "fake_lavf": fake_lavf}
    try:
        run([str(FFMPEG), "-y", "-i", str(source), "-vn", "-c:a", "aac", "-b:a", "192k", str(audio)], "1/7 音频首遍")
        parts = (["[0:a]aresample=44100,anull[a_p]"] if rate == 1.0 else
                 [f"[0:a]asetrate=44100*{rate:.6f},aresample=44100,atempo={1/rate:.6f}[a_p]"])
        alabel = "a_p"
        if extra_tempo is not None:
            parts.append(f"[a_p]atempo={extra_tempo:.6f}[a_t]"); alabel = "a_t"
        parts += [f"[{alabel}]{eqs}[a_eq_pre]",
                  "[a_eq_pre]aphaser=type=t:in_gain=1.0:out_gain=0.95:delay=0.06:decay=0.06:speed=0.10[a_eq1]",
                  "[a_eq1]aphaser=type=t:in_gain=1.0:out_gain=0.92:delay=0.04:decay=0.04:speed=0.10[a_eq]"]
        for i, delay in enumerate(delays, 1): parts.append(f"[{i}:a]aresample=44100,adelay={delay}|{delay}[n{i-1}]")
        mix = "[a_eq]" + "".join(f"[n{i}]" for i in range(len(chosen)))
        parts += [f"{mix}amix=inputs={1+len(chosen)}:duration=first:weights=1 {' '.join(f'{w:.17f}' for w in weights)}[a_mix]",
                  "[a_mix]aformat=dblp,compand=attacks=0.05:decays=0.6:points=-70/-70|-40/-40|-18/-14|0/-2[a_agc]",
                  "[a_agc]channelsplit=channel_layout=stereo[L][R]",
                  f"[L]aecho=1.0:1.0:{left['delay']:.1f}:{left['decay']:.3f},adelay={left['left_delay']:.1f}|{left['right_delay']:.1f},volume={left['volume']:.2f}dB[L_v]",
                  f"[R]aecho=1.0:1.0:{right['delay']:.1f}:{right['decay']:.3f},adelay={right['left_delay']:.1f}|{right['right_delay']:.1f},volume={right['volume']:.2f}dB[R_v]",
                  "[L_v][R_v]join=inputs=2:channel_layout=stereo[a_out]"]
        cmd = [str(FFMPEG), "-y", "-i", str(audio)]
        for noise in chosen: cmd += ["-i", str(noise)]
        cmd += ["-filter_complex", ";".join(parts), "-map", "[a_out]", "-c:a", "aac", "-b:a", f"{effect_br}k", "-profile:a", "aac_low", "-map_metadata:s:a", "-1", str(effects)]
        run(cmd, "2/7 随机音频效果")

        vf = f"scale=1092:1940:flags=bicubic,crop=1080:1920:6:10,noise=alls=1:allf=t+u,setpts=N/({fps}*TB),tpad=stop_mode=clone:stop=2"
        x264s = ":".join(f"{k}={v}" for k, v in x264.items())
        run([str(FFMPEG), "-y", "-i", str(source), "-an", "-vf", vf, "-c:v", "libx264", "-preset", "medium",
             "-x264-params", x264s, "-psy-rd", psy, "-g", str(gop), "-keyint_min", str(gop-2), "-sc_threshold", "80",
             "-force_key_frames", ",".join(key_times), "-crf", str(crf), "-profile:v", "high" if dct8 else "main",
             "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-r", str(fps), str(video)], "3/7 随机视频编码")
        run([str(FFMPEG), "-y", "-i", str(effects), "-af", f"atempo={micro_tempo:.6f}", "-c:a", "aac", "-b:a", "192k", str(micro)], "4/7 音频微变速")
        vdur = float(probe(video)["format"]["duration"])
        run([str(FFMPEG), "-y", "-i", str(video), "-i", str(micro), "-c:v", "copy", "-c:a", "aac", "-b:a", f"{final_br}k",
             "-profile:a", "aac_low", "-af", "apad", "-map", "0:v:0", "-map", "1:a:0", "-map_metadata:s:a", "-1",
             "-metadata:s:a:0", f"encoder={fake_lavf}", "-metadata:s:a:0", f"title={audio_title}", "-metadata:s:a:0", f"artist={audio_artist}", "-t", f"{vdur:.3f}", str(muxed)], "5/7 音视频封装")
        # Heavy-only pass observed in memory: strip the MP4 wrapper, clean the
        # raw H.264 elementary stream, then remux it with the processed audio.
        run([str(FFMPEG), "-y", "-i", str(muxed), "-c:v", "copy", "-an", "-f", "h264", str(raw_h264)], "6a/7 导出裸 H.264")
        run([str(FFMPEG), "-y", "-i", str(raw_h264), "-c:v", "copy", "-bsf:v",
             "filter_units=remove_types=6,h264_metadata=aud=remove:delete_filler=1:colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0",
             "-an", "-f", "h264", str(clean_h264)], "6b/7 重度码流清洗")
        run([str(FFMPEG), "-y", "-r", str(fps), "-i", str(clean_h264), "-i", str(muxed),
             "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", str(remuxed)], "6c/7 裸流重封装")
        run([str(FFMPEG), "-y", "-i", str(remuxed), "-c:v", "copy", "-c:a", "copy", str(s1)], "6d/7 生成重度基片")
        run([str(FFMPEG), "-y", "-i", str(s1), "-c:v", "copy", "-c:a", "copy", "-bsf:v", f"h264_metadata=sei_user_data={sei}", str(s2)], "6e/7 注入随机 SEI")
        cmd = [str(FFMPEG), "-y", "-i", str(s2), "-c:v", "copy", "-c:a", "copy", "-map_metadata", "-1", "-brand", "isom"]
        for k, v in tags.items(): cmd += ["-metadata", f"{k}={v}"]
        cmd += ["-movflags", "+faststart", "-f", "mp4", str(tagged)]
        run(cmd, "7/7 随机容器标签")
        if output.exists():
            backup = output.with_suffix(output.suffix + ".bak"); shutil.copy2(output, backup); print("原输出备份：", backup)
        os.replace(tagged, output)
        stamp = datetime.now().timestamp() - plan["stamp_days"] * 86400
        os.utime(output, (stamp, stamp))
        manifest.update(output=str(output), probe=probe(output))
        return manifest
    finally:
        if keep_temp: print("中间文件保留于：", tmp)
        else: shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="复刻旺店 v3.2 重度档，并支持随机裂变")
    ap.add_argument("input", type=Path); ap.add_argument("output", type=Path)
    ap.add_argument("--fission", type=int, default=1); ap.add_argument("--seed", type=int)
    ap.add_argument("--keep-temp", action="store_true"); ap.add_argument("--crf", type=float, default=None)
    a = ap.parse_args()
    src, requested = a.input.resolve(), a.output.resolve()
    if not src.is_file(): ap.error(f"输入不存在：{src}")
    if a.fission < 1: ap.error("--fission 至少为 1")
    root_seed = a.seed if a.seed is not None else secrets.randbits(63)
    batch, results = random.Random(root_seed), []
    for i in range(1, a.fission + 1):
        vseed = batch.getrandbits(63); rng = random.Random(vseed)
        out = requested if a.fission == 1 else requested.with_name(f"{requested.stem}_v{i}_{token(rng)}_{datetime.now():%Y%m%d_%H%M%S}{requested.suffix}")
        results.append(make_variant(src, out, rng, vseed, a.crf, a.keep_temp))
    print(json.dumps({"root_seed": root_seed, "outputs": [x["output"] for x in results]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
