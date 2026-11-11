#include "pb_core.h"
#include "pb_journal.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static void controls_test(void) {
    pb_controls_t c = {.menu = true};
    assert(pb_talk(&c, true) == PB_BACK);
    assert(!c.menu);
    assert(pb_talk(&c, false) == PB_NONE);
    assert(pb_talk(&c, true) == PB_RECORD_START);
    assert(pb_talk(&c, false) == PB_RECORD_END);
    c.consume_wheel = true;
    assert(pb_wheel_push(&c, true) == PB_NONE);
    assert(pb_wheel_push(&c, false) == PB_NONE);
    assert(pb_wheel_push(&c, true) == PB_MENU);
    assert(pb_wheel_push(&c, false) == PB_NONE);
    assert(pb_wheel_push(&c, true) == PB_SELECT);
    pb_button_t b = {0};
    assert(!pb_button_update(&b, true, 100));
    assert(!pb_button_update(&b, false, 105));
    assert(!pb_button_update(&b, true, 110));
    assert(!pb_button_update(&b, true, 134));
    assert(pb_button_update(&b, true, 135));
    assert(!pb_button_update(&b, true, 200));
    assert(pb_remaining_ms(100, 100) == 30000);
    assert(pb_remaining_ms(100, 15100) == 15000);
    assert(pb_remaining_ms(100, 30100) == 0);
    assert(pb_remaining_ms(100, UINT64_MAX) == 0);
}
static void text_test(void) {
    char line[96];
    const char *text = "Åäö hello\nNext";
    const char *next = pb_wrap_line(text, 3, line, sizeof(line));
    assert(!strcmp(line, "Åäö") && !strcmp(next, " hello\nNext"));
    assert(pb_text_lines("123456\nabc\n", 3) == 3);
    assert(pb_text_lines("", 21) == 0);
    assert(pb_language_valid("sv") && pb_language_valid("en-US"));
    assert(pb_language_valid("zh-Hant-TW") && pb_language_valid("es-419"));
    assert(!pb_language_valid("") && !pb_language_valid("s") && !pb_language_valid("sv-"));
    assert(!pb_language_valid("sv\ninjected") && !pb_language_valid("123") &&
           !pb_language_valid("en--US"));
}
static void audio_test(void) {
    int32_t stereo[] = {65536, INT32_MAX, 196608, INT32_MAX, -65536, INT32_MAX, -196608, INT32_MAX};
    int16_t pcm[2];
    pb_decimator_t d = {0};
    assert(pb_pcm48_to_24(&d, stereo, 1, pcm, 16) == 0);
    assert(pb_pcm48_to_24(&d, stereo + 2, 3, pcm, 16) == 2);
    assert(pcm[0] == 2 && pcm[1] == -2);
    int32_t expanded[8];
    pb_pcm24_to_48(pcm, 2, expanded, 50);
    for (int i = 0; i < 4; ++i)
        assert(expanded[i] == 65536);
    for (int i = 4; i < 8; ++i)
        assert(expanded[i] == -65536);
    int16_t extremes[] = {INT16_MIN, INT16_MAX};
    pb_pcm24_to_48(extremes, 2, expanded, 100);
    assert(expanded[0] == INT32_MIN && expanded[4] == 2147418112);
    int32_t loud[] = {INT32_MAX, 0, INT32_MAX, 0};
    d = (pb_decimator_t){0};
    assert(pb_pcm48_to_24(&d, loud, 2, pcm, 8) == 1 && pcm[0] == INT16_MAX);
    assert(PB_MAX_PCM == 1440000 && PB_PLAYBACK_BYTES == 65536);
    assert(pb_crc32(0, "123456789", 9) == 0xcbf43926);
    assert(pb_crc32(pb_crc32(0, "1234", 4), "56789", 5) == 0xcbf43926);
}
#define FLASH_BYTES (2u * 16384u)
typedef struct {
    uint8_t bytes[FLASH_BYTES];
    int fail_op, op;
    size_t partial;
} flash_t;
static int read_flash(void *ctx, size_t offset, void *data, size_t n) {
    flash_t *f = ctx;
    assert(offset + n <= FLASH_BYTES);
    memcpy(data, f->bytes + offset, n);
    return 0;
}
static int write_flash(void *ctx, size_t offset, const void *data, size_t n) {
    flash_t *f = ctx;
    assert(offset + n <= FLASH_BYTES);
    bool fail = ++f->op == f->fail_op;
    if (fail && n > f->partial)
        n = f->partial;
    const uint8_t *p = data;
    for (size_t i = 0; i < n; ++i) {
        assert((f->bytes[offset + i] & p[i]) == p[i]);
        f->bytes[offset + i] &= p[i];
    }
    return fail ? -1 : 0;
}
static int erase_flash(void *ctx, size_t offset, size_t n) {
    flash_t *f = ctx;
    assert(offset % 4096 == 0 && n % 4096 == 0 && offset + n <= FLASH_BYTES);
    bool fail = ++f->op == f->fail_op;
    if (fail && n > f->partial)
        n = f->partial;
    memset(f->bytes + offset, 255, n);
    return fail ? -1 : 0;
}
static void journal_test(void) {
    flash_t initial = {.fail_op = -1};
    memset(initial.bytes, 255, sizeof(initial.bytes));
    pb_journal_t j = {.context = &initial,
                      .size = FLASH_BYTES,
                      .read = read_flash,
                      .write = write_flash,
                      .erase = erase_flash};
    char out[9000];
    size_t n;
    assert(pb_journal_info(&j, &n) == PB_JOURNAL_EMPTY);
    assert(pb_journal_write(&j, "old", 4) == PB_JOURNAL_OK);
    assert(pb_journal_read(&j, out, sizeof(out), &n) == PB_JOURNAL_OK && !strcmp(out, "old"));
    uint8_t replacement[8500];
    memset(replacement, 0x53, sizeof(replacement));
    /* Cut power inside erase, payload write and commit-header write. After reboot,
       the reader must see a complete old record or a complete new record. */
    for (int operation = 1; operation <= 3; ++operation) {
        for (size_t partial = 0; partial <= 8500; ++partial) {
            flash_t f = initial;
            f.op = 0;
            f.fail_op = operation;
            f.partial = partial;
            j.context = &f;
            assert(pb_journal_write(&j, replacement, sizeof(replacement)) == PB_JOURNAL_IO);
            assert(pb_journal_read(&j, out, sizeof(out), &n) == PB_JOURNAL_OK);
            assert((n == 4 && !strcmp(out, "old")) ||
                   (n == sizeof(replacement) && !memcmp(out, replacement, n)));
        }
    }
    j.context = &initial;
    assert(pb_journal_write(&j, replacement, sizeof(replacement)) == PB_JOURNAL_OK);
    /* Payload corruption falls back to the previous valid committed slot. */
    initial.bytes[16384 + 4096 + 17] ^= 1;
    assert(pb_journal_read(&j, out, sizeof(out), &n) == PB_JOURNAL_OK && !strcmp(out, "old"));
    assert(pb_journal_write(&j, NULL, 0) == PB_JOURNAL_OK);
    assert(pb_journal_info(&j, &n) == PB_JOURNAL_EMPTY);
    assert(pb_journal_write(&j, replacement, FLASH_BYTES) == PB_JOURNAL_INVALID);
    /* Exercise full recording capacity against the production pending partition size. */
    assert(0x400000u / 2 - 4096 >= PB_MAX_PCM + 256u * 1024u + 4);
}
int main(void) {
    controls_test();
    audio_test();
    text_test();
    journal_test();
    puts("PocketBrain core and power-loss tests passed");
}
