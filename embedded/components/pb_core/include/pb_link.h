#pragma once
#include <stdbool.h>
#include <stdint.h>

#define PB_LINK_CODE_BYTES 32
#define PB_LINK_URI_BYTES 512
#define PB_LINK_TOKEN_BYTES 65

typedef struct {
    char code[PB_LINK_CODE_BYTES];
    char uri[PB_LINK_URI_BYTES];
    char secret[PB_LINK_TOKEN_BYTES];
    unsigned expires_in, poll_interval;
} pb_link_details_t;
typedef struct {
    int status;
    unsigned retry_after;
    bool linked;
    char credential[PB_LINK_TOKEN_BYTES];
} pb_link_poll_t;
typedef enum {
    PB_LINK_WAITING,
    PB_LINK_RETRYING,
    PB_LINK_SAVING,
    PB_LINK_SAVE_FAILED,
    PB_LINK_SUCCESS,
    PB_LINK_CANCELLED,
    PB_LINK_EXPIRED,
    PB_LINK_FAILED
} pb_link_state_t;
/* Caller owns the transport, persistence and presentation. No secret is passed
   to show(). Cancellation is checked after every blocking request and before save. */
typedef struct {
    void *context;
    uint64_t (*now_ms)(void *);
    void (*wait_ms)(void *, unsigned);
    bool (*cancelled)(void *);
    int (*start)(void *, pb_link_details_t *);
    pb_link_poll_t (*poll)(void *, const char *secret);
    bool (*save)(void *, const char *credential);
    void (*show)(void *, pb_link_state_t, const char *code, const char *uri, unsigned seconds);
} pb_link_io_t;
bool pb_link_token_valid(const char *token);
bool pb_link_details_valid(const pb_link_details_t *details);
bool pb_link_uri_matches_base(const char *uri, const char *base);
pb_link_state_t pb_link_run(const pb_link_io_t *io);
