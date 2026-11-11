#pragma once
#include <stddef.h>
#include <stdint.h>
/* Flash callbacks return zero on success. Erase size and offsets are 4 KiB aligned.
   A journal exclusively owns a partition of two equal, sector-aligned slots. */
typedef struct {
    void *context;
    size_t size;
    int (*read)(void *, size_t, void *, size_t);
    int (*write)(void *, size_t, const void *, size_t);
    int (*erase)(void *, size_t, size_t);
} pb_journal_t;
enum { PB_JOURNAL_OK, PB_JOURNAL_EMPTY, PB_JOURNAL_INVALID, PB_JOURNAL_IO };
int pb_journal_info(const pb_journal_t *j, size_t *length);
int pb_journal_read(const pb_journal_t *j, void *buffer, size_t capacity, size_t *length);
int pb_journal_write(const pb_journal_t *j, const void *data, size_t length);
