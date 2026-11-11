FROM php:8.4-cli
RUN docker-php-ext-install pdo_mysql
WORKDIR /app
COPY backend /app
COPY router.php /router.php
COPY mock_realtime.php /mock_realtime.php
CMD ["php", "-S", "0.0.0.0:8080", "-t", "/app/public_html", "/router.php"]
