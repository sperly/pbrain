#pragma once
#include "sdkconfig.h"
#include "esp_err.h"
#include "cJSON.h"
#include "pb_core.h"
#include <stdatomic.h>
#include <stdint.h>
#include <stddef.h>
#define PB_TEXT_MAX 32768u
#define PB_METADATA_MAX (256u * 1024u)
#define PB_CACHE_MAX (448u * 1024u)

typedef struct {
    char credential[65];
    bool muted;
    atomic_uint volume;
    unsigned timeout;
} pb_settings_t;
extern pb_settings_t pb_settings;
void pb_status(const char *message);
void pb_text(const char *text);
void pb_display_init(void);
void pb_display_render(const char *status, const char *text, int scroll, unsigned remaining);
void pb_display_sleep(void);

esp_err_t pb_storage_init(void);
esp_err_t pb_settings_save(void);
/* Dual-slot commit-last journals. NULL data/zero length is a durable tombstone. */
esp_err_t pb_blob_load(const char *partition, void **data, size_t *length);
esp_err_t pb_blob_save(const char *partition, const void *data, size_t length);
esp_err_t pb_pending_save(cJSON *meta, const int16_t *pcm, size_t samples);
esp_err_t pb_pending_load(cJSON **meta, int16_t **pcm, size_t *samples);
void pb_uuid(char out[37]);

esp_err_t pb_audio_init(void);
esp_err_t pb_capture_start(int16_t *buffer);
size_t pb_capture_stop(void);
size_t pb_capture_samples(void);
esp_err_t pb_play(const void *pcm, size_t bytes);
void pb_play_begin(void);
void pb_play_stop(void);
bool pb_playing(void);

esp_err_t pb_network_init(void);
esp_err_t pb_network_connect(void);
esp_err_t pb_provision(void);
void pb_network_stop(void);
/* status is HTTP status, or zero on transport failure; caller owns returned JSON. */
cJSON *pb_api(const char *action, const char *token, const cJSON *body, int *status);
esp_err_t pb_pair(const atomic_bool *cancel);

typedef struct {
    atomic_bool cancel;
    atomic_bool recording;
    cJSON *meta; /* Worker-owned; frozen snapshot includes original conversation/context. */
    int16_t *pcm;
    size_t samples;
    bool durable;
} pb_turn_t;
/* Connects while recording, persists PCM before upload, then saves the transcript.
   On any failure the pending journal survives. Caller owns turn and allocations. */
esp_err_t pb_realtime(pb_turn_t *turn);
esp_err_t pb_save_turn(cJSON *meta);
