#include "pb.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_heap_caps.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>

/* All navigation state belongs to app_main. The worker owns each submitted job
   until it posts a result. UI updates cross tasks only through ui_lock. */
typedef enum {
    JOB_TURN,
    JOB_PAIR,
    JOB_WIFI,
    JOB_HISTORY,
    JOB_OPEN,
    JOB_RESUME,
    JOB_DELETE,
    JOB_NEW,
    JOB_UNLINK,
    JOB_LOOPBACK
} job_kind_t;
typedef struct {
    job_kind_t kind;
    cJSON *arg;
    pb_turn_t *turn;
} job_t;
typedef struct {
    job_kind_t kind;
    esp_err_t error;
    cJSON *data;
} result_t;
static QueueHandle_t jobs, results;
static SemaphoreHandle_t ui_lock;
static char status_text[512], *screen_text;
static cJSON *cache, *preview, *index_page;
static pb_turn_t *turn, *staged;
static bool busy, audio_ready, recording, limit_reached;
static job_kind_t active_job;
static atomic_bool pairing_cancel;
static bool pending_ram, confirmation;
static int scroll, history_selection;
static uint64_t record_started, last_activity;
static pb_controls_t controls;
static const char *menu[] = {
    "New conversation", "History", "Continue here",  "Delete conversation", "Retry question/save",
    "Discard pending",  "Volume",  "Mute",           "Wi-Fi setup",         "Link account",
    "Display timeout",  "Usage",   "Unlink locally", "Retry in new thread", "5s audio loopback"};
#define MENU_COUNT (sizeof(menu) / sizeof(menu[0]))
static const char *str(cJSON *j, const char *key) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(j, key);
    return cJSON_IsString(v) ? v->valuestring : "";
}
static void setstr(cJSON *j, const char *key, const char *value) {
    cJSON_DeleteItemFromObjectCaseSensitive(j, key);
    cJSON_AddStringToObject(j, key, value);
}
void pb_status(const char *message) {
    xSemaphoreTake(ui_lock, portMAX_DELAY);
    snprintf(status_text, sizeof(status_text), "%s", message);
    xSemaphoreGive(ui_lock);
    printf("\n[PocketBrain] %s\n", message);
}
void pb_text(const char *text) {
    xSemaphoreTake(ui_lock, portMAX_DELAY);
    snprintf(screen_text, PB_CACHE_MAX + 1, "%s", text);
    xSemaphoreGive(ui_lock);
}
static cJSON *load_cache(void) {
    void *raw;
    size_t len;
    cJSON *loaded = NULL;
    if (pb_blob_load("history", &raw, &len) == ESP_OK) {
        loaded = cJSON_ParseWithLength(raw, len);
        free(raw);
    }
    return loaded ? loaded : cJSON_CreateObject();
}
static void show_thread(cJSON *thread) {
    size_t used = 0;
    char *text = calloc(1, PB_CACHE_MAX + 1);
    if (!text)
        return;
    cJSON *t;
    cJSON_ArrayForEach(t, cJSON_GetObjectItemCaseSensitive(thread, "turns")) {
        int n = snprintf(text + used, PB_CACHE_MAX + 1 - used, "You: %s\n\nPocketBrain: %s%s\n\n",
                         str(t, "question_text"), str(t, "reply_text"),
                         !strcmp(str(t, "reply_status"), "interrupted") ? " [interrupted]" : "");
        if (n < 0 || (size_t)n >= PB_CACHE_MAX + 1 - used)
            break;
        used += n;
    }
    pb_text(text);
    /* Open at the newest reply, leaving wheel-up access to older cached turns. */
    size_t lines = pb_text_lines(text, 21);
    scroll = lines > 18 ? (int)lines - 18 : 0;
    free(text);
    pb_status(*str(thread, "title") ? str(thread, "title") : "PocketBrain ready");
    if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(thread, "older_unavailable")))
        pb_status("Older turns need a connection; cached newest turns below");
}
static bool valid_id(const char *id) {
    return *id && strlen(id) <= 20 && strspn(id, "0123456789") == strlen(id);
}
static esp_err_t persist_cache(cJSON *thread) {
    cJSON *turns = cJSON_GetObjectItemCaseSensitive(thread, "turns");
    for (;;) {
        char *raw = cJSON_PrintUnformatted(thread);
        if (!raw)
            return ESP_ERR_NO_MEM;
        size_t length = strlen(raw);
        if (length <= PB_CACHE_MAX) {
            esp_err_t err = pb_blob_save("history", raw, length);
            free(raw);
            return err;
        }
        free(raw);
        if (cJSON_GetArraySize(turns) <= 1)
            return ESP_ERR_INVALID_SIZE;
        cJSON_DeleteItemFromArray(turns, 0);
        cJSON_DeleteItemFromObjectCaseSensitive(thread, "older_unavailable");
        cJSON_AddTrueToObject(thread, "older_unavailable");
    }
}
static cJSON *fetch_thread(const char *id) {
    if (!valid_id(id))
        return NULL;
    cJSON *thread = cJSON_CreateObject(), *turns = cJSON_AddArrayToObject(thread, "turns");
    cJSON_AddStringToObject(thread, "conversation_id", id);
    char after[21] = "0";
    for (unsigned page = 0; page < 10000; ++page) {
        char action[128];
        snprintf(action, sizeof(action), "conversation&id=%s&after_id=%s", id, after);
        int status;
        cJSON *reply = pb_api(action, pb_settings.credential, NULL, &status);
        if (status != 200 || !reply) {
            cJSON_Delete(reply);
            cJSON_Delete(thread);
            return NULL;
        }
        cJSON *conversation = cJSON_GetObjectItemCaseSensitive(reply, "conversation");
        setstr(thread, "title", str(conversation, "title"));
        cJSON_DeleteItemFromObjectCaseSensitive(thread, "language_tag");
        cJSON *language = cJSON_GetObjectItemCaseSensitive(conversation, "language_tag");
        cJSON_AddItemToObject(thread, "language_tag",
                              language ? cJSON_Duplicate(language, true) : cJSON_CreateNull());
        cJSON *t;
        cJSON_ArrayForEach(t, cJSON_GetObjectItemCaseSensitive(reply, "turns"))
            cJSON_AddItemToArray(turns, cJSON_Duplicate(t, true));
        /* Keep bounded memory even when traversing very long histories. */
        for (;;) {
            char *serialized = cJSON_PrintUnformatted(thread);
            bool fits = serialized && strlen(serialized) <= PB_CACHE_MAX;
            free(serialized);
            if (fits)
                break;
            if (cJSON_GetArraySize(turns) <= 1) {
                cJSON_Delete(reply);
                cJSON_Delete(thread);
                return NULL;
            }
            cJSON_DeleteItemFromArray(turns, 0);
            cJSON_DeleteItemFromObjectCaseSensitive(thread, "older_unavailable");
            cJSON_AddTrueToObject(thread, "older_unavailable");
        }
        const char *next = str(reply, "next_after_id");
        if (!*next) {
            cJSON_Delete(reply);
            return thread;
        }
        if (!valid_id(next) || !strcmp(next, after)) {
            cJSON_Delete(reply);
            break;
        }
        snprintf(after, sizeof(after), "%s", next);
        cJSON_Delete(reply);
    }
    cJSON_Delete(thread);
    return NULL;
}
static void worker(void *arg) {
    (void)arg;
    job_t job;
    for (;;) {
        xQueueReceive(jobs, &job, portMAX_DELAY);
        result_t result = {.kind = job.kind, .error = ESP_FAIL};
        int status = 0;
        if (job.kind == JOB_TURN)
            result.error = pb_realtime(job.turn);
        else if (job.kind == JOB_LOOPBACK) {
            int16_t *pcm = heap_caps_malloc(PB_MAX_PCM, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            if (pcm) {
                pb_status("Loopback: speak for five seconds");
                pb_capture_start(pcm);
                vTaskDelay(pdMS_TO_TICKS(5000));
                size_t samples = pb_capture_stop();
                pb_play_begin();
                pb_status("Loopback: playing");
                result.error = pb_play(pcm, samples * 2);
                free(pcm);
            }
        } else if (job.kind == JOB_WIFI)
            result.error = pb_provision();
        else if (job.kind == JOB_PAIR)
            result.error = pb_pair(&pairing_cancel);
        else if (job.kind == JOB_UNLINK) {
            /* Commit tombstones before allowing this unit to pair to another owner. */
            result.error = pb_blob_save("pending", NULL, 0);
            if (result.error == ESP_OK)
                result.error = pb_blob_save("history", NULL, 0);
            if (result.error == ESP_OK) {
                pb_settings.credential[0] = 0;
                result.error = pb_settings_save();
            }
        } else if (pb_network_connect() == ESP_OK && pb_settings.credential[0]) {
            if (job.kind == JOB_HISTORY) {
                const char *offset = str(job.arg, "offset");
                char action[96];
                snprintf(action, sizeof(action), "conversations&offset=%s", *offset ? offset : "0");
                result.data = pb_api(action, pb_settings.credential, NULL, &status);
                if (status == 200 && result.data) {
                    const char *active = str(result.data, "active_conversation_id");
                    cJSON *local = load_cache();
                    if (valid_id(str(local, "conversation_id"))) {
                        char verify[96];
                        snprintf(verify, sizeof(verify), "conversation&id=%s",
                                 str(local, "conversation_id"));
                        int verify_status;
                        cJSON *check = pb_api(verify, pb_settings.credential, NULL, &verify_status);
                        cJSON_Delete(check);
                        if (verify_status == 404) {
                            pb_blob_save("history", NULL, 0);
                            cJSON_Delete(local);
                            local = cJSON_CreateObject();
                        }
                    }
                    if (valid_id(active)) {
                        cJSON *fresh = fetch_thread(active);
                        if (fresh) {
                            persist_cache(fresh);
                            cJSON_Delete(fresh);
                        }
                    } else {
                        cJSON_DeleteItemFromObjectCaseSensitive(local, "inactive");
                        cJSON_AddTrueToObject(local, "inactive");
                        persist_cache(local);
                    }
                    cJSON_Delete(local);
                }
            } else if (job.kind == JOB_OPEN) {
                result.data = fetch_thread(str(job.arg, "conversation_id"));
                status = result.data ? 200 : 0;
            } else {
                const char *action =
                    job.kind == JOB_DELETE ? "conversation-delete" : "conversation-active";
                cJSON *body = cJSON_CreateObject();
                const char *id = str(job.arg, "conversation_id");
                if (job.kind == JOB_NEW)
                    cJSON_AddNullToObject(body, "conversation_id");
                else
                    cJSON_AddStringToObject(body, "conversation_id", id);
                result.data = pb_api(action, pb_settings.credential, body, &status);
                cJSON_Delete(body);
                if (status == 200 && result.data) {
                    if (job.kind == JOB_RESUME)
                        result.error = persist_cache(job.arg);
                    else if (job.kind == JOB_NEW) {
                        cJSON *cached = load_cache();
                        cJSON_DeleteItemFromObjectCaseSensitive(cached, "inactive");
                        cJSON_AddTrueToObject(cached, "inactive");
                        result.error = persist_cache(cached);
                        cJSON_Delete(cached);
                    } else {
                        cJSON *cached = load_cache();
                        result.error = !strcmp(str(cached, "conversation_id"), id)
                                           ? pb_blob_save("history", NULL, 0)
                                           : ESP_OK;
                        cJSON_Delete(cached);
                    }
                }
            }
            if ((job.kind == JOB_HISTORY || job.kind == JOB_OPEN) && status == 200 && result.data)
                result.error = ESP_OK;
        }
        cJSON_Delete(job.arg);
        xQueueSend(results, &result, portMAX_DELAY);
    }
}
static void submit(job_kind_t kind, cJSON *arg, pb_turn_t *t) {
    if (busy || (recording && kind != JOB_TURN)) {
        cJSON_Delete(arg);
        return;
    }
    job_t job = {.kind = kind, .arg = arg, .turn = t};
    busy = true;
    active_job = kind;
    if (kind == JOB_PAIR) {
        atomic_store(&pairing_cancel, false);
        controls.menu = false;
        scroll = 0;
    }
    xQueueSend(jobs, &job, portMAX_DELAY);
}
static bool pending_exists(void) {
    if (pending_ram)
        return true;
    void *data;
    size_t n;
    if (pb_blob_load("pending", &data, &n) == ESP_OK) {
        free(data);
        return true;
    }
    return false;
}
static esp_err_t ensure_audio(void) {
    if (!audio_ready) {
        esp_err_t err = pb_audio_init();
        if (err != ESP_OK)
            return err;
        audio_ready = true;
    }
    return ESP_OK;
}
static void free_turn(void) {
    if (!turn)
        return;
    cJSON_Delete(turn->meta);
    free(turn->pcm);
    free(turn);
    turn = NULL;
}
static cJSON *new_meta(void) {
    cJSON *meta = cJSON_CreateObject();
    char id[37];
    pb_uuid(id);
    cJSON_AddStringToObject(meta, "client_turn_id", id);
    bool active = !cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(cache, "inactive")) &&
                  *str(cache, "conversation_id");
    if (active) {
        cJSON_AddStringToObject(meta, "conversation_id", str(cache, "conversation_id"));
        cJSON_AddStringToObject(meta, "title", str(cache, "title"));
        cJSON *language = cJSON_GetObjectItemCaseSensitive(cache, "language_tag");
        if (language)
            cJSON_AddItemToObject(meta, "language_tag", cJSON_Duplicate(language, true));
    } else
        cJSON_AddNullToObject(meta, "conversation_id");
    cJSON *context = cJSON_AddArrayToObject(meta, "context");
    cJSON *turns = cJSON_GetObjectItemCaseSensitive(cache, "turns");
    int n = active ? cJSON_GetArraySize(turns) : 0;
    for (int i = n > 6 ? n - 6 : 0; i < n; ++i) {
        cJSON *source = cJSON_GetArrayItem(turns, i), *t = cJSON_CreateObject();
        const char *keys[] = {"question_text", "reply_text"};
        for (unsigned j = 0; j < 2; ++j) {
            const char *value = str(source, keys[j]);
            char text[2001];
            size_t len = strlen(value);
            if (len > 2000)
                len = 2000;
            while (len && ((unsigned char)value[len] & 0xc0) == 0x80)
                --len;
            memcpy(text, value, len);
            text[len] = 0;
            cJSON_AddStringToObject(t, keys[j], text);
        }
        cJSON_AddItemToArray(context, t);
    }
    return meta;
}
static pb_turn_t *allocate_recording(void) {
    pb_turn_t *t = calloc(1, sizeof(*t));
    if (!t)
        return NULL;
    t->pcm = heap_caps_malloc(PB_MAX_PCM, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!t->pcm) {
        free(t);
        return NULL;
    }
    atomic_init(&t->recording, true);
    atomic_init(&t->cancel, false);
    return t;
}
static void begin_capture(pb_turn_t *t) {
    pb_play_stop();
    pb_text("");
    scroll = 0;
    pb_capture_start(t->pcm);
    record_started = esp_timer_get_time() / 1000;
    recording = true;
    limit_reached = false;
    pb_status("Listening");
}
static void start_recording(void) {
    if (recording || staged)
        return;
    if (busy) {
        if (active_job == JOB_TURN && turn) {
            /* A second PSRAM buffer lets capture start immediately while the old
               worker cancels generation and saves the interrupted transcript. */
            atomic_store(&turn->cancel, true);
            pb_play_stop();
            staged = allocate_recording();
            if (staged)
                begin_capture(staged);
            else
                pb_status("PSRAM allocation failed");
        }
        return;
    }
    if (pending_exists()) {
        pb_status("Question saved: Retry or confirm Discard before recording another");
        return;
    }
    free_turn();
    if (ensure_audio() != ESP_OK) {
        pb_status("Audio initialization failed");
        return;
    }
    turn = allocate_recording();
    if (!turn) {
        pb_status("PSRAM allocation failed");
        return;
    }
    turn->meta = new_meta();
    if (!turn->meta) {
        free_turn();
        return;
    }
    begin_capture(turn);
    submit(JOB_TURN, NULL, turn);
}
static void submit_staged(void) {
    if (!staged || turn)
        return;
    turn = staged;
    staged = NULL;
    turn->meta = new_meta();
    if (!turn->meta) {
        pb_status("Could not allocate next question metadata");
        return;
    }
    submit(JOB_TURN, NULL, turn);
    pb_status(recording ? "Listening" : "Preparing next question");
}
static void stop_recording(void) {
    if (!recording)
        return;
    pb_turn_t *capturing = staged ? staged : turn;
    capturing->samples = pb_capture_stop();
    recording = false;
    /* Publish samples only after capture has stopped. Worker reads on acquire. */
    atomic_store(&capturing->recording, false);
    pb_status(staged && !busy
                  ? "Next question held in RAM; Retry or Discard previous pending question first"
                  : "Preparing question");
}
static void retry_pending(bool new_thread) {
    if (busy)
        return;
    if (!pending_ram) {
        free_turn();
        turn = calloc(1, sizeof(*turn));
        if (!turn)
            return;
        if (pb_pending_load(&turn->meta, &turn->pcm, &turn->samples) != ESP_OK) {
            free_turn();
            pb_status("No saved question");
            return;
        }
        turn->durable = true;
    }
    if (new_thread) {
        if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(turn->meta, "transcript_ready"))) {
            pb_status("Completed transcript keeps its original thread");
            return;
        }
        cJSON_DeleteItemFromObjectCaseSensitive(turn->meta, "conversation_id");
        cJSON_AddNullToObject(turn->meta, "conversation_id");
        cJSON_DeleteItemFromObjectCaseSensitive(turn->meta, "context");
        cJSON_DeleteItemFromObjectCaseSensitive(turn->meta, "language_tag");
        cJSON_DeleteItemFromObjectCaseSensitive(turn->meta, "title");
        /* New intent means a new id; ordinary retries always retain their id. */
        char id[37];
        pb_uuid(id);
        setstr(turn->meta, "client_turn_id", id);
    }
    if (ensure_audio() != ESP_OK)
        return;
    atomic_store(&turn->cancel, false);
    atomic_store(&turn->recording, false);
    submit(JOB_TURN, NULL, turn);
    pb_status("Retrying saved question");
}
static void show_menu(void) {
    char text[1536] = "";
    size_t used = 0;
    for (unsigned i = 0; i < MENU_COUNT; ++i)
        used += snprintf(text + used, sizeof(text) - used, "%c %s\n",
                         controls.selection == i ? '>' : ' ', menu[i]);
    pb_text(text);
    scroll = controls.selection > 18 ? controls.selection - 18 : 0;
    pb_status(confirmation ? "Press wheel again to confirm; Talk cancels"
                           : "Menu: wheel selects; Talk goes Back");
}
static void show_index(void) {
    char *text = calloc(1, 12288);
    if (!text)
        return;
    size_t used = 0;
    cJSON *row;
    int i = 0;
    cJSON_ArrayForEach(row, cJSON_GetObjectItemCaseSensitive(index_page, "conversations")) {
        int n = snprintf(text + used, 12288 - used, "%c %.160s\n",
                         i++ == history_selection ? '>' : ' ', str(row, "title"));
        if (n < 0 || (size_t)n >= 12288 - used)
            break;
        used += n;
    }
    if (*str(index_page, "next_offset"))
        snprintf(text + used, 12288 - used, "%c More conversations\n",
                 i == history_selection ? '>' : ' ');
    pb_text(text);
    free(text);
    scroll = history_selection > 15 ? history_selection - 15 : 0;
    pb_status("History preview; Talk returns");
}
static void select_menu(void) {
    int selection = controls.selection;
    bool destructive = selection == 3 || selection == 5 || selection == 12 || selection == 13;
    if (destructive && !confirmation) {
        confirmation = true;
        show_menu();
        return;
    }
    confirmation = false;
    if (busy || recording) {
        pb_status("Wait for the current operation");
        return;
    }
    switch (selection) {
    case 0:
        if (pending_exists()) {
            pb_status("Retry or discard pending question first");
            return;
        }
        submit(JOB_NEW, NULL, NULL);
        break;
    case 1:
        submit(JOB_HISTORY, NULL, NULL);
        break;
    case 2:
        if (preview && !pending_exists())
            submit(JOB_RESUME, cJSON_Duplicate(preview, true), NULL);
        else
            pb_status("Preview History first; resolve any pending question");
        break;
    case 3:
        if (preview && !pending_exists())
            submit(JOB_DELETE, cJSON_Duplicate(preview, true), NULL);
        else
            pb_status("Preview a thread first; resolve any pending question");
        break;
    case 4:
        retry_pending(false);
        break;
    case 5:
        if (pb_blob_save("pending", NULL, 0) == ESP_OK) {
            pending_ram = false;
            free_turn();
            pb_status("Pending question discarded");
            submit_staged();
        } else
            pb_status("Could not clear pending flash");
        break;
    case 6:
        pb_settings.volume = (pb_settings.volume + 10) % 110;
        pb_settings_save();
        {
            char text[64];
            snprintf(text, sizeof(text), "Volume %u%%", pb_settings.volume);
            pb_status(text);
        }
        break;
    case 7:
        pb_settings.muted = !pb_settings.muted;
        pb_settings_save();
        pb_status(pb_settings.muted ? "Mute on" : "Mute off");
        break;
    case 8:
        submit(JOB_WIFI, NULL, NULL);
        break;
    case 9:
        if (pb_settings.credential[0])
            pb_status("Already linked; unlink locally before pairing again");
        else
            submit(JOB_PAIR, NULL, NULL);
        break;
    case 10:
        pb_settings.timeout = pb_settings.timeout == 120 ? 600 : 120;
        pb_settings_save();
        pb_status(pb_settings.timeout == 120 ? "Display timeout: 2 minutes"
                                             : "Display timeout: 10 minutes");
        break;
    case 11:
        pb_status("Usage is available in the backend dashboard");
        break;
    case 12:
        submit(JOB_UNLINK, NULL, NULL);
        break;
    case 13:
        retry_pending(true);
        break;
    case 14:
        if (ensure_audio() == ESP_OK)
            submit(JOB_LOOPBACK, NULL, NULL);
        break;
    }
    controls.menu = false;
}
static void process_results(void) {
    result_t result;
    if (xQueueReceive(results, &result, 0) != pdPASS)
        return;
    busy = false;
    last_activity = esp_timer_get_time() / 1000;
    if (result.kind == JOB_TURN) {
        cJSON_Delete(cache);
        cache = load_cache();
        pending_ram = result.error != ESP_OK && turn && turn->samples >= PB_MIN_SAMPLES;
        if (result.error == ESP_OK) {
            pb_status("Reply saved");
            pending_ram = false;
            free_turn();
            submit_staged();
        } else if (result.error == ESP_ERR_INVALID_SIZE) {
            pb_status("Hold Talk for at least 0.1 seconds");
            pending_ram = false;
            free_turn();
            submit_staged();
        } else
            pb_status(
                turn && turn->durable
                    ? "Question saved: Retry or Discard in menu"
                    : "Flash write failed; recording retained in RAM. Keep power on and Retry.");

    } else if (result.kind == JOB_PAIR) {
        /* The linking screen retains its specific success/cancel/expiry/error. */
        controls.menu = false;
    } else if (result.error != ESP_OK)
        pb_status("Operation failed; check Wi-Fi/backend and try again");
    else if (result.kind == JOB_HISTORY) {
        cJSON_Delete(cache);
        cache = load_cache();
        cJSON_Delete(index_page);
        index_page = result.data;
        result.data = NULL;
        controls.menu = true;
        history_selection = 0;
        show_index();
    } else if (result.kind == JOB_OPEN) {
        cJSON_Delete(preview);
        preview = result.data;
        result.data = NULL;
        controls.menu = false;
        show_thread(preview);
    } else if (result.kind == JOB_RESUME || result.kind == JOB_DELETE || result.kind == JOB_NEW ||
               result.kind == JOB_UNLINK) {
        cJSON_Delete(cache);
        cache = load_cache();
        cJSON_Delete(preview);
        preview = NULL;
        if (result.kind == JOB_UNLINK) {
            pending_ram = false;
            free_turn();
            if (staged) {
                free(staged->pcm);
                cJSON_Delete(staged->meta);
                free(staged);
                staged = NULL;
            }
        }
        show_thread(cache);
    } else
        pb_status(result.kind == JOB_PAIR       ? "Account linked"
                  : result.kind == JOB_LOOPBACK ? "Loopback complete"
                                                : "Wi-Fi configured");
    cJSON_Delete(result.data);
}
static bool linking(void) {
    return busy && active_job == JOB_PAIR;
}
static void cancel_link(void) {
    atomic_store(&pairing_cancel, true);
    pb_status("Cancelling linking");
}
static void go_back(void) {
    confirmation = false;
    if (index_page) {
        cJSON_Delete(index_page);
        index_page = NULL;
        controls.menu = true;
        show_menu();
    } else {
        controls.menu = false;
        show_thread(preview ? preview : cache);
    }
}
static void rotate(int direction) {
    last_activity = esp_timer_get_time() / 1000;
    if (controls.menu && index_page) {
        int count =
            cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(index_page, "conversations")) +
            (*str(index_page, "next_offset") ? 1 : 0);
        history_selection += direction;
        if (history_selection < 0)
            history_selection = 0;
        if (history_selection >= count)
            history_selection = count ? count - 1 : 0;
        show_index();
    } else if (controls.menu) {
        confirmation = false;
        controls.selection = (controls.selection + direction + MENU_COUNT) % MENU_COUNT;
        show_menu();
    } else {
        scroll += direction * 3;
        xSemaphoreTake(ui_lock, portMAX_DELAY);
        size_t lines = pb_text_lines(screen_text, 21);
        xSemaphoreGive(ui_lock);
        int maximum = lines > 18 ? (int)lines - 18 : 0;
        if (scroll > maximum)
            scroll = maximum;
        if (scroll < 0)
            scroll = 0;
    }
}
static void select_wheel(void) {
    if (controls.menu && index_page) {
        cJSON *row = cJSON_GetArrayItem(
            cJSON_GetObjectItemCaseSensitive(index_page, "conversations"), history_selection);
        if (!row && *str(index_page, "next_offset")) {
            cJSON *arg = cJSON_CreateObject();
            cJSON_AddStringToObject(arg, "offset", str(index_page, "next_offset"));
            submit(JOB_HISTORY, arg, NULL);
        }
        if (row) {
            cJSON *arg = cJSON_CreateObject();
            cJSON_AddStringToObject(arg, "conversation_id", str(row, "id"));
            submit(JOB_OPEN, arg, NULL);
        }
        cJSON_Delete(index_page);
        index_page = NULL;
    } else
        select_menu();
}
static void sleep_device(void) {
    if (busy || recording || staged || (pending_ram && turn && !turn->durable) ||
        (audio_ready && pb_playing()))
        return;
    if (!gpio_get_level(CONFIG_PB_TALK_PIN) || !gpio_get_level(CONFIG_PB_WHEEL_PUSH_PIN))
        return;
    pb_status("Sleeping");
    pb_network_stop();
    if (audio_ready)
        pb_play_stop();
    pb_display_sleep();
    ESP_ERROR_CHECK(esp_sleep_enable_ext1_wakeup((1ULL << CONFIG_PB_TALK_PIN) |
                                                     (1ULL << CONFIG_PB_WHEEL_PUSH_PIN),
                                                 ESP_EXT1_WAKEUP_ANY_LOW));
    ESP_ERROR_CHECK(rtc_gpio_pullup_en(CONFIG_PB_TALK_PIN));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis(CONFIG_PB_TALK_PIN));
    ESP_ERROR_CHECK(rtc_gpio_pullup_en(CONFIG_PB_WHEEL_PUSH_PIN));
    ESP_ERROR_CHECK(rtc_gpio_pulldown_dis(CONFIG_PB_WHEEL_PUSH_PIN));
    esp_deep_sleep_start();
}
static void check_pins(void) {
    int pins[] = {
        CONFIG_PB_TALK_PIN,    CONFIG_PB_WHEEL_PUSH_PIN, CONFIG_PB_WHEEL_A_PIN,
        CONFIG_PB_WHEEL_B_PIN, CONFIG_PB_BCLK_PIN,       CONFIG_PB_WS_PIN,
        CONFIG_PB_MIC_PIN,     CONFIG_PB_SPEAKER_PIN,    CONFIG_PB_AMP_SD_PIN,
#if CONFIG_PB_OLED_ENABLED
        CONFIG_PB_OLED_CS_PIN, CONFIG_PB_OLED_MOSI_PIN,  CONFIG_PB_OLED_CLK_PIN,
        CONFIG_PB_OLED_DC_PIN, CONFIG_PB_OLED_RESET_PIN,
#endif
    };
    for (size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
        if (pins[i] < 0)
            continue;
        ESP_ERROR_CHECK(GPIO_IS_VALID_GPIO(pins[i]) ? ESP_OK : ESP_ERR_INVALID_ARG);
        ESP_ERROR_CHECK((pins[i] < 26 || pins[i] > 37) ? ESP_OK : ESP_ERR_INVALID_ARG);
        for (size_t j = 0; j < i; ++j)
            ESP_ERROR_CHECK(pins[i] != pins[j] ? ESP_OK : ESP_ERR_INVALID_ARG);
    }
    ESP_ERROR_CHECK(rtc_gpio_is_valid_gpio(CONFIG_PB_TALK_PIN) &&
                            rtc_gpio_is_valid_gpio(CONFIG_PB_WHEEL_PUSH_PIN)
                        ? ESP_OK
                        : ESP_ERR_INVALID_ARG);
}
void app_main(void) {
    check_pins();
    ui_lock = xSemaphoreCreateMutex();
    screen_text = heap_caps_calloc(1, PB_CACHE_MAX + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    ESP_ERROR_CHECK(ui_lock && screen_text ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(pb_storage_init());
    ESP_ERROR_CHECK(pb_network_init());
    pb_display_init();
    cache = load_cache();
    show_thread(cache);
    if (pending_exists())
        pb_status("Question saved: open menu for Retry or Discard");
    /* Wi-Fi is initialized but never started until a network action or Talk. */
    jobs = xQueueCreate(1, sizeof(job_t));
    results = xQueueCreate(1, sizeof(result_t));
    ESP_ERROR_CHECK(jobs && results ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreate(worker, "pb_network", 24576, NULL, 4, NULL) == pdPASS
                        ? ESP_OK
                        : ESP_ERR_NO_MEM);
    gpio_config_t cfg = {.pin_bit_mask =
                             (1ULL << CONFIG_PB_TALK_PIN) | (1ULL << CONFIG_PB_WHEEL_PUSH_PIN),
                         .mode = GPIO_MODE_INPUT,
                         .pull_up_en = true};
    if (CONFIG_PB_WHEEL_A_PIN >= 0 && CONFIG_PB_WHEEL_B_PIN >= 0)
        cfg.pin_bit_mask |= (1ULL << CONFIG_PB_WHEEL_A_PIN) | (1ULL << CONFIG_PB_WHEEL_B_PIN);
    rtc_gpio_deinit(CONFIG_PB_TALK_PIN);
    rtc_gpio_deinit(CONFIG_PB_WHEEL_PUSH_PIN);
    ESP_ERROR_CHECK(gpio_config(&cfg));
    uint64_t wake = esp_sleep_get_ext1_wakeup_status();
    controls.consume_wheel =
        !!(wake & (1ULL << CONFIG_PB_WHEEL_PUSH_PIN)) && !gpio_get_level(CONFIG_PB_WHEEL_PUSH_PIN);
    controls.consume_talk = controls.consume_wheel && !gpio_get_level(CONFIG_PB_TALK_PIN);
    pb_button_t talk = {0}, wheel = {0};
    int old_encoder = 0, encoder_steps = 0;
    static const int8_t transitions[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
    fcntl(STDIN_FILENO, F_SETFL, O_NONBLOCK);
    printf("\nSerial keys: t=Talk down, r=Talk up, w=wheel, j/k=scroll, b=Back, p=pair, f=Wi-Fi, "
           "s=sleep\n");
    last_activity = esp_timer_get_time() / 1000;
    uint64_t last_render = 0;
    for (;;) {
        process_results();
        uint64_t now = esp_timer_get_time() / 1000;
        bool talk_changed = pb_button_update(&talk, !gpio_get_level(CONFIG_PB_TALK_PIN), now);
        if (talk_changed) {
            last_activity = now;
            if (linking() && talk.stable) {
                cancel_link();
                controls.consume_talk = true;
                continue;
            }
            pb_action_t action = pb_talk(&controls, talk.stable);
            if (action == PB_BACK)
                go_back();
            if (action == PB_RECORD_START)
                start_recording();
            if (action == PB_RECORD_END)
                stop_recording();
        }
        if (pb_button_update(&wheel, !gpio_get_level(CONFIG_PB_WHEEL_PUSH_PIN), now)) {
            last_activity = now;
            if (linking() || recording) { /* Keep linking/capture screen visible. */
            } else if (wheel.stable && audio_ready &&
                       (pb_playing() || (busy && active_job == JOB_TURN && turn && !recording))) {
                if (turn)
                    atomic_store(&turn->cancel, true);
                pb_play_stop();
            } else {
                pb_action_t action = pb_wheel_push(&controls, wheel.stable);
                if (action == PB_MENU)
                    show_menu();
                if (action == PB_SELECT)
                    select_wheel();
            }
        }
        if (CONFIG_PB_WHEEL_A_PIN >= 0 && CONFIG_PB_WHEEL_B_PIN >= 0) {
            int encoder = (gpio_get_level(CONFIG_PB_WHEEL_A_PIN) << 1) |
                          gpio_get_level(CONFIG_PB_WHEEL_B_PIN);
            encoder_steps += transitions[(old_encoder << 2) | encoder];
            old_encoder = encoder;
            if (encoder_steps >= 4 || encoder_steps <= -4) {
                rotate(encoder_steps > 0 ? 1 : -1);
                encoder_steps = 0;
            }
        }
        char key;
        while (read(STDIN_FILENO, &key, 1) > 0) {
            last_activity = now;
            if (key == 't') {
                if (linking()) {
                    cancel_link();
                    controls.consume_talk = true;
                    continue;
                }
                pb_action_t a = pb_talk(&controls, true);
                if (a == PB_BACK)
                    go_back();
                else if (a == PB_RECORD_START)
                    start_recording();
            }
            if (key == 'r') {
                if (pb_talk(&controls, false) == PB_RECORD_END)
                    stop_recording();
            }
            if (key == 'j' || key == 'k')
                rotate(key == 'j' ? 1 : -1);
            if (key == 'w' && !linking()) {
                pb_action_t a = pb_wheel_push(&controls, true);
                if (a == PB_MENU)
                    show_menu();
                else if (a == PB_SELECT)
                    select_wheel();
                pb_wheel_push(&controls, false);
            }
            if (key == 'b') {
                if (linking())
                    cancel_link();
                else
                    go_back();
            }
            if (key == 'p') {
                if (linking())
                    cancel_link();
                else if (!busy && !pb_settings.credential[0])
                    submit(JOB_PAIR, NULL, NULL);
            }
            if (key == 'f')
                submit(JOB_WIFI, NULL, NULL);
            if (key == 'l' && !busy && !recording && ensure_audio() == ESP_OK)
                submit(JOB_LOOPBACK, NULL, NULL);
            if (key == 's')
                sleep_device();
        }
        if (recording && !limit_reached &&
            (!pb_remaining_ms(record_started, now) || pb_capture_samples() >= PB_MAX_SAMPLES)) {
            pb_turn_t *capturing = staged ? staged : turn;
            capturing->samples = pb_capture_stop();
            limit_reached = true;
            pb_status("Recording limit reached; release Talk to send");
            /* Keep recording flag set: releasing Talk is what commits the question. */
        }
        if (now - last_render >= 100) {
            xSemaphoreTake(ui_lock, portMAX_DELAY);
            pb_display_render(status_text, screen_text, scroll,
                              recording ? pb_remaining_ms(record_started, now) : 30001);
            xSemaphoreGive(ui_lock);
            last_render = now;
        }
        if (pb_settings.timeout && now >= last_activity &&
            now - last_activity >= pb_settings.timeout * 1000u)
            sleep_device();
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
