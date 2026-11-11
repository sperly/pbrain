<?php
// Test-only TLS terminator stand-in. Never deploy this router.
$_SERVER['HTTPS'] = 'on';
if (getenv('PB_MOCK_REALTIME') === '1') {
    require_once '/mock_realtime.php';
}
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if ($path === '/style.css') {
    return false;
}
require $path === '/index.php' ? '/app/public_html/index.php' : '/app/public_html/api.php';
