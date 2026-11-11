#include "pb_core.h"
#include <limits.h>
bool pb_button_update(pb_button_t *b, bool down, uint64_t now) {
    if (down != b->raw) {
        b->raw = down;
        b->changed = now;
    }
    if (down != b->stable && now - b->changed >= 25) {
        b->stable = down;
        return true;
    }
    return false;
}
pb_action_t pb_talk(pb_controls_t *c, bool down) {
    if (down && c->menu) {
        c->menu = false;
        c->consume_talk = true;
        return PB_BACK;
    }
    if (c->consume_talk) {
        if (!down)
            c->consume_talk = false;
        return PB_NONE;
    }
    return down ? PB_RECORD_START : PB_RECORD_END;
}
pb_action_t pb_wheel_push(pb_controls_t *c, bool down) {
    if (c->consume_wheel) {
        if (!down)
            c->consume_wheel = false;
        return PB_NONE;
    }
    if (!down)
        return PB_NONE;
    if (c->menu)
        return PB_SELECT;
    c->menu = true;
    c->selection = 0;
    return PB_MENU;
}
unsigned pb_remaining_ms(uint64_t start, uint64_t now) {
    uint64_t elapsed = now >= start ? now - start : 0;
    return elapsed >= PB_RECORD_SECONDS * 1000u ? 0 : PB_RECORD_SECONDS * 1000u - (unsigned)elapsed;
}
size_t pb_pcm48_to_24(pb_decimator_t *d, const int32_t *in, size_t frames, int16_t *out,
                      unsigned shift) {
    size_t n = 0;
    for (size_t i = 0; i < frames; ++i) {
        int32_t sample = in[i * 2] >> shift;
        if (!d->have_first) {
            d->first = sample;
            d->have_first = true;
            continue;
        }
        int64_t average = ((int64_t)d->first + sample) / 2;
        if (average > INT16_MAX)
            average = INT16_MAX;
        if (average < INT16_MIN)
            average = INT16_MIN;
        out[n++] = (int16_t)average;
        d->have_first = false;
    }
    return n;
}
void pb_pcm24_to_48(const int16_t *in, size_t n, int32_t *out, unsigned volume) {
    if (volume > 100)
        volume = 100;
    for (size_t i = 0; i < n; ++i) {
        int32_t v = (int32_t)((int64_t)in[i] * 65536 * volume / 100);
        for (unsigned j = 0; j < 4; ++j)
            out[i * 4 + j] = v;
    }
}
uint32_t pb_crc32(uint32_t crc, const void *data, size_t n) {
    const uint8_t *p = data;
    crc = ~crc;
    while (n--) {
        crc ^= *p++;
        for (unsigned i = 0; i < 8; ++i)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
const char *pb_wrap_line(const char *p, unsigned width, char *out, size_t cap) {
    size_t n = 0;
    unsigned columns = 0;
    while (*p && *p != '\n' && columns < width) {
        unsigned char c = (unsigned char)*p;
        unsigned count = c < 128 ? 1 : c < 224 ? 2 : c < 240 ? 3 : 4;
        if (count >= cap - n)
            break;
        for (unsigned i = 0; i < count && *p; ++i)
            out[n++] = *p++;
        ++columns;
    }
    if (*p == '\n')
        ++p;
    if (cap)
        out[n] = 0;
    return p;
}
size_t pb_text_lines(const char *text, unsigned columns) {
    size_t lines = 0;
    char chunk[128];
    if (!columns)
        return 0;
    while (*text) {
        const char *next = pb_wrap_line(text, columns, chunk, sizeof(chunk));
        if (next == text)
            break;
        text = next;
        ++lines;
    }
    return lines;
}
bool pb_language_valid(const char *p) {
    if (!p || !*p)
        return false;
    unsigned length = 0, segment = 0, parts = 0;
    for (; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (++length > 63)
            return false;
        if (c == '-') {
            if (segment < (parts ? 1u : 2u) || segment > 8)
                return false;
            ++parts;
            segment = 0;
            continue;
        }
        bool letter = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
        if (!letter && !(parts && c >= '0' && c <= '9'))
            return false;
        if (++segment > 8)
            return false;
    }
    return segment >= (parts ? 1u : 2u) && segment <= 8;
}
