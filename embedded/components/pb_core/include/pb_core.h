#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define PB_RATE 24000u
#define PB_RECORD_SECONDS 30u
#define PB_MAX_SAMPLES (PB_RATE * PB_RECORD_SECONDS)
#define PB_MAX_PCM (PB_MAX_SAMPLES * sizeof(int16_t))
#define PB_MIN_SAMPLES (PB_RATE / 10u)
#define PB_PLAYBACK_BYTES (64u * 1024u)
/* Debounce and navigation are independent of RTOS scheduling and transport. */
typedef struct {
    bool raw, stable;
    uint64_t changed;
} pb_button_t;
bool pb_button_update(pb_button_t *b, bool down, uint64_t now_ms);
typedef struct {
    bool menu, consume_talk, consume_wheel;
    int selection;
} pb_controls_t;
typedef enum { PB_NONE, PB_RECORD_START, PB_RECORD_END, PB_BACK, PB_SELECT, PB_MENU } pb_action_t;
pb_action_t pb_talk(pb_controls_t *c, bool down);
pb_action_t pb_wheel_push(pb_controls_t *c, bool down);
unsigned pb_remaining_ms(uint64_t started_ms, uint64_t now_ms);
/* Two-tap decimator: persistent state permits arbitrary chunk boundaries. */
typedef struct {
    int32_t first;
    bool have_first;
} pb_decimator_t;
size_t pb_pcm48_to_24(pb_decimator_t *d, const int32_t *stereo, size_t frames, int16_t *mono,
                      unsigned shift);
void pb_pcm24_to_48(const int16_t *mono, size_t samples, int32_t *stereo, unsigned volume);
uint32_t pb_crc32(uint32_t crc, const void *data, size_t len);
/* Text layout shared by display and navigation; offsets never split UTF-8. */
const char *pb_wrap_line(const char *text, unsigned columns, char *out, size_t capacity);
size_t pb_text_lines(const char *text, unsigned columns);
bool pb_language_valid(const char *tag);
