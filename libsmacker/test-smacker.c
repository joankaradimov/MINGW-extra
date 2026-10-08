/* Decode every frame of an .smk and write it as raw RGB24, so the result can
 * be compared byte for byte with another decoder's output. */
#include <stdio.h>
#include <smacker.h>

int main(int argc, char **argv)
{
    unsigned long frame, frames, w, h, i;
    unsigned char y_scale;
    double usf;
    FILE *out;
    smk s;

    if (argc != 3) {
        fprintf(stderr, "usage: test-smacker IN.smk OUT.rgb\n");
        return 2;
    }
    s = smk_open_file(argv[1], SMK_MODE_DISK);
    if (!s) {
        fprintf(stderr, "FAIL: cannot open %s\n", argv[1]);
        return 1;
    }
    smk_info_all(s, &frame, &frames, &usf);
    smk_info_video(s, &w, &h, &y_scale);
    printf("%lux%lu, %lu frames, %.0f us/frame, y_scale %u\n", w, h, frames, usf, y_scale);

    out = fopen(argv[2], "wb");
    if (!out)
        return 1;
    smk_enable_video(s, 1);
    smk_first(s);
    for (frame = 0; frame < frames; frame++) {
        const unsigned char *pal = smk_get_palette(s);
        const unsigned char *pix = smk_get_video(s);
        if (!pal || !pix) {
            fprintf(stderr, "FAIL: frame %lu has no video\n", frame);
            return 1;
        }
        for (i = 0; i < w * h; i++)
            fwrite(&pal[pix[i] * 3], 1, 3, out);
        if (frame + 1 < frames && smk_next(s) < 0) {
            fprintf(stderr, "FAIL: smk_next at frame %lu\n", frame);
            return 1;
        }
    }
    fclose(out);
    smk_close(s);
    return 0;
}
