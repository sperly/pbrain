#include "pb_journal.h"
#include "pb_core.h"
#define MAGIC 0x50424a31u
#define SECTOR 4096u
typedef struct {
    uint32_t magic, sequence, size, crc, header_crc;
} header_t;
_Static_assert(sizeof(header_t) == 20, "journal disk layout");
static uint32_t header_crc(header_t h) {
    h.header_crc = 0;
    return pb_crc32(0, &h, sizeof(h));
}
static int valid(const pb_journal_t *j) {
    return j && j->read && j->write && j->erase && j->size >= SECTOR * 4 &&
           j->size % (SECTOR * 2) == 0;
}
static int read_header(const pb_journal_t *j, size_t offset, header_t *h) {
    if (j->read(j->context, offset, h, sizeof(*h)) || h->magic != MAGIC ||
        h->size > j->size / 2 - SECTOR || h->header_crc != header_crc(*h))
        return 0;
    uint8_t chunk[1024];
    uint32_t crc = 0;
    for (size_t i = 0; i < h->size; i += sizeof(chunk)) {
        size_t n = h->size - i;
        if (n > sizeof(chunk))
            n = sizeof(chunk);
        if (j->read(j->context, offset + SECTOR + i, chunk, n))
            return 0;
        crc = pb_crc32(crc, chunk, n);
    }
    return crc == h->crc;
}
static int latest(const pb_journal_t *j, header_t h[2]) {
    int a = read_header(j, 0, &h[0]), b = read_header(j, j->size / 2, &h[1]);
    if (!a && !b)
        return -1;
    if (!a)
        return 1;
    if (!b)
        return 0;
    return (int32_t)(h[1].sequence - h[0].sequence) > 0 ? 1 : 0;
}
int pb_journal_info(const pb_journal_t *j, size_t *length) {
    if (!valid(j) || !length)
        return PB_JOURNAL_INVALID;
    header_t h[2];
    int slot = latest(j, h);
    *length = slot < 0 ? 0 : h[slot].size;
    return slot < 0 || !*length ? PB_JOURNAL_EMPTY : PB_JOURNAL_OK;
}
int pb_journal_read(const pb_journal_t *j, void *buffer, size_t capacity, size_t *length) {
    if (!valid(j) || !length)
        return PB_JOURNAL_INVALID;
    header_t h[2];
    int slot = latest(j, h);
    *length = slot < 0 ? 0 : h[slot].size;
    if (slot < 0 || !*length)
        return PB_JOURNAL_EMPTY;
    if (!buffer || capacity < *length)
        return PB_JOURNAL_INVALID;
    return j->read(j->context, (size_t)slot * (j->size / 2) + SECTOR, buffer, *length)
               ? PB_JOURNAL_IO
               : PB_JOURNAL_OK;
}
int pb_journal_write(const pb_journal_t *j, const void *data, size_t length) {
    if (!valid(j) || length > UINT32_MAX || length > j->size / 2 - SECTOR || (length && !data))
        return PB_JOURNAL_INVALID;
    header_t old[2];
    int slot = latest(j, old);
    size_t offset = (slot == 0 ? 1 : 0) * (j->size / 2);
    header_t h = {.magic = MAGIC,
                  .sequence = slot < 0 ? 1 : old[slot].sequence + 1,
                  .size = (uint32_t)length,
                  .crc = pb_crc32(0, data, length)};
    h.header_crc = header_crc(h);
    size_t erase = SECTOR + ((length + SECTOR - 1) / SECTOR) * SECTOR;
    if (j->erase(j->context, offset, erase))
        return PB_JOURNAL_IO;
    if (length && j->write(j->context, offset + SECTOR, data, length))
        return PB_JOURNAL_IO;
    /* The previous committed slot remains readable until the new header lands. */
    return j->write(j->context, offset, &h, sizeof(h)) ? PB_JOURNAL_IO : PB_JOURNAL_OK;
}
