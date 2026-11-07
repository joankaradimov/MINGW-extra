/*
 * Stand-in for the frozen UI executables of Carla's Windows releases.
 *
 * Carla starts the UIs of its internal plugins, and of Carla itself as a
 * plugin, as <resources>/<name>.exe. Here those UIs are the Python scripts
 * <resources>/<name>, so this program, installed as <name>.exe, runs
 * pythonw.exe on the script beside it with the same arguments. The arguments
 * name the pipes the UI talks over. A job object ends the UI together with
 * this process when Carla closes or kills it.
 *
 * The prefix is three levels up: <prefix>/share/carla/resources/<name>.exe.
 */

#include <windows.h>
#include <wchar.h>

static wchar_t *skip_argv0(wchar_t *cmd)
{
    if (*cmd == L'"') {
        for (++cmd; *cmd != L'\0' && *cmd != L'"'; ++cmd)
            ;
        if (*cmd == L'"')
            ++cmd;
    } else {
        while (*cmd != L'\0' && *cmd != L' ' && *cmd != L'\t')
            ++cmd;
    }
    while (*cmd == L' ' || *cmd == L'\t')
        ++cmd;
    return cmd;
}

int wmain(void)
{
    wchar_t self[MAX_PATH], script[MAX_PATH], python[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, self, MAX_PATH);
    if (len == 0 || len >= MAX_PATH)
        return 1;

    /* <dir>\<name>.exe -> <dir>\<name> */
    wcscpy(script, self);
    wchar_t *dot = wcsrchr(script, L'.');
    if (dot == NULL || _wcsicmp(dot, L".exe") != 0)
        return 1;
    *dot = L'\0';

    /* <prefix>\share\carla\resources\<name>.exe -> <prefix>\bin\pythonw.exe */
    wcscpy(python, self);
    for (int i = 0; i < 4; ++i) {
        wchar_t *sep = wcsrchr(python, L'\\');
        if (sep == NULL)
            return 1;
        *sep = L'\0';
    }
    if (wcslen(python) + wcslen(L"\\bin\\pythonw.exe") >= MAX_PATH)
        return 1;
    wcscat(python, L"\\bin\\pythonw.exe");

    const wchar_t *args = skip_argv0(GetCommandLineW());
    size_t size = wcslen(python) + wcslen(script) + wcslen(args) + 8;
    wchar_t *cmd = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    if (cmd == NULL)
        return 1;
    swprintf(cmd, size, L"\"%ls\" \"%ls\" %ls", python, script, args);

    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job != NULL) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info;
        ZeroMemory(&info, sizeof(info));
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info, sizeof(info));
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    if (!CreateProcessW(python, cmd, NULL, NULL, TRUE,
                        CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT,
                        NULL, NULL, &si, &pi))
        return 1;
    if (job != NULL)
        AssignProcessToJobObject(job, pi.hProcess);
    ResumeThread(pi.hThread);
    CloseHandle(pi.hThread);

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
