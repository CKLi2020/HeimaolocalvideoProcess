#ifndef FC_HOST_GATE_H
#define FC_HOST_GATE_H

#ifdef FC_LICENSE_GATE
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
#include <windows.h>
#include <wchar.h>

static int fc_host_gate_enabled(void) { return 1; }

static int fc_parent_directory(wchar_t *path) {
    wchar_t *sep = wcsrchr(path, L'\\');
    if (sep == NULL) { return 0; }
    if (sep > path && sep[-1] == L':') {
        sep[1] = 0;
    } else {
        *sep = 0;
    }
    return 1;
}

static HANDLE fc_open_directory(const wchar_t *path) {
    wchar_t extended[32768];
    size_t length = wcslen(path);
    if (wcsncmp(path, L"\\\\?\\", 4) == 0) {
        return CreateFileW(path, FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    }
    if (wcsncmp(path, L"\\\\", 2) == 0) {
        if (length + 7 >= 32768) { return INVALID_HANDLE_VALUE; }
        wcscpy(extended, L"\\\\?\\UNC\\");
        wcscat(extended, path + 2);
    } else {
        if (length + 5 >= 32768) { return INVALID_HANDLE_VALUE; }
        wcscpy(extended, L"\\\\?\\");
        wcscat(extended, path);
    }
    return CreateFileW(extended, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
}

static int fc_same_directory(const wchar_t *left, const wchar_t *right) {
    HANDLE a = fc_open_directory(left);
    HANDLE b = fc_open_directory(right);
    BY_HANDLE_FILE_INFORMATION ai, bi;
    int same = 0;
    if (a != INVALID_HANDLE_VALUE && b != INVALID_HANDLE_VALUE &&
            GetFileInformationByHandle(a, &ai) &&
            GetFileInformationByHandle(b, &bi)) {
        same = (ai.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
            (bi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
            ai.dwVolumeSerialNumber == bi.dwVolumeSerialNumber &&
            ai.nFileIndexHigh == bi.nFileIndexHigh &&
            ai.nFileIndexLow == bi.nFileIndexLow;
    }
    if (a != INVALID_HANDLE_VALUE) { CloseHandle(a); }
    if (b != INVALID_HANDLE_VALUE) { CloseHandle(b); }
    return same;
}

static int fc_host_ok(void) {
    wchar_t self[32768], exe[32768];
    HMODULE module = NULL;
    DWORD n;
    if (!GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCWSTR)(const void *)&fc_host_ok, &module)) {
        return 0;
    }
    n = GetModuleFileNameW(module, self, 32768);
    if (n == 0 || n >= 32768) { return 0; }
    n = GetModuleFileNameW(NULL, exe, 32768);
    if (n == 0 || n >= 32768) { return 0; }

    /* The core is in <release>\app; the launcher is in <release>.
       Nuitka may load the core through an 8.3 alias of the same directory. */
    if (!fc_parent_directory(self) || !fc_parent_directory(self) ||
            !fc_parent_directory(exe)) { return 0; }
    return fc_same_directory(self, exe);
}

static void fc_host_deny(void) {
    /* Keep rejection outside VMProtect's Python exception paths. */
    MessageBoxW(NULL,
        L"The native core host check failed (FCG1 / 0x46434731).\n"
        L"Keep the launcher and app folder in the same complete release folder.\n"
        L"If this persists, contact support with the release folder path.",
        L"Native core host check", MB_OK | MB_ICONERROR);
    ExitProcess(0x46434731u);
}
#else
static int fc_host_gate_enabled(void) { return 0; }
static int fc_host_ok(void) { return 1; }
static void fc_host_deny(void) { }
#endif

#endif
