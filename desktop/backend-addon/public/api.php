<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';
require dirname(__DIR__) . '/app/pairing.php';

header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function jsonResponse(int $status, array $body): never
{
    http_response_code($status);
    echo json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
    exit;
}

function bearerToken(): string
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    return preg_match('/\ABearer ([a-f0-9]{64})\z/iD', $header, $match) === 1 ? $match[1] : '';
}

function requireMethod(string $method): void
{
    if ($_SERVER['REQUEST_METHOD'] !== $method) {
        header('Allow: ' . $method);
        jsonResponse(405, ['error' => 'method_not_allowed']);
    }
}

function apiLimit(string $scope, string $subject, int $limit, int $seconds): void
{
    if (!rateAllowed($scope, $subject, $limit, $seconds)) {
        header('Retry-After: ' . ($seconds - time() % $seconds));
        jsonResponse(429, ['error' => 'rate_limited']);
    }
}

if (!isHttps()) {
    jsonResponse(400, ['error' => 'https_required']);
}

try {
    switch ($_GET['action'] ?? '') {
        case 'pair-start':
            requireMethod('POST');
            apiLimit('pair-start-ip', clientIp(), 10, 300);
            jsonResponse(201, createPairing());

        case 'pair-poll':
            requireMethod('POST');
            apiLimit('pair-poll-ip', clientIp(), 120, 60);
            $secret = bearerToken();
            if (!validToken($secret)) {
                jsonResponse(401, ['error' => 'invalid_polling_secret']);
            }
            apiLimit('pair-poll-secret', $secret, 15, 60);
            try {
                $result = pollPairing($secret);
            } catch (DomainException) {
                $result = ['status' => 'expired_or_unknown'];
            }
            $status = match ($result['status']) {
                'pending' => 202,
                'linked' => 200,
                default => 404,
            };
            jsonResponse($status, $result);

        case 'realtime-secret':
            requireMethod('POST');
            apiLimit('realtime-ip', clientIp(), 60, 60);
            $device = deviceByCredential(bearerToken());
            if ($device === false) {
                header('WWW-Authenticate: Bearer realm="PocketBrain"');
                jsonResponse(401, ['error' => 'invalid_device_credential']);
            }
            $deviceId = (string) $device['id'];
            apiLimit('realtime-device', $deviceId, 12, 60);
            apiLimit('realtime-owner', (string) $device['user_id'], 24, 60);
            require dirname(__DIR__) . '/app/realtime.php';
            [$status, $body] = issueRealtimeSecret();
            if ($status === 200) {
                recordDeviceSeen($deviceId);
            }
            jsonResponse($status, $body);

        case 'device':
            requireMethod('GET');
            apiLimit('device-status-ip', clientIp(), 120, 60);
            $device = deviceByCredential(bearerToken());
            if ($device === false) {
                header('WWW-Authenticate: Bearer realm="PocketBrain"');
                jsonResponse(401, ['error' => 'invalid_device_credential']);
            }
            recordDeviceSeen((string) $device['id']);
            jsonResponse(200, ['id' => (string) $device['id'], 'name' => $device['display_name']]);

        default:
            jsonResponse(404, ['error' => 'not_found']);
    }
} catch (Throwable $error) {
    error_log('PocketBrain API error: ' . get_class($error) . ' ' . $error->getCode());
    jsonResponse(500, ['error' => 'server_error']);
}
