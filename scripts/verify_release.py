"""Post-SProtect / post-finalize end-to-end check of a release directory.

Run this after SProtect has produced the packed launcher and after
``finalize_sprotect_release.ps1`` has swapped it in. It answers one question
without launching the GUI: **is this release directory still intact?**

It repeats, from outside, the three checks the shipped product performs or
depends on:

1. the manifest signature, product id and per-file hashes -- exactly what
   ``core/release_integrity.verify_release_manifest`` does at startup, so a
   release that passes here will not fail the app's own gate;
2. ``app/_flowcut_core.pyd`` still exports every name in
   ``engine/native_core.py::_REQUIRED`` (SProtect and VMProtect both rewrite
   binaries, so a damaged core is a real failure mode);
3. ``app/_random_frame_swap_core.pyd`` still exports what the 爆闪 channel
   imports from it.

It then adds one release-hygiene check the product itself cannot make: that no
plaintext copy of a channel algorithm is sitting in the directory. That covers
the Python twins of the protected cores and the feimao/tingxue recipe, which
lives in ``modes/douyin/feimao_recipe.py`` and must never reappear as the
``filter_complex.txt`` / ``feimao_ffargs.json`` data files.

Importing a protected core does not require a license -- the gate runs inside
each exported function, not at module load -- so this check needs no
``license.key``. Calling one of those functions does, and the native smoke test
in ``build_native.ps1`` is where that gets exercised.

Usage:

    python scripts\\verify_release.py --release-root "dist-protected\\黑猫@视频软件_V1.0.0"
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import sys
from pathlib import Path

# Plaintext copies of channel algorithms that must never appear in a release:
# the Python twins of the two protected cores, and the feimao/tingxue recipe
# data files (now compiled in as modes/douyin/feimao_recipe.py). Mirrors
# build_release_manifest.py::FORBIDDEN, which blocks them before signing.
PLAINTEXT_ALGORITHMS = (
    "modes/shipinhao/heimao_luoyue_core.py",
    "modes/shipinhao/__pycache__/heimao_luoyue_core.cpython-*.pyc",
    "modes/douyin/filter_complex.txt",
    "modes/douyin/feimao_ffargs.json",
)


def load_extension(path: Path, module_name: str):
    """Import a .pyd by path, with the DLL search path it needs to resolve."""
    directory = str(path.parent)
    parent = str(path.parent.parent)
    # On Windows an extension module needs python39.dll (and the gcc runtime)
    # to resolve before it can load.
    for candidate in (os.path.dirname(os.path.abspath(sys.executable)), directory, parent):
        try:
            os.add_dll_directory(candidate)
        except (AttributeError, OSError):
            pass
    os.environ["PATH"] = os.pathsep.join([directory, parent, os.environ.get("PATH", "")])
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None:
        raise RuntimeError(f"not a loadable extension module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def required_from_native_core(repo_root: Path, const_name: str) -> list[str]:
    """Read a required-export tuple out of engine/native_core.py without importing it."""
    path = repo_root / "engine" / "native_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == const_name for t in node.targets):
            return [element.value for element in node.value.elts]
    raise RuntimeError(f"could not read {const_name} from {path}")


def check_exports(path: Path, module_name: str, required: tuple[str, ...], label: str) -> list[str]:
    if not path.is_file():
        return [f"{label} 缺失：{path}"]
    try:
        module = load_extension(path, module_name)
    except Exception as exc:
        return [f"{label} 无法加载（加壳可能破坏了它）：{exc}"]
    have = {name for name in dir(module) if not name.startswith("_")}
    missing = sorted(set(required) - have)
    if missing:
        return [f"{label} 缺少导出：{', '.join(missing)}"]
    print(f"  ok  {label}：{len(required)} 个导出齐全")
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    root = Path(args.release_root).resolve()
    if not root.is_dir():
        raise SystemExit(f"发布目录不存在：{root}")

    problems: list[str] = []

    print(f"自检发布目录：{root}")

    # 1. Exactly what the app checks before its window appears.
    sys.path.insert(0, str(repo_root))
    try:
        from core.release_integrity import verify_release_manifest

        verify_release_manifest.cache_clear()
        manifest = verify_release_manifest(root, required=True)
    except Exception as exc:
        problems.append(f"清单校验失败：{exc}")
        manifest = {}
    else:
        print(f"  ok  清单签名与逐文件哈希：{len(manifest.get('files', []))} 个文件")
        if not any(f["path"].lower().endswith(".exe") and "/" not in f["path"] for f in manifest.get("files", [])):
            problems.append("清单里没有启动器 EXE，加壳后的启动器没被签进去")

    # 2/3. Both protected cores must still be loadable with their full export set.
    app = root / "app"
    problems += check_exports(
        app / "_flowcut_core.pyd", "_flowcut_core",
        tuple(required_from_native_core(repo_root, "_REQUIRED")),
        "app/_flowcut_core.pyd",
    )
    problems += check_exports(
        app / "_random_frame_swap_core.pyd", "_random_frame_swap_core",
        tuple(required_from_native_core(repo_root, "RANDOM_SWAP_REQUIRED")),
        "app/_random_frame_swap_core.pyd",
    )

    # 4. No plaintext copy of a channel algorithm may be in the release.
    leaked: list[Path] = []
    for pattern in PLAINTEXT_ALGORITHMS:
        leaked.extend(sorted(root.glob(pattern)))
    if leaked:
        for path in leaked:
            problems.append(f"发布物里有明文通道算法：{path.relative_to(root)}")
    else:
        print("  ok  没有明文通道算法")

    print()
    if problems:
        for item in problems:
            print(f"失败：{item}")
        print(f"\n发布自检未通过（{len(problems)} 项）")
        return 1
    print("发布自检通过：签名清单有效、两个受保护核心可加载、无明文泄漏")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
