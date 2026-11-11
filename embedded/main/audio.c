#include "pb.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>

static i2s_chan_handle_t rx, tx;
static SemaphoreHandle_t capture_lock, playback_lock;
static int16_t *capture, *ring;
static size_t captured, head, used;
static bool capture_enabled;
static atomic_bool audible;
static pb_decimator_t decimator;
#define BLOCK_FRAMES 240
static void amplifier(bool on) {
    if (CONFIG_PB_AMP_SD_PIN >= 0)
        gpio_set_level(CONFIG_PB_AMP_SD_PIN, on);
}
static void audio_task(void *arg) {
    (void)arg;
    int32_t input[BLOCK_FRAMES * 2], output[BLOCK_FRAMES * 2];
    int16_t mono[BLOCK_FRAMES / 2], play[BLOCK_FRAMES / 2];
    for (;;) {
        size_t bytes = 0;
        esp_err_t err = i2s_channel_read(rx, input, sizeof(input), &bytes, 50);
        if (err == ESP_OK && bytes) {
            xSemaphoreTake(capture_lock, portMAX_DELAY);
            if (capture_enabled) {
                size_t n = pb_pcm48_to_24(&decimator, input, bytes / 8, mono, CONFIG_PB_MIC_SHIFT);
                if (n > PB_MAX_SAMPLES - captured)
                    n = PB_MAX_SAMPLES - captured;
                memcpy(capture + captured, mono, n * 2);
                captured += n;
                if (captured == PB_MAX_SAMPLES)
                    capture_enabled = false;
            }
            xSemaphoreGive(capture_lock);
        }
        xSemaphoreTake(playback_lock, portMAX_DELAY);
        size_t n = used < BLOCK_FRAMES / 2 ? used : BLOCK_FRAMES / 2;
        for (size_t i = 0; i < n; ++i)
            play[i] = ring[(head + i) % (PB_PLAYBACK_BYTES / 2)];
        head = (head + n) % (PB_PLAYBACK_BYTES / 2);
        used -= n;
        memset(play + n, 0, sizeof(play) - n * 2);
        pb_pcm24_to_48(play, BLOCK_FRAMES / 2, output, pb_settings.volume);
        if (atomic_load(&audible)) {
            amplifier(n > 0);
            size_t written = 0;
            i2s_channel_write(tx, output, sizeof(output), &written, 20);
        }
        xSemaphoreGive(playback_lock);
    }
}
esp_err_t pb_audio_init(void) {
    capture_lock = xSemaphoreCreateMutex();
    playback_lock = xSemaphoreCreateMutex();
    ring = heap_caps_malloc(PB_PLAYBACK_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!capture_lock || !playback_lock || !ring)
        return ESP_ERR_NO_MEM;
    if (CONFIG_PB_AMP_SD_PIN >= 0) {
        gpio_set_direction(CONFIG_PB_AMP_SD_PIN, GPIO_MODE_OUTPUT);
        amplifier(false);
    }
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.dma_desc_num = 4;
    chan.dma_frame_num = BLOCK_FRAMES;
    chan.auto_clear = true;
    esp_err_t err = i2s_new_channel(&chan, &tx, &rx);
    if (err != ESP_OK)
        return err;
    i2s_std_config_t cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(48000),
        .slot_cfg =
            I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED,
                     .bclk = CONFIG_PB_BCLK_PIN,
                     .ws = CONFIG_PB_WS_PIN,
                     .dout = CONFIG_PB_SPEAKER_PIN,
                     .din = CONFIG_PB_MIC_PIN},
    };
    if ((err = i2s_channel_init_std_mode(tx, &cfg)) != ESP_OK ||
        (err = i2s_channel_init_std_mode(rx, &cfg)) != ESP_OK ||
        (err = i2s_channel_enable(tx)) != ESP_OK || (err = i2s_channel_enable(rx)) != ESP_OK)
        return err;
    return xTaskCreate(audio_task, "pb_audio", 8192, NULL, 6, NULL) == pdPASS ? ESP_OK
                                                                              : ESP_ERR_NO_MEM;
}
esp_err_t pb_capture_start(int16_t *buffer) {
    if (!buffer)
        return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(capture_lock, portMAX_DELAY);
    capture = buffer;
    captured = 0;
    decimator = (pb_decimator_t){0};
    capture_enabled = true;
    xSemaphoreGive(capture_lock);
    return ESP_OK;
}
size_t pb_capture_stop(void) {
    xSemaphoreTake(capture_lock, portMAX_DELAY);
    capture_enabled = false;
    size_t n = captured;
    xSemaphoreGive(capture_lock);
    return n;
}
size_t pb_capture_samples(void) {
    xSemaphoreTake(capture_lock, portMAX_DELAY);
    size_t n = captured;
    xSemaphoreGive(capture_lock);
    return n;
}
esp_err_t pb_play(const void *pcm, size_t bytes) {
    if (bytes % 2)
        return ESP_ERR_INVALID_SIZE;
    const int16_t *samples = pcm;
    size_t left = bytes / 2;
    while (left) {
        if (!atomic_load(&audible))
            return ESP_ERR_INVALID_STATE;
        xSemaphoreTake(playback_lock, portMAX_DELAY);
        if (!atomic_load(&audible)) {
            xSemaphoreGive(playback_lock);
            return ESP_ERR_INVALID_STATE;
        }
        size_t n = PB_PLAYBACK_BYTES / 2 - used;
        if (n > left)
            n = left;
        for (size_t i = 0; i < n; ++i)
            ring[(head + used + i) % (PB_PLAYBACK_BYTES / 2)] = samples[i];
        used += n;
        xSemaphoreGive(playback_lock);
        samples += n;
        left -= n;
        if (left)
            vTaskDelay(pdMS_TO_TICKS(5));
    }
    return ESP_OK;
}
void pb_play_begin(void) {
    atomic_store(&audible, true);
}
void pb_play_stop(void) {
    amplifier(false);
    atomic_store(&audible, false);
    xSemaphoreTake(playback_lock, portMAX_DELAY);
    used = head = 0;
    i2s_channel_disable(tx);
    i2s_channel_enable(tx);
    xSemaphoreGive(playback_lock);
}
bool pb_playing(void) {
    xSemaphoreTake(playback_lock, portMAX_DELAY);
    bool result = used != 0;
    xSemaphoreGive(playback_lock);
    return result;
}
