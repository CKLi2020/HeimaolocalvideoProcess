import ctypes
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native host gate")


@pytest.fixture(scope="module")
def native_tools(tmp_path_factory):
    gcc = shutil.which("gcc") or r"C:\MinGW\bin\gcc.exe"
    if not Path(gcc).is_file():
        pytest.skip("MinGW GCC is required for native host gate tests")
    build = tmp_path_factory.mktemp("host_gate_build")
    dll_source = build / "probe.c"
    dll_source.write_text(
        '#define FC_LICENSE_GATE\n#include "host_gate.h"\n'
        '__declspec(dllexport) int host_status(void) { return fc_host_ok(); }\n'
        '__declspec(dllexport) int legacy_status(void) {\n'
        ' wchar_t a[32768], b[32768], *p; HMODULE m=NULL;\n'
        ' if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |\n'
        ' GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,\n'
        ' (LPCWSTR)(const void *)&legacy_status, &m)) return -1;\n'
        ' if(!GetModuleFileNameW(m,a,32768) || !GetModuleFileNameW(NULL,b,32768)) return -1;\n'
        " p=wcsrchr(a,92); if(!p)return -1; *p=0;\n"
        " p=wcsrchr(a,92); if(!p)return -1; *p=0;\n"
        " p=wcsrchr(b,92); if(!p)return -1; *p=0;\n"
        ' return _wcsicmp(a,b)==0;\n}\n'
        r'''
__declspec(dllexport) int root_paths(void) {
    wchar_t ordinary[] = L"C:\\launcher.exe";
    wchar_t extended[] = L"\\\\?\\C:\\launcher.exe";
    wchar_t core[] = L"C:\\app\\probe.dll";
    return fc_parent_directory(ordinary) &&
        wcscmp(ordinary, L"C:\\") == 0 &&
        fc_parent_directory(extended) &&
        wcscmp(extended, L"\\\\?\\C:\\") == 0 &&
        fc_parent_directory(core) && fc_parent_directory(core) &&
        wcscmp(core, L"C:\\") == 0;
}
''',
        encoding="ascii",
    )
    exe_source = build / "launcher.c"
    exe_source.write_text(
        '#include <windows.h>\n#include <shellapi.h>\n#include <stdio.h>\n'
        'int main(void) {\n'
        ' int n; wchar_t **args=CommandLineToArgvW(GetCommandLineW(),&n);\n'
        ' HMODULE m; int (*check)(void), (*legacy)(void);\n'
        ' if(!args || (n!=2 && n!=3)) return 2;\n'
        ' m=LoadLibraryW(args[1]); LocalFree(args); if(!m) return 3;\n'
        ' if(n==3) {\n'
        ' check=(int (*)(void))GetProcAddress(m,"root_paths"); if(!check)return 4;\n'
        ' printf("%d\\n",check()); FreeLibrary(m); return 0;\n}\n'
        ' check=(int (*)(void))GetProcAddress(m,"host_status");\n'
        ' legacy=(int (*)(void))GetProcAddress(m,"legacy_status");\n'
        ' if(!check || !legacy) return 4;\n'
        ' printf("%d %d\\n", check(), legacy()); FreeLibrary(m); return 0;\n}\n',
        encoding="ascii",
    )
    dll = build / "probe.dll"
    exe = build / "launcher.exe"
    for command in (
        [gcc, "-shared", "-Wall", "-Werror", "-Wno-unused-function",
         "-I", str(ROOT / "native_src"), str(dll_source), "-o", str(dll), "-luser32"],
        [gcc, "-Wall", "-Werror", str(exe_source), "-o", str(exe), "-lshell32"],
    ):
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    return exe, dll


def make_release(tmp_path, native_tools):
    exe, dll = native_tools
    release = tmp_path / "星火漫剧 测试目录"
    (release / "app").mkdir(parents=True)
    return (
        Path(shutil.copy2(exe, release / "launcher.exe")),
        Path(shutil.copy2(dll, release / "app" / "probe.dll")),
    )


def run_probe(exe, dll):
    result = subprocess.run([str(exe), str(dll)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, (result.returncode, result.stderr)
    return tuple(int(value) for value in result.stdout.split())


def test_same_unicode_directory_allowed(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    assert run_probe(exe, dll) == (1, 1)


def test_drive_roots_are_preserved(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    result = subprocess.run(
        [str(exe), str(dll), "--root-paths"], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_short_core_path_matches_long_launcher_path(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    short_path = ctypes.windll.kernel32.GetShortPathNameW
    short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    short_path.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = short_path(str(dll), buffer, len(buffer))
    assert 0 < length < len(buffer), ctypes.get_last_error()
    alias = Path(buffer.value)
    if str(alias.parent.parent).casefold() == str(exe.parent).casefold():
        pytest.skip("8.3 aliases are disabled on the test volume")
    assert run_probe(exe, alias) == (1, 0)


def test_core_in_another_release_is_denied(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    other = tmp_path / "another_release" / "app"
    other.mkdir(parents=True)
    foreign = Path(shutil.copy2(dll, other / "probe.dll"))
    assert run_probe(exe, foreign) == (0, 0)


def test_extended_length_path_is_allowed(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    assert run_probe(exe, "\\\\?\\" + str(dll))[0] == 1


def test_directory_junction_is_allowed(tmp_path, native_tools):
    exe, dll = make_release(tmp_path, native_tools)
    alias = tmp_path / "release_alias"
    subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(alias), str(exe.parent)],
        check=True, capture_output=True,
    )
    try:
        assert run_probe(exe, alias / "app" / dll.name) == (1, 0)
    finally:
        os.rmdir(alias)
