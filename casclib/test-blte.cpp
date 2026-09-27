// Decodes a two-frame BLTE file, CASC's container format, through
// CascOpenLocalFile(): a raw frame and a zlib frame, each checked against its
// MD5, under a non-ASCII file name. In a copy with one flipped byte, reading
// must stop at the damaged frame with ERROR_FILE_CORRUPT.
#include <cstdio>
#include <cstring>
#include <windows.h>
#include <CascLib.h>

static const unsigned char blte[] = {
    0x42, 0x4c, 0x54, 0x45, 0x00, 0x00, 0x00, 0x3c, 0x0f, 0x00, 0x00, 0x02,
    0x00, 0x00, 0x00, 0x26, 0x00, 0x00, 0x00, 0x25, 0x3a, 0xde, 0x88, 0x9b,
    0xcd, 0x58, 0xdc, 0x03, 0x0b, 0xe2, 0x17, 0xa7, 0xe8, 0x00, 0x05, 0x62,
    0x00, 0x00, 0x00, 0x44, 0x00, 0x00, 0x00, 0x43, 0x9b, 0x51, 0xaf, 0xaa,
    0xdb, 0xa0, 0xb5, 0xca, 0x5f, 0xc3, 0xf8, 0x83, 0xc0, 0x85, 0x80, 0xfc,
    0x4e, 0x44, 0x65, 0x63, 0x6f, 0x64, 0x65, 0x64, 0x20, 0x62, 0x79, 0x20,
    0x43, 0x61, 0x73, 0x63, 0x4c, 0x69, 0x62, 0x20, 0x66, 0x72, 0x6f, 0x6d,
    0x20, 0x61, 0x20, 0x42, 0x4c, 0x54, 0x45, 0x20, 0x66, 0x69, 0x6c, 0x65,
    0x3a, 0x20, 0x5a, 0x78, 0xda, 0xcb, 0xcf, 0x4b, 0x55, 0x28, 0x4a, 0x2c,
    0x57, 0x48, 0x2b, 0x4a, 0xcc, 0x4d, 0xd5, 0x51, 0x28, 0xc9, 0x48, 0xcd,
    0x03, 0x12, 0x99, 0xc5, 0x0a, 0x55, 0x39, 0x99, 0x49, 0x30, 0xd1, 0xd4,
    0xc4, 0xe4, 0x0c, 0x85, 0xe4, 0x8c, 0xd4, 0xe4, 0xec, 0xd4, 0x14, 0x85,
    0xc4, 0xf4, 0xc4, 0xcc, 0xbc, 0xe2, 0x12, 0x85, 0xcc, 0x92, 0x62, 0x05,
    0x5f, 0x17, 0x53, 0x3d, 0x2e, 0x00, 0x27, 0xc0, 0x17, 0x00,};

static const char expected[] =
    "Decoded by CascLib from a BLTE file: "
    "one raw frame, then this zlib frame, each checked against its MD5.\n";

static bool write_file(const wchar_t *path, const unsigned char *data, size_t size)
{
    FILE *file = _wfopen(path, L"wb");
    if (file == NULL)
        return false;
    size_t written = fwrite(data, 1, size, file);
    return fclose(file) == 0 && written == size;
}

// Reads the whole file with MD5 checks on. Returns the bytes decoded, and the
// error CascLib reported in *error.
static DWORD decode(const wchar_t *path, char *buffer, DWORD capacity, DWORD *error)
{
    HANDLE file;
    ULONGLONG size = 0;
    DWORD read = 0;

    SetLastError(ERROR_SUCCESS);
    if (!CascOpenLocalFile(path, CASC_STRICT_DATA_CHECK, &file)) {
        *error = GetCascError();
        return 0;
    }
    if (!CascGetFileSize64(file, &size) || size != sizeof(expected) - 1 ||
        !CascReadFile(file, buffer, capacity, &read))
        read = 0;
    *error = GetCascError();
    CascCloseFile(file);
    return read;
}

int main()
{
    const wchar_t *good = L"blte-ünicöde.blte";
    const wchar_t *bad = L"blte-corrupt.blte";
    unsigned char corrupt[sizeof(blte)];
    char buffer[256];
    DWORD error;

    if (!write_file(good, blte, sizeof(blte)))
        return perror("writing the BLTE file"), 1;
    DWORD read = decode(good, buffer, sizeof(buffer), &error);
    if (read != sizeof(expected) - 1 || memcmp(buffer, expected, read) != 0) {
        fprintf(stderr, "decoding failed after %lu bytes: error %lu\n",
                (unsigned long)read, (unsigned long)error);
        return 1;
    }

    memcpy(corrupt, blte, sizeof(blte));
    corrupt[sizeof(blte) - 1] ^= 0xff;
    if (!write_file(bad, corrupt, sizeof(corrupt)))
        return perror("writing the corrupted copy"), 1;
    read = decode(bad, buffer, sizeof(buffer), &error);
    if (read == sizeof(expected) - 1 || error != ERROR_FILE_CORRUPT) {
        fprintf(stderr, "the damaged frame was not refused: %lu bytes, error %lu\n",
                (unsigned long)read, (unsigned long)error);
        return 1;
    }

    puts("BLTE decoded; the damaged copy stopped at its bad frame");
    return 0;
}
