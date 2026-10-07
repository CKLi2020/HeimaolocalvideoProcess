---
name: video-channel-worker-integration
description: 'Integrate standalone Python video worker scripts as platform processing channels in this repository. Use when adding or replacing a channel, adapting worker command construction to BaseMode, supporting CPU plus NVIDIA/AMD GPU encoding, preserving automatic CPU fallback, or validating a channel merge end to end.'
argument-hint: 'Describe the worker script, platform, channel name, input roles, and channels to replace'
---

# Video Channel Worker Integration

For the complete capture-to-Release workflow, new channels, historical-channel
derivation, or explicitly requested in-place updates, use
[Video Channel Lifecycle](../video-channel-lifecycle/SKILL.md). This legacy skill
remains available for worker-only integrations. The new skill is standalone and
documents the current service execution path, multi-setting integration, and
tool-root `capture` output policy.

Use this workflow to turn one or more standalone Python video workers into selectable channels in this repository. A completed integration must work on CPU-only machines and use supported NVIDIA or AMD hardware encoding when selected.

## Required Inputs

Identify before editing:

- Worker script and its current CLI arguments.
- Target platform key, channel ID, a distinctive literary Chinese display name, suffix, and output extension.
- Meaning of the main and auxiliary video inputs.
- Existing channels that must be removed or replaced.
- Output codec. Choose GPU encoders for the same codec, not merely the same container.

For each new integration, choose a fresh, distinctive, literary Chinese channel name rather than a generic technical label or a name already used by another channel. Make the name consistent across the UI, help text, and tests.

When a channel is moved into the protected native core, append the integration date in `MMDD` form to its user-facing name (for example `云麒1004`) while keeping its stable channel ID unchanged. Follow the protected-core pattern end to end: add a development-equivalent API in `engine/dev_core.py`, the matching VMProtect-wrapped Cython API in `native_src/flowcut_core.pyx`, register it in `engine/native_core.py`, add its marker and import smoke assertion to `scripts/build_native.ps1`, make the worker consume only the core API, and add a focused deterministic core test.

Every newly integrated channel must be placed first in its platform's channel list, even when the user does not repeat this requirement. Give it a `sort_priority` lower than all existing channels in that platform, and add or update a focused assertion that the new channel ID is first. If several channels are integrated together, order the newly integrated channels ahead of all pre-existing channels and assert the intended order.

If the worker requires more input roles than the UI exposes, define an explicit mapping. Do not silently require a hidden file. A reference used only to derive stream settings should normally be probed from the main input.

## Integration Procedure

### 1. Trace the Owning Path

Read only the relevant surfaces first:

- `modes/base_mode.py` for `BaseMode.render()` and output naming.
- `modes/__init__.py` for discovery, IDs, JSON merging, and sorting.
- `main.py` for main/aux pairing, GPU attempts, CPU fallback, temporary output, and verification.
- `core/hardware.py` for the detected encoder profile.
- The worker and the nearest existing custom mode/test.

State one local hypothesis and one focused check before editing.

### 2. Extract a Reusable Command Builder

Keep the worker CLI functional. Extract command assembly into a side-effect-free function that returns `list[str]`, then let the existing `process()` execute it.

Use this shape when practical:

```python
def build_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    reference: dict[str, Any],
    threads: int,
    video_encoder: str = "libx265",
    encoder_options: Sequence[str] = (),
) -> list[str]:
    ...
```

Add extra input paths, such as an effect video, before `output_path`. Preserve defaults so existing CLI callers still use the original CPU behavior.

Do not make the mode launch the worker's Python CLI as a nested subprocess. Reuse the builder and let `FFmpegRunner` own execution, progress, cancellation, logs, and error handling.

### 3. Separate CPU-Only and GPU-Safe Options

The CPU path may use codec-specific options such as `-x265-params`, `-crf`, `+ilme`, or `+ildct`. Never pass those blindly to hardware encoders.

Build the command in three sections:

1. Common inputs, filters, maps, color metadata, timing, audio, and muxing.
2. CPU options when the encoder is `libx265` or `libx264`.
3. GPU options supplied for the selected vendor.

For HEVC channels in this repository:

- NVIDIA encoder: `hevc_nvenc`.
- AMD encoder: `hevc_amf`.
- MP4 tag: `hvc1`.
- Use `gpu_profile['hevc_encoder']`, not `h264_encoder`.
- Omit x265-only and software interlacing options from hardware commands unless the target encoder documentation explicitly supports them.

Verify option names against `ffmpeg -hide_banner -h encoder=<encoder>` rather than assuming H.264 and HEVC options are identical.

### 4. Add the Platform Mode Adapter

Create `modes/<platform>/mode_<channel>.py` and expose `MODE`.

The mode must define:

- Stable `id` in `<platform>/<channel>` form.
- A distinctive literary Chinese user-facing `name`.
- Correct `needs_aux` value.
- `gpu_supported = True` when both rendering paths are implemented.
- Output suffix, naming policy, extension, and help text.

For a custom renderer:

1. Validate main and auxiliary files.
2. Resolve `use_gpu` from the explicit argument, falling back to state.
3. Select CPU or the profile's codec-matching GPU encoder.
4. Probe input metadata needed by the builder.
5. Honor `out_base` and append exactly one extension.
6. Return `(command_string, is_gpu, error)`.
7. Convert the argv list with `subprocess.list2cmdline()` on Windows.

Override `has_gpu_command()` to return `True` for custom GPU rendering. This is required because `main.py` checks it before calling `render()` and uses it to schedule GPU-to-CPU fallback.

### 5. Preserve Fallback Behavior

Do not implement a second fallback loop inside the mode. `main.py` already performs:

1. GPU attempt when the selected profile is available and the mode supports GPU.
2. CPU retry after GPU render or execution failure.
3. CPU-only processing for the rest of that batch after the first GPU failure.

A GPU render error should be descriptive and return `is_gpu=True`. The subsequent CPU call must produce a valid software command.

### 6. Update Channel Definitions Safely

Remove obsolete `mode_defs/<platform>/*.json` files only when replacement was requested. Check that no JSON shares an ID with an unintended local mode. Preserve unrelated user changes.

Remember that a local `mode_*.py` is discovered automatically. A matching JSON may override its allowed fields, including `gpu_supported`, so inspect both sides.

### 7. Add Focused Tests

Create or update a test that verifies:

- The platform exposes exactly the expected channel IDs after replacement.
- `needs_aux`, `gpu_supported`, and `has_gpu_command()` are correct.
- CPU rendering performs a real short FFmpeg conversion.
- `verify_output()` accepts the result.
- A synthetic NVIDIA profile generates the expected NVIDIA encoder.
- A synthetic AMD profile generates the expected AMD encoder.
- GPU commands do not contain CPU-codec-only options.
- Output paths with `.part` follow the runner's temporary-file convention.

Do not claim real GPU execution unless it ran on compatible hardware. On CPU-only hardware, validate generated GPU commands and rely on `core.hardware.encoder_self_test()` to gate selection on deployed machines.

### 8. Validate the Merge

Run checks in this order:

1. Syntax/editor diagnostics for every changed Python file.
2. Focused channel test, for example `python test_douyin_0921.py`.
3. A `load_modes()` assertion for IDs and GPU flags.
4. Relevant existing regression scripts.
5. Repository self-test when practical.
6. Working-tree diff/status to confirm no unrelated files were changed or reverted.

If the full self-test cannot finish in the tool environment, report exactly which focused paths passed and what remains unverified.

Always set an appropriate `sort_priority` (lower values sort earlier) so the newly integrated channel appears first in its platform list, and add a focused assertion for the first channel ID.

## Current Reference Implementation

Use these files as the local pattern:

- `mode_a1_worker.py`: single-input worker with reusable CPU/GPU command construction.
- `mode_douyin_tongyao_worker.py`: main plus auxiliary-effect worker.
- `modes/douyin/hevc_gpu.py`: NVIDIA/AMD HEVC selection and options.
- `modes/douyin/mode_zhandou0921.py`: no-aux custom channel adapter.
- `modes/douyin/mode_yunqi_qilin.py`: 云麒1004 single-input adapter for the multi-stage 麒麟 worker, with HEVC CPU/NVIDIA/AMD encoding and staged runner execution.
- 云麒1004 is an example of the first-in-platform ordering rule (`sort_priority = -200`); apply the same rule to every subsequently integrated channel, not just 云麒1004.
- `modes/douyin/mode_douyin_qilin_worker.py`: reusable Qilin pipeline command builder. The original tool generates randomized 198x188 6x6/4x6 color mosaics plus randomized grid, audio, seek, keyframe, and metadata values on every run. Preserve those behavioral classes instead of substituting solid-color assets or freezing one captured graph. The 云麒1004 worker obtains this complete random pipeline plan from `native_core.qilin_pipeline_plan`; do not move the protected implementation back into the worker. Captured graphs in `modes/douyin/qilin_artifacts/` are evidence for ranges, not production templates.
- For captured multi-stage modes, a stable ffprobe signature is not visual equivalence. Preserve transient assets whenever possible and add assertions for their dimensions, content diversity, and per-run randomness.
- `modes/douyin/mode_tongyao0921.py`: auxiliary-input custom channel adapter.
- `test_douyin_0921.py`: CPU execution plus NVIDIA/AMD command assertions.
- `modes/kuaishou/h264_gpu.py`: NVIDIA/AMD H.264 selection and options.
- `modes/kuaishou/mode_silie0921.py`: no-aux Matroska worker channel adapter.
- `test_kuaishou_silie0921.py`: CPU execution plus NVIDIA/AMD command assertions.
- `modes/shipinhao/h264_gpu.py`: NVIDIA/AMD H.264 selection for auxiliary-input workers.
- `modes/shipinhao/mode_caishen0923.py`: 财神主视频 + 辅助视频 adapter.
- `modes/shipinhao/mode_tianjia0923.py`: 天家主视频 + 辅助视频 adapter.
- `modes/shipinhao/mode_liuying_v15.py`: 流萤 needs only the main video; the adapter probes it as its own reference, so the user does not select an auxiliary video. It has always-on fixed perspective flash positions; additional random enhancement is disabled with no UI switch. Supports 1–100 copies via `supports_copies` and `output_count(state)`: the service independently builds and runs the worker command for each copy of each input, rather than duplicating an existing output. Provide `prepare_batch_state` / `state_for_copy` hooks when per-copy random seeds must differ, and test actual rendered frames rather than command strings alone. The original tool's cross-time source-frame sampling is not yet fully reproduced.
- `modes/shipinhao/mode_shipinghao_chuanshanjia_v15_worker.py`: reusable worker command builder and captured workflow.
- `test_shipinhao_0923.py`: CPU execution plus NVIDIA/AMD command assertions.
- `modes/kuaishou/mode_binfeng_caishen0923.py`: 冰峰财神主视频 + 辅助视频 adapter.
- `test_kuaishou_binfeng_0923.py`: CPU execution plus NVIDIA/AMD command assertions.

## Completion Criteria

The integration is complete only when the requested channel list is correct, CPU conversion succeeds, both supported GPU vendors render codec-correct commands, fallback remains active, output verification passes, and changed files have no diagnostics.
