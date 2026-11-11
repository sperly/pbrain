idf_component_register(SRCS "app_main.c" "audio.c" "storage.c" "network.c" "realtime.c" "display.c"
    INCLUDE_DIRS "."
    REQUIRES pb_core esp_driver_gpio esp_driver_i2s esp_wifi esp_netif esp_event
             nvs_flash esp_http_client esp-tls mbedtls json esp_timer esp_partition
             esp_hw_support wifi_provisioning bt esp_websocket_client esp_driver_spi u8g2)
