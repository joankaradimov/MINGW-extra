// Creates an MPQ archive under a non-ASCII name, stores one file with zlib and
// one with bzip2, signs the archive with the weak signature and reopens it.
// The signature must verify, its RSA part must not be all zero (StormLib
// accepts an all-zero weak signature as a blanked one), and both files must
// read back intact.
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <windows.h>
#include <StormLib.h>

static const char payload[] =
    "Stored in a signed MPQ archive, then read back and compared.\n";
static const DWORD payload_size = sizeof(payload) - 1;

static bool add(HANDLE mpq, const char *name, DWORD compression)
{
    HANDLE file;
    return SFileCreateFile(mpq, name, 0, payload_size, 0, MPQ_FILE_COMPRESS, &file) &&
           SFileWriteFile(file, payload, payload_size, compression) &&
           SFileFinishFile(file);
}

static bool read_back(HANDLE mpq, const char *name, void *buffer, DWORD size)
{
    HANDLE file;
    DWORD read = 0;
    if (!SFileOpenFileEx(mpq, name, SFILE_OPEN_FROM_MPQ, &file))
        return false;
    bool ok = SFileReadFile(file, buffer, size, &read, NULL) && read == size;
    SFileCloseFile(file);
    return ok;
}

int main()
{
    const wchar_t *path = L"signed-ärchive.mpq";
    char buffer[sizeof(payload)];
    unsigned char signature[72];
    HANDLE mpq;

    DeleteFileW(path);
    if (!SFileCreateArchive(path, MPQ_CREATE_ARCHIVE_V1 | MPQ_CREATE_LISTFILE |
                                  MPQ_CREATE_SIGNATURE, 16, &mpq))
        return fprintf(stderr, "creating the archive: error %lu\n", GetLastError()), 1;
    if (!add(mpq, "zlib.txt", MPQ_COMPRESSION_ZLIB) ||
        !add(mpq, "bzip2.txt", MPQ_COMPRESSION_BZIP2))
        return fprintf(stderr, "adding files: error %lu\n", GetLastError()), 1;
    if (!SFileSignArchive(mpq, SIGNATURE_TYPE_WEAK))
        return fprintf(stderr, "signing: error %lu\n", GetLastError()), 1;
    SFileCloseArchive(mpq);

    if (!SFileOpenArchive(path, 0, STREAM_FLAG_READ_ONLY, &mpq))
        return fprintf(stderr, "reopening: error %lu\n", GetLastError()), 1;

    DWORD verdict = SFileVerifyArchive(mpq);
    if (verdict != ERROR_WEAK_SIGNATURE_OK)
        return fprintf(stderr, "SFileVerifyArchive returned %lu\n", verdict), 1;

    if (!read_back(mpq, "(signature)", signature, sizeof(signature)))
        return fputs("the (signature) file is missing or short\n", stderr), 1;
    bool blank = true;
    for (size_t i = 8; i < sizeof(signature); i++)
        blank = blank && signature[i] == 0;
    if (blank)
        return fputs("the weak signature is all zero\n", stderr), 1;

    for (const char *name : {"zlib.txt", "bzip2.txt"}) {
        if (!read_back(mpq, name, buffer, payload_size) ||
            memcmp(buffer, payload, payload_size) != 0)
            return fprintf(stderr, "%s did not read back intact\n", name), 1;
    }

    SFileCloseArchive(mpq);
    puts("signed archive verified; zlib and bzip2 files read back intact");
    return 0;
}
