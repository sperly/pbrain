#include "pb_link.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint64_t now, cancel_at;
    unsigned starts, polls, saves, failures;
    unsigned start_delay, poll_delay, lifetime, interval;
    uint64_t polled_at[16];
    pb_link_poll_t responses[16];
    unsigned response_count;
    int start_status;
    bool cancelled, malformed;
    pb_link_state_t shown;
} fake_t;
static const char token[] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static uint64_t now(void *ctx) {
    return ((fake_t *)ctx)->now;
}
static void wait(void *ctx, unsigned ms) {
    ((fake_t *)ctx)->now += ms;
}
static bool cancelled(void *ctx) {
    fake_t *f = ctx;
    return f->cancelled || (f->cancel_at && f->now >= f->cancel_at);
}
static int start(void *ctx, pb_link_details_t *d) {
    fake_t *f = ctx;
    ++f->starts;
    f->now += f->start_delay;
    strcpy(d->code, "ABCD-2345");
    strcpy(d->uri, "https://peabrain.se/index.php#devices");
    strcpy(d->secret, f->malformed ? "bad" : token);
    d->expires_in = f->lifetime;
    d->poll_interval = f->interval;
    return f->start_status;
}
static pb_link_poll_t poll(void *ctx, const char *secret) {
    fake_t *f = ctx;
    assert(!strcmp(secret, token));
    assert(f->polls < 16);
    f->polled_at[f->polls] = f->now;
    pb_link_poll_t r =
        f->polls < f->response_count ? f->responses[f->polls] : (pb_link_poll_t){.status = 202};
    ++f->polls;
    f->now += f->poll_delay;
    return r;
}
static bool save(void *ctx, const char *credential) {
    fake_t *f = ctx;
    assert(!cancelled(ctx));
    assert(!strcmp(credential, token));
    return ++f->saves > f->failures;
}
static void show(void *ctx, pb_link_state_t state, const char *code, const char *uri,
                 unsigned seconds) {
    fake_t *f = ctx;
    f->shown = state;
    if (seconds) {
        assert(!strcmp(code, "ABCD-2345"));
        assert(!strcmp(uri, "https://peabrain.se/index.php#devices"));
    }
}
static pb_link_state_t run(fake_t *f) {
    pb_link_io_t io = {.context = f,
                       .now_ms = now,
                       .wait_ms = wait,
                       .cancelled = cancelled,
                       .start = start,
                       .poll = poll,
                       .save = save,
                       .show = show};
    return pb_link_run(&io);
}
static fake_t setup(void) {
    return (fake_t){.start_status = 201, .lifetime = 300, .interval = 5};
}
static pb_link_poll_t linked(void) {
    pb_link_poll_t r = {.status = 200, .linked = true};
    strcpy(r.credential, token);
    return r;
}
int main(void) {
    fake_t f = setup();
    f.responses[0] = (pb_link_poll_t){.status = 202};
    f.responses[1] = linked();
    f.response_count = 2;
    assert(run(&f) == PB_LINK_SUCCESS && f.saves == 1 && f.polls == 2);
    assert(f.polled_at[0] == 5000 && f.polled_at[1] == 10000);
    f = setup();
    f.interval = 1;
    f.responses[0] = linked();
    f.response_count = 1;
    assert(run(&f) == PB_LINK_SUCCESS && f.polled_at[0] == 5000);
    f = setup();
    f.responses[0] = (pb_link_poll_t){.status = 429, .retry_after = 30};
    f.responses[1] = (pb_link_poll_t){.status = 503};
    f.responses[2] = linked();
    f.response_count = 3;
    assert(run(&f) == PB_LINK_SUCCESS && f.polled_at[1] == 35000 && f.polled_at[2] == 55000);
    f = setup();
    f.responses[0] = (pb_link_poll_t){.status = 0};
    f.responses[1] = linked();
    f.response_count = 2;
    assert(run(&f) == PB_LINK_SUCCESS && f.polls == 2);
    f = setup();
    f.lifetime = 6;
    f.start_delay = 2000;
    assert(run(&f) == PB_LINK_EXPIRED && f.polls == 0 && f.now == 6000);
    f = setup();
    f.responses[0] = (pb_link_poll_t){.status = 404};
    f.response_count = 1;
    assert(run(&f) == PB_LINK_EXPIRED && !f.saves);
    f = setup();
    f.responses[0] = linked();
    f.responses[0].credential[0] = '!';
    f.response_count = 1;
    assert(run(&f) == PB_LINK_FAILED && !f.saves);
    f = setup();
    f.malformed = true;
    assert(run(&f) == PB_LINK_FAILED && !f.polls && !f.saves);
    f = setup();
    f.cancelled = true;
    assert(run(&f) == PB_LINK_CANCELLED && !f.starts && !f.saves);
    f = setup();
    f.cancel_at = 1000;
    assert(run(&f) == PB_LINK_CANCELLED && !f.polls && !f.saves);
    f = setup();
    f.responses[0] = linked();
    f.response_count = 1;
    f.poll_delay = 1000;
    f.cancel_at = 5500;
    assert(run(&f) == PB_LINK_CANCELLED && f.polls == 1 && !f.saves);
    f = setup();
    f.responses[0] = linked();
    f.response_count = 1;
    f.failures = 2;
    assert(run(&f) == PB_LINK_SUCCESS && f.polls == 1 && f.saves == 3);
    f = setup();
    f.responses[0] = (pb_link_poll_t){.status = 429, .retry_after = 600};
    f.response_count = 1;
    assert(run(&f) == PB_LINK_EXPIRED && f.polls == 1 && f.now == 300000);
    pb_link_details_t d;
    f = setup();
    start(&f, &d);
    assert(pb_link_details_valid(&d));
    strcpy(d.uri, "https://peabrain.se/\nspoof");
    assert(!pb_link_details_valid(&d));
    assert(!pb_link_token_valid("short"));
    f = setup();
    f.start_delay = 1000;
    f.cancel_at = 500;
    assert(run(&f) == PB_LINK_CANCELLED && !f.polls && !f.saves);
    f = setup();
    f.lifetime = 6;
    f.poll_delay = 2000;
    f.responses[0] = linked();
    f.response_count = 1;
    assert(run(&f) == PB_LINK_EXPIRED && !f.saves);
    f = setup();
    f.failures = 5;
    f.cancel_at = 5500;
    f.responses[0] = linked();
    f.response_count = 1;
    assert(run(&f) == PB_LINK_CANCELLED && f.saves == 1 && f.polls == 1);
    assert(
        pb_link_uri_matches_base("https://peabrain.se/index.php#devices", "https://peabrain.se"));
    assert(
        pb_link_uri_matches_base("https://peabrain.se/index.php#devices", "https://peabrain.se/"));
    assert(
        pb_link_uri_matches_base("https://host.test/pb/index.php#devices", "https://host.test/pb"));
    assert(!pb_link_uri_matches_base("https://peabrain.se.evil.test/index.php",
                                     "https://peabrain.se"));
    assert(!pb_link_uri_matches_base("https://pocketbrain.example.com/index.php",
                                     "https://peabrain.se"));
    puts("PocketBrain linking tests passed");
}
