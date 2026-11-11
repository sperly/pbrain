#include "pb.h"
#include "esp_partition.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

pb_settings_t pb_settings = {.volume = 15, .timeout = CONFIG_PB_IDLE_SECONDS};
#include "pb_journal.h"
static int flash_read(void *p, size_t offset, void *data, size_t length) {
    return esp_partition_read(p, offset, data, length);
}
static int flash_write(void *p, size_t offset, const void *data, size_t length) {
    return esp_partition_write(p, offset, data, length);
}
static int flash_erase(void *p, size_t offset, size_t length) {
    return esp_partition_erase_range(p, offset, length);
}
static pb_journal_t journal(const esp_partition_t *p) {
    return (pb_journal_t){.context = (void *)p,
                          .size = p->size,
                          .read = flash_read,
                          .write = flash_write,
                          .erase = flash_erase};
}
esp_err_t pb_blob_load(const char *label, void **data, size_t *length) {
    *data = NULL;
    *length = 0;
    const esp_partition_t *p =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, label);
    if (!p)
        return ESP_ERR_NOT_FOUND;
    pb_journal_t j = journal(p);
    if (pb_journal_info(&j, length) != PB_JOURNAL_OK)
        return ESP_ERR_NOT_FOUND;
    void *buf = heap_caps_malloc(*length + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf)
        return ESP_ERR_NO_MEM;
    if (pb_journal_read(&j, buf, *length, length) != PB_JOURNAL_OK) {
        free(buf);
        return ESP_FAIL;
    }
    ((char *)buf)[*length] = 0;
    *data = buf;
    return ESP_OK;
}
esp_err_t pb_blob_save(const char *label, const void *data, size_t length) {
    const esp_partition_t *p =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, label);
    if (!p)
        return ESP_ERR_NOT_FOUND;
    pb_journal_t j = journal(p);
    int result = pb_journal_write(&j, data, length);
    return result == PB_JOURNAL_OK        ? ESP_OK
           : result == PB_JOURNAL_INVALID ? ESP_ERR_INVALID_SIZE
                                          : ESP_FAIL;
}
esp_err_t pb_pending_save(cJSON *meta, const int16_t *pcm, size_t samples) {
    if (samples > PB_MAX_SAMPLES)
        return ESP_ERR_INVALID_SIZE;
    char *json = cJSON_PrintUnformatted(meta);
    if (!json)
        return ESP_ERR_NO_MEM;
    uint32_t n = strlen(json);
    if (n > PB_METADATA_MAX) {
        free(json);
        return ESP_ERR_INVALID_SIZE;
    }
    size_t length = sizeof(n) + n + samples * 2;
    uint8_t *buf = heap_caps_malloc(length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf) {
        free(json);
        return ESP_ERR_NO_MEM;
    }
    memcpy(buf, &n, sizeof(n));
    memcpy(buf + sizeof(n), json, n);
    if (samples)
        memcpy(buf + sizeof(n) + n, pcm, samples * 2);
    esp_err_t err = pb_blob_save("pending", buf, length);
    free(buf);
    free(json);
    return err;
}
esp_err_t pb_pending_load(cJSON **meta, int16_t **pcm, size_t *samples) {
    *meta = NULL;
    *pcm = NULL;
    *samples = 0;
    uint8_t *buf;
    size_t length;
    esp_err_t err = pb_blob_load("pending", (void **)&buf, &length);
    if (err != ESP_OK)
        return err;
    uint32_t n = 0;
    if (length >= sizeof(n))
        memcpy(&n, buf, sizeof(n));
    if (n == 0 || n > PB_METADATA_MAX || length < sizeof(n) + n || (length - sizeof(n) - n) % 2 ||
        length - sizeof(n) - n > PB_MAX_PCM) {
        free(buf);
        return ESP_ERR_INVALID_SIZE;
    }
    *meta = cJSON_ParseWithLength((char *)buf + sizeof(n), n);
    *samples = (length - sizeof(n) - n) / 2;
    if (*samples) {
        *pcm = heap_caps_malloc(*samples * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (*pcm)
            memcpy(*pcm, buf + sizeof(n) + n, *samples * 2);
    }
    free(buf);
    if (!cJSON_IsObject(*meta) || (*samples && !*pcm)) {
        cJSON_Delete(*meta);
        free(*pcm);
        *meta = NULL;
        *pcm = NULL;
        return ESP_FAIL;
    }
    return ESP_OK;
}
esp_err_t pb_storage_init(void) {
    esp_err_t err = nvs_flash_init();
    /* Never erase credentials automatically after an NVS error. */
    if (err != ESP_OK)
        return err;
    nvs_handle_t h;
    err = nvs_open("pocketbrain", NVS_READWRITE, &h);
    if (err != ESP_OK)
        return err;
    size_t n = sizeof(pb_settings.credential);
    if (nvs_get_str(h, "credential", pb_settings.credential, &n) != ESP_OK)
        pb_settings.credential[0] = 0;
    uint8_t muted;
    uint32_t value;
    if (nvs_get_u8(h, "muted", &muted) == ESP_OK)
        pb_settings.muted = muted;
    if (nvs_get_u32(h, "volume", &value) == ESP_OK && value <= 100)
        pb_settings.volume = value;
    if (nvs_get_u32(h, "timeout", &value) == ESP_OK && value <= 3600)
        pb_settings.timeout = value;
    nvs_close(h);
    return ESP_OK;
}
esp_err_t pb_settings_save(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open("pocketbrain", NVS_READWRITE, &h);
    if (err != ESP_OK)
        return err;
    err = nvs_set_str(h, "credential", pb_settings.credential);
    if (err == ESP_OK)
        err = nvs_set_u8(h, "muted", pb_settings.muted);
    if (err == ESP_OK)
        err = nvs_set_u32(h, "volume", pb_settings.volume);
    if (err == ESP_OK)
        err = nvs_set_u32(h, "timeout", pb_settings.timeout);
    if (err == ESP_OK)
        err = nvs_commit(h);
    nvs_close(h);
    return err;
}
void pb_uuid(char out[37]) {
    uint8_t b[16];
    esp_fill_random(b, sizeof(b));
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0],
             b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13],
             b[14], b[15]);
}
