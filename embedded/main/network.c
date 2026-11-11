#include "pb.h"
#include "pb_link.h"
#include <strings.h>
#include <limits.h>
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_sntp.h"
#include "esp_timer.h"
#include "nvs.h"
#include "wifi_provisioning/manager.h"
#include "wifi_provisioning/scheme_ble.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>

static EventGroupHandle_t network_events;
static atomic_bool started, provisioning;
static wifi_config_t saved_networks[2];
static unsigned reconnect_attempts, network_slot;
#define CONNECTED BIT0
#define PROVISIONED BIT1
#define RESPONSE_LIMIT (2u * 1024u * 1024u)
static void net_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    (void)data;
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP)
        xEventGroupSetBits(network_events, CONNECTED);
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(network_events, CONNECTED);
        if (started && !provisioning) {
            if (++reconnect_attempts % 2 == 0 && saved_networks[1].sta.ssid[0]) {
                network_slot ^= 1;
                esp_wifi_set_config(WIFI_IF_STA, &saved_networks[network_slot]);
            }
            esp_wifi_connect();
        }
    }
    if (base == WIFI_PROV_EVENT && id == WIFI_PROV_CRED_SUCCESS) {
        wifi_config_t cfg;
        if (esp_wifi_get_config(WIFI_IF_STA, &cfg) == ESP_OK) {
            if (memcmp(cfg.sta.ssid, saved_networks[0].sta.ssid, sizeof(cfg.sta.ssid)))
                saved_networks[1] = saved_networks[0];
            saved_networks[0] = cfg;
            network_slot = 0;
            nvs_handle_t nvs;
            if (nvs_open("pb_networks", NVS_READWRITE, &nvs) == ESP_OK) {
                if (nvs_set_blob(nvs, "profiles", saved_networks, sizeof(saved_networks)) == ESP_OK)
                    nvs_commit(nvs);
                nvs_close(nvs);
            }
        }
    }
    if (base == WIFI_PROV_EVENT && id == WIFI_PROV_END) {
        wifi_prov_mgr_deinit();
        provisioning = false;
        xEventGroupSetBits(network_events, PROVISIONED);
    }
}
esp_err_t pb_network_init(void) {
    nvs_handle_t nvs;
    if (nvs_open("pb_networks", NVS_READONLY, &nvs) == ESP_OK) {
        size_t bytes = sizeof(saved_networks);
        if (nvs_get_blob(nvs, "profiles", saved_networks, &bytes) != ESP_OK ||
            bytes != sizeof(saved_networks))
            memset(saved_networks, 0, sizeof(saved_networks));
        nvs_close(nvs);
    }
    network_events = xEventGroupCreate();
    if (!network_events)
        return ESP_ERR_NO_MEM;
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK)
        return err;
    if ((err = esp_event_loop_create_default()) != ESP_OK)
        return err;
    if (!esp_netif_create_default_wifi_sta())
        return ESP_ERR_NO_MEM;
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    if ((err = esp_wifi_init(&cfg)) != ESP_OK)
        return err;
    if ((err = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, net_event, NULL)) !=
            ESP_OK ||
        (err = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, net_event, NULL)) !=
            ESP_OK ||
        (err = esp_event_handler_register(WIFI_PROV_EVENT, ESP_EVENT_ANY_ID, net_event, NULL)) !=
            ESP_OK)
        return err;
    return esp_wifi_set_mode(WIFI_MODE_STA);
}
esp_err_t pb_provision(void) {
    if (!CONFIG_PB_PROVISION_POP[0]) {
        pb_status("Set a unique BLE proof of possession in menuconfig first");
        return ESP_ERR_INVALID_STATE;
    }
    wifi_prov_mgr_config_t cfg = {.scheme = wifi_prov_scheme_ble,
                                  .scheme_event_handler = WIFI_PROV_EVENT_HANDLER_NONE};
    esp_err_t err = wifi_prov_mgr_init(cfg);
    if (err != ESP_OK)
        return err;
    provisioning = true;
    pb_status("Wi-Fi setup: connect with Espressif BLE provisioning app, service PocketBrain");
    err = wifi_prov_mgr_start_provisioning(WIFI_PROV_SECURITY_1, CONFIG_PB_PROVISION_POP,
                                           "PocketBrain", NULL);
    if (err != ESP_OK) {
        wifi_prov_mgr_deinit();
        provisioning = false;
        return err;
    }
    started = true;
    EventBits_t bits =
        xEventGroupWaitBits(network_events, PROVISIONED, pdTRUE, pdFALSE, pdMS_TO_TICKS(180000));
    if (!(bits & PROVISIONED)) {
        wifi_prov_mgr_stop_provisioning();
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}
static esp_err_t network_connect(const atomic_bool *cancel) {
    if (!started) {
        wifi_config_t cfg;
        esp_err_t err = esp_wifi_get_config(WIFI_IF_STA, &cfg);
        if (err != ESP_OK || !cfg.sta.ssid[0])
            return ESP_ERR_INVALID_STATE;
        if (saved_networks[0].sta.ssid[0])
            esp_wifi_set_config(WIFI_IF_STA, &saved_networks[0]);
        network_slot = 0;
        reconnect_attempts = 0;
        started = true;
        if ((err = esp_wifi_start()) != ESP_OK) {
            started = false;
            return err;
        }
        esp_wifi_connect();
    }
    int64_t connect_until = esp_timer_get_time() + 15000000;
    while (!(xEventGroupGetBits(network_events) & CONNECTED)) {
        if (cancel && atomic_load(cancel))
            return ESP_ERR_INVALID_STATE;
        if (esp_timer_get_time() >= connect_until)
            return ESP_ERR_TIMEOUT;
        xEventGroupWaitBits(network_events, CONNECTED, pdFALSE, pdFALSE, pdMS_TO_TICKS(100));
    }
    /* SNTP runs only when networking is requested; read wake stays offline. */
    if (!esp_sntp_enabled()) {
        esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
        esp_sntp_setservername(0, "pool.ntp.org");
        esp_sntp_init();
    }
    int64_t deadline = esp_timer_get_time() + 15000000;
    while (time(NULL) < 1735689600 && esp_timer_get_time() < deadline) {
        if (cancel && atomic_load(cancel))
            return ESP_ERR_INVALID_STATE;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    return time(NULL) >= 1735689600 ? ESP_OK : ESP_ERR_TIMEOUT;
}
esp_err_t pb_network_connect(void) {
    return network_connect(NULL);
}
void pb_network_stop(void) {
    if (started) {
        started = false;
        esp_wifi_stop();
    }
    if (esp_sntp_enabled())
        esp_sntp_stop();
}
typedef struct {
    unsigned retry_after;
} api_headers_t;
static esp_err_t api_header(esp_http_client_event_t *event) {
    if (event->event_id == HTTP_EVENT_ON_HEADER && !strcasecmp(event->header_key, "Retry-After")) {
        char *end;
        unsigned long value = strtoul(event->header_value, &end, 10);
        if (*event->header_value && !*end && value <= 86400)
            ((api_headers_t *)event->user_data)->retry_after = (unsigned)value;
    }
    return ESP_OK;
}
static cJSON *api_request(const char *action, const char *token, const cJSON *body, int *status,
                          unsigned *retry_after) {
    *status = 0;
    const char *base = CONFIG_PB_BACKEND_URL;
    if (strncmp(base, "https://", 8) || strpbrk(base, "\r\n?#@") || !base[8])
        return NULL;
    if (token && strpbrk(token, "\r\n"))
        return NULL;
    char url[768], auth[256];
    int n = snprintf(url, sizeof(url), "%s%sapi.php?action=%s", base,
                     base[strlen(base) - 1] == '/' ? "" : "/", action);
    if (n < 0 || n >= sizeof(url))
        return NULL;
    bool get = !strcmp(action, "device") || !strncmp(action, "conversation&", 13) ||
               !strncmp(action, "conversations", 13);
    api_headers_t response_headers = {0};
    esp_http_client_config_t cfg = {.url = url,
                                    .event_handler = api_header,
                                    .user_data = &response_headers,
                                    .timeout_ms = !strcmp(action, "tool-call") ? 35000 : 15000,
                                    .crt_bundle_attach = esp_crt_bundle_attach,
                                    .disable_auto_redirect = true,
                                    .method = get ? HTTP_METHOD_GET : HTTP_METHOD_POST,
                                    .buffer_size = 2048};
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client)
        return NULL;
    esp_http_client_set_header(client, "Accept", "application/json");
    if (token && *token) {
        n = snprintf(auth, sizeof(auth), "Bearer %s", token);
        if (n < 0 || n >= sizeof(auth)) {
            esp_http_client_cleanup(client);
            return NULL;
        }
        esp_http_client_set_header(client, "Authorization", auth);
    }
    char *json = body ? cJSON_PrintUnformatted(body) : NULL;
    if (body && !json) {
        esp_http_client_cleanup(client);
        return NULL;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");
    size_t request_len = json ? strlen(json) : 0;
    esp_err_t err = esp_http_client_open(client, request_len);
    if (err == ESP_OK && request_len) {
        size_t sent = 0;
        while (sent < request_len) {
            int amount = esp_http_client_write(client, json + sent, request_len - sent);
            if (amount <= 0) {
                err = ESP_FAIL;
                break;
            }
            sent += amount;
        }
    }
    free(json);
    cJSON *reply = NULL;
    if (err == ESP_OK && esp_http_client_fetch_headers(client) >= 0) {
        *status = esp_http_client_get_status_code(client);
        size_t used = 0, cap = 4096;
        char *raw = malloc(cap);
        while (raw) {
            if (used + 2049 > cap) {
                size_t next = cap * 2;
                if (next > RESPONSE_LIMIT + 1)
                    next = RESPONSE_LIMIT + 1;
                if (next <= used + 1)
                    break;
                char *grown = realloc(raw, next);
                if (!grown)
                    break;
                raw = grown;
                cap = next;
            }
            int got = esp_http_client_read(client, raw + used, cap - used - 1);
            if (got < 0)
                break;
            if (got == 0) {
                if (esp_http_client_is_complete_data_received(client)) {
                    raw[used] = 0;
                    reply = cJSON_ParseWithLength(raw, used);
                }
                break;
            }
            used += got;
        }
        free(raw);
    }
    if (retry_after)
        *retry_after = response_headers.retry_after;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    if (*status == 401 && token && !strcmp(token, pb_settings.credential))
        pb_status("Device credential rejected; unlink locally and pair again");
    return reply;
}
cJSON *pb_api(const char *action, const char *token, const cJSON *body, int *status) {
    return api_request(action, token, body, status, NULL);
}
static const char *str(cJSON *j, const char *key) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(j, key);
    return cJSON_IsString(v) ? v->valuestring : "";
}
typedef struct {
    const atomic_bool *cancel;
    int http_status;
    bool invalid_reply, wrong_approval_url;
} link_context_t;
static bool link_cancelled(void *ctx) {
    return atomic_load(((link_context_t *)ctx)->cancel);
}
static uint64_t link_now(void *ctx) {
    (void)ctx;
    return esp_timer_get_time() / 1000;
}
static void link_wait(void *ctx, unsigned ms) {
    (void)ctx;
    vTaskDelay(pdMS_TO_TICKS(ms));
}
static bool copy_field(cJSON *json, const char *key, char *out, size_t capacity) {
    cJSON *value = cJSON_GetObjectItemCaseSensitive(json, key);
    if (!cJSON_IsString(value) || strlen(value->valuestring) >= capacity)
        return false;
    memcpy(out, value->valuestring, strlen(value->valuestring) + 1);
    return true;
}
static int link_start(void *ctx, pb_link_details_t *details) {
    link_context_t *context = ctx;
    cJSON *reply = pb_api("pair-start", NULL, NULL, &context->http_status);
    cJSON *expires = cJSON_GetObjectItemCaseSensitive(reply, "expires_in");
    cJSON *interval = cJSON_GetObjectItemCaseSensitive(reply, "poll_interval");
    bool valid = copy_field(reply, "code", details->code, sizeof(details->code)) &&
                 copy_field(reply, "verification_uri", details->uri, sizeof(details->uri)) &&
                 copy_field(reply, "polling_secret", details->secret, sizeof(details->secret)) &&
                 cJSON_IsNumber(expires) && expires->valuedouble >= 1 &&
                 expires->valuedouble <= 900 && expires->valuedouble == expires->valueint &&
                 cJSON_IsNumber(interval) && interval->valuedouble >= 1 &&
                 interval->valuedouble <= 900 && interval->valuedouble == interval->valueint;
    if (valid) {
        details->expires_in = expires->valueint;
        details->poll_interval = interval->valueint;
    }
    valid = valid && pb_link_details_valid(details);
    context->invalid_reply = context->http_status == 201 && !valid;
    context->wrong_approval_url =
        valid && !pb_link_uri_matches_base(details->uri, CONFIG_PB_BACKEND_URL);
    cJSON_Delete(reply);
    return valid && !context->wrong_approval_url ? context->http_status : 0;
}
static pb_link_poll_t link_poll(void *ctx, const char *secret) {
    link_context_t *context = ctx;
    pb_link_poll_t response = {0};
    cJSON *reply = api_request("pair-poll", secret, NULL, &response.status, &response.retry_after);
    context->http_status = response.status;
    response.linked = !strcmp(str(reply, "status"), "linked");
    if (response.status == 200)
        copy_field(reply, "device_credential", response.credential, sizeof(response.credential));
    if (response.status == 202 && (!reply || strcmp(str(reply, "status"), "pending")))
        response.status = -1;
    cJSON_Delete(reply);
    return response;
}
static bool link_save(void *ctx, const char *credential) {
    if (link_cancelled(ctx))
        return false;
    char previous[sizeof(pb_settings.credential)];
    memcpy(previous, pb_settings.credential, sizeof(previous));
    memcpy(pb_settings.credential, credential, sizeof(pb_settings.credential));
    if (pb_settings_save() == ESP_OK)
        return true;
    memcpy(pb_settings.credential, previous, sizeof(previous));
    return false;
}
static void link_show(void *ctx, pb_link_state_t state, const char *code, const char *uri,
                      unsigned remaining) {
    link_context_t *context = ctx;
    char text[1024], status[128];
    const char *title = "Link account";
    switch (state) {
    case PB_LINK_WAITING:
        title = "Waiting for approval";
        break;
    case PB_LINK_RETRYING:
        title = "Connection interrupted; retrying";
        break;
    case PB_LINK_SAVING:
        title = "Saving device credential";
        break;
    case PB_LINK_SAVE_FAILED:
        title = "Credential save failed; retrying";
        break;
    case PB_LINK_SUCCESS:
        pb_status("Account linked");
        pb_text("Device linked to your account.\n\nHold Talk to ask a question.");
        return;
    case PB_LINK_CANCELLED:
        pb_status("Linking cancelled");
        pb_text("No new credential was installed.\n\nSelect Link account to start again.");
        return;
    case PB_LINK_EXPIRED:
        pb_status("Pairing expired");
        pb_text("Select Link account to get a new code.");
        return;
    case PB_LINK_FAILED:
        if (context->wrong_approval_url) {
            pb_status("Backend approval URL is misconfigured");
            pb_text("Set base_url in the server's private config.php to:\n" CONFIG_PB_BACKEND_URL
                    "\n\nThen select Link account again.");
            return;
        }
        if (context->invalid_reply) {
            pb_status("Invalid pairing response from backend");
            pb_text("Check the backend deployment, then select Link account to retry.");
            return;
        }
        if (context->http_status)
            snprintf(status, sizeof(status), "Linking failed (HTTP %d)", context->http_status);
        else
            snprintf(status, sizeof(status), "Could not contact pairing service");
        pb_status(status);
        pb_text("Check Wi-Fi and the backend URL, then select Link account to retry.");
        return;
    }
    snprintf(status, sizeof(status), "%s (%us)", title, remaining);
    snprintf(text, sizeof(text),
             "Code: %s\n\nOn your phone, open:\n%s\n\nSign in, find My devices, enter this code "
             "and approve.\n\nTalk: cancel linking",
             code, uri);
    pb_text(text);
    pb_status(status);
}
esp_err_t pb_pair(const atomic_bool *cancel) {
    if (pb_settings.credential[0]) {
        pb_status("Already linked; unlink locally before linking again");
        return ESP_ERR_INVALID_STATE;
    }
    pb_status("Connecting to backend");
    pb_text("Preparing account link.\n\nTalk: cancel linking");
    if (atomic_load(cancel)) {
        link_context_t ctx = {.cancel = cancel};
        link_show(&ctx, PB_LINK_CANCELLED, "", "", 0);
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t connected = network_connect(cancel);
    link_context_t ctx = {.cancel = cancel};
    if (atomic_load(cancel)) {
        link_show(&ctx, PB_LINK_CANCELLED, "", "", 0);
        return ESP_ERR_INVALID_STATE;
    }
    if (connected != ESP_OK) {
        pb_status("Wi-Fi unavailable");
        pb_text("Use Wi-Fi setup first, then select Link account.\n\nClock synchronization must "
                "also succeed for HTTPS.");
        return connected;
    }
    pb_link_io_t io = {.context = &ctx,
                       .now_ms = link_now,
                       .wait_ms = link_wait,
                       .cancelled = link_cancelled,
                       .start = link_start,
                       .poll = link_poll,
                       .save = link_save,
                       .show = link_show};
    return pb_link_run(&io) == PB_LINK_SUCCESS ? ESP_OK : ESP_FAIL;
}
