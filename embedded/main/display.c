#include "pb.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_rom_sys.h"
#include "u8g2.h"
#include <string.h>

#if CONFIG_PB_OLED_ENABLED
static u8g2_t oled;
static spi_device_handle_t spi;
static uint8_t byte_cb(u8x8_t *display, uint8_t message, uint8_t arg, void *data) {
    (void)display;
    switch (message) {
    case U8X8_MSG_BYTE_INIT:
        return 1;
    case U8X8_MSG_BYTE_START_TRANSFER:
        gpio_set_level(CONFIG_PB_OLED_CS_PIN, 0);
        return 1;
    case U8X8_MSG_BYTE_END_TRANSFER:
        gpio_set_level(CONFIG_PB_OLED_CS_PIN, 1);
        return 1;
    case U8X8_MSG_BYTE_SET_DC:
        gpio_set_level(CONFIG_PB_OLED_DC_PIN, arg);
        return 1;
    case U8X8_MSG_BYTE_SEND: {
        spi_transaction_t transaction = {.length = arg * 8u, .tx_buffer = data};
        return spi_device_polling_transmit(spi, &transaction) == ESP_OK;
    }
    default:
        return 0;
    }
}
static uint8_t gpio_cb(u8x8_t *display, uint8_t message, uint8_t arg, void *data) {
    (void)display;
    (void)data;
    switch (message) {
    case U8X8_MSG_GPIO_AND_DELAY_INIT:
        return 1;
    case U8X8_MSG_DELAY_MILLI:
        vTaskDelay(pdMS_TO_TICKS(arg) + 1);
        return 1;
    case U8X8_MSG_DELAY_10MICRO:
        esp_rom_delay_us(arg * 10);
        return 1;
    case U8X8_MSG_DELAY_NANO:
        esp_rom_delay_us(1);
        return 1;
    case U8X8_MSG_GPIO_RESET:
        gpio_set_level(CONFIG_PB_OLED_RESET_PIN, arg);
        return 1;
    default:
        return 1;
    }
}
static const char *line(const char *p, char out[96]) {
    return pb_wrap_line(p, 21, out, 96);
}
#endif
void pb_display_init(void) {
#if CONFIG_PB_OLED_ENABLED
    gpio_config_t gpio = {.pin_bit_mask = (1ULL << CONFIG_PB_OLED_CS_PIN) |
                                          (1ULL << CONFIG_PB_OLED_DC_PIN) |
                                          (1ULL << CONFIG_PB_OLED_RESET_PIN),
                          .mode = GPIO_MODE_OUTPUT};
    ESP_ERROR_CHECK(gpio_config(&gpio));
    gpio_set_level(CONFIG_PB_OLED_CS_PIN, 1);
    spi_bus_config_t bus = {.mosi_io_num = CONFIG_PB_OLED_MOSI_PIN,
                            .miso_io_num = -1,
                            .sclk_io_num = CONFIG_PB_OLED_CLK_PIN,
                            .quadwp_io_num = -1,
                            .quadhd_io_num = -1,
                            .max_transfer_sz = 4096};
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));
    spi_device_interface_config_t cfg = {
        .clock_speed_hz = 4000000, .mode = 0, .spics_io_num = -1, .queue_size = 1};
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &cfg, &spi));
    u8g2_Setup_ssd1363_256x128_f(&oled, U8G2_R1, byte_cb, gpio_cb);
    u8g2_InitDisplay(&oled);
    u8g2_SetPowerSave(&oled, 0);
    u8g2_SetFont(&oled, u8g2_font_6x10_tf);
#endif
}
void pb_display_render(const char *status, const char *text, int scroll, unsigned remaining) {
#if CONFIG_PB_OLED_ENABLED
    u8g2_ClearBuffer(&oled);
    char chunk[96];
    const char *p = status;
    for (unsigned row = 0; *p && row < 3; ++row) {
        p = line(p, chunk);
        u8g2_DrawUTF8(&oled, 0, 9 + row * 10, chunk);
    }
    u8g2_DrawHLine(&oled, 0, 32, 128);
    p = text;
    while (*p && scroll-- > 0)
        p = line(p, chunk);
    for (unsigned row = 0; *p && row < 21; ++row) {
        p = line(p, chunk);
        u8g2_DrawUTF8(&oled, 0, 44 + row * 10, chunk);
    }
    if (remaining <= 30000) {
        u8g2_DrawFrame(&oled, 0, 250, 128, 6);
        u8g2_DrawBox(&oled, 1, 251, 126u * remaining / 30000u, 4);
    }
    u8g2_SendBuffer(&oled);
#else
    (void)status;
    (void)text;
    (void)scroll;
    (void)remaining;
#endif
}
void pb_display_sleep(void) {
#if CONFIG_PB_OLED_ENABLED
    u8g2_SetPowerSave(&oled, 1);
#endif
}
