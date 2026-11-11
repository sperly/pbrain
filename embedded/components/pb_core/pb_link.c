#include "pb_link.h"
#include <string.h>

bool pb_link_token_valid(const char *token) {
    return token && strlen(token) == 64 && strspn(token, "0123456789abcdefABCDEF") == 64;
}
bool pb_link_details_valid(const pb_link_details_t *d) {
    if (!d || !memchr(d->code, 0, sizeof(d->code)) || !memchr(d->uri, 0, sizeof(d->uri)) ||
        !memchr(d->secret, 0, sizeof(d->secret)))
        return false;
    if (!pb_link_token_valid(d->secret) || d->expires_in == 0 || d->expires_in > 900 ||
        d->poll_interval == 0 || d->poll_interval > 900)
        return false;
    /* Match the backend's human-readable code and reject display control bytes. */
    if (strlen(d->code) != 9 || d->code[4] != '-')
        return false;
    for (unsigned i = 0; i < 9; ++i)
        if (i != 4 && !strchr("23456789ABCDEFGHJKLMNPQRSTUVWXYZ", d->code[i]))
            return false;
    if (strncmp(d->uri, "https://", 8) || !d->uri[8])
        return false;
    for (const unsigned char *p = (const unsigned char *)d->uri; *p; ++p)
        if (*p <= 32 || *p == 127)
            return false;
    return true;
}
bool pb_link_uri_matches_base(const char *uri, const char *base) {
    if (!uri || !base || strncmp(base, "https://", 8) || !base[8])
        return false;
    size_t length = strlen(base);
    while (length > 8 && base[length - 1] == '/')
        --length;
    return !strncmp(uri, base, length) && uri[length] == '/';
}
static unsigned seconds_left(uint64_t now, uint64_t until) {
    return now >= until ? 0 : (unsigned)((until - now + 999) / 1000);
}
pb_link_state_t pb_link_run(const pb_link_io_t *io) {
    pb_link_details_t d = {0};
    pb_link_state_t state = PB_LINK_FAILED;
    if (io->cancelled(io->context)) {
        state = PB_LINK_CANCELLED;
        goto finish;
    }
    uint64_t started = io->now_ms(io->context);
    int status = io->start(io->context, &d);
    if (io->cancelled(io->context)) {
        state = PB_LINK_CANCELLED;
        goto finish;
    }
    if (status != 201 || !pb_link_details_valid(&d))
        goto finish;
    /* Count conservatively from before the request, including network latency. */
    uint64_t until = started + (uint64_t)d.expires_in * 1000;
    unsigned interval = d.poll_interval < 5 ? 5 : d.poll_interval;
    uint64_t next = io->now_ms(io->context) + (uint64_t)interval * 1000;
    unsigned shown = 0, backoff = interval;
    char credential[PB_LINK_TOKEN_BYTES] = {0};
    state = PB_LINK_WAITING;
    while (true) {
        if (io->cancelled(io->context)) {
            state = PB_LINK_CANCELLED;
            break;
        }
        uint64_t now = io->now_ms(io->context);
        if (now >= until) {
            state = PB_LINK_EXPIRED;
            break;
        }
        unsigned remaining = seconds_left(now, until);
        if (remaining != shown) {
            io->show(io->context, state, d.code, d.uri, remaining);
            shown = remaining;
        }
        if (now < next) {
            io->wait_ms(io->context, 100);
            continue;
        }
        if (*credential) {
            state = PB_LINK_SAVING;
            io->show(io->context, state, d.code, d.uri, remaining);
            if (io->cancelled(io->context)) {
                state = PB_LINK_CANCELLED;
                break;
            }
            if (io->save(io->context, credential)) {
                state = PB_LINK_SUCCESS;
                break;
            }
            state = PB_LINK_SAVE_FAILED;
            shown = 0;
            next = io->now_ms(io->context) + 1000;
            continue;
        }
        pb_link_poll_t reply = io->poll(io->context, d.secret);
        if (io->cancelled(io->context)) {
            state = PB_LINK_CANCELLED;
            break;
        }
        if (io->now_ms(io->context) >= until) {
            state = PB_LINK_EXPIRED;
            break;
        }
        if (reply.status == 200 && reply.linked) {
            if (!memchr(reply.credential, 0, sizeof(reply.credential)) ||
                !pb_link_token_valid(reply.credential)) {
                state = PB_LINK_FAILED;
                break;
            }
            memcpy(credential, reply.credential, sizeof(credential));
            next = io->now_ms(io->context);
            continue;
        }
        if (reply.status == 202) {
            state = PB_LINK_WAITING;
            backoff = interval;
        } else if (reply.status == 404) {
            state = PB_LINK_EXPIRED;
            break;
        } else if (reply.status == 0 || reply.status == 408 || reply.status == 429 ||
                   reply.status >= 500) {
            state = PB_LINK_RETRYING;
            if (backoff < 60)
                backoff = backoff > 30 ? 60 : backoff * 2;
            if (backoff < interval)
                backoff = interval;
        } else {
            state = PB_LINK_FAILED;
            break;
        }
        unsigned delay = state == PB_LINK_WAITING ? interval : backoff;
        if (reply.retry_after > delay)
            delay = reply.retry_after;
        next = io->now_ms(io->context) + (uint64_t)delay * 1000;
        shown = 0;
    }
finish:
    io->show(io->context, state, d.code, d.uri, 0);
    return state;
}
