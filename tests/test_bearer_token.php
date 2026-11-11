<?php
declare(strict_types=1);

// Standalone: php tests/test_bearer_token.php (no database or private config).
$testHeaders = [];
if (!function_exists('getallheaders')) {
    function getallheaders(): array
    {
        return $GLOBALS['testHeaders'];
    }
}
require dirname(__DIR__) . '/backend/app/bootstrap.php';

$token = str_repeat('a', 64);
$cases = [
    'direct header' => [['HTTP_AUTHORIZATION' => 'Bearer ' . $token], [], $token],
    'rewrite header' => [['REDIRECT_HTTP_AUTHORIZATION' => 'Bearer ' . $token], [], $token],
    'native headers' => [[], ['Authorization' => 'Bearer ' . $token], $token],
    'case insensitive header name' => [[], ['authorization' => 'Bearer ' . $token], $token],
    'missing header' => [[], [], ''],
    'invalid credential' => [['HTTP_AUTHORIZATION' => 'Bearer invalid'], [], ''],
    'wrong scheme' => [['HTTP_AUTHORIZATION' => 'Basic ' . $token], [], ''],
    'duplicate credentials' => [['HTTP_AUTHORIZATION' => 'Bearer ' . $token . ', Bearer ' . $token], [], ''],
    'no fallback for explicit invalid header' => [
        ['HTTP_AUTHORIZATION' => 'invalid', 'REDIRECT_HTTP_AUTHORIZATION' => 'Bearer ' . $token], [], ''],
    'no header injection' => [['HTTP_AUTHORIZATION' => 'Bearer ' . $token . "\r\nX-Test: value"], [], ''],
];
$_GET = ['token' => $token];
$_POST = ['token' => $token];
foreach ($cases as $name => [$server, $headers, $expected]) {
    $_SERVER = $server;
    $testHeaders = $headers;
    if (bearerToken() !== $expected) {
        throw new RuntimeException('Failed: ' . $name);
    }
}
echo count($cases) . " bearer-header checks passed\n";
