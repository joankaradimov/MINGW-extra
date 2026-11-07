/* A plugin host linked to libcarla_native-plugin through
   carla-native-plugin.pc, the way LMMS's Carla plugin is: a DLL
   (CARLA_TEST_HOST) that a program loads (the rest). The host has to load,
   find Carla-Rack and Carla-Patchbay, and get Carla's library, not itself,
   from carla_get_library_filename(). */
#include <stdio.h>
#include <string.h>
#include <windows.h>

#ifdef CARLA_TEST_HOST

#include "CarlaNativePlugin.h"

__declspec(dllexport) int carla_test_host(void)
{
    const char* const filename = carla_get_library_filename();
    const char* base = strrchr(filename, '\\');
    const NativePluginDescriptor* const rack = carla_get_native_rack_plugin();
    const NativePluginDescriptor* const patchbay = carla_get_native_patchbay_plugin();

    printf("%s\n", filename);
    if (base == NULL || _stricmp(base + 1, "libcarla_native-plugin.dll") != 0)
        return 1;
    if (rack == NULL || patchbay == NULL)
        return 1;
    printf("%s, %s\n", rack->name, patchbay->name);
    return 0;
}

#else

int main(int argc, char** argv)
{
    if (argc != 2)
        return 2;
    HMODULE host = LoadLibraryA(argv[1]);
    if (host == NULL) {
        printf("cannot load %s: error %lu\n", argv[1], GetLastError());
        return 1;
    }
    int (*test)(void) = (int (*)(void))(void (*)(void))GetProcAddress(host, "carla_test_host");
    if (test == NULL)
        return 1;
    return test();
}

#endif
