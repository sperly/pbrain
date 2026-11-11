<?php
declare(strict_types=1);

function issueRealtimeSecret(): array
{
    $settings = config();
    $apiKey = $settings['openai_api_key'] ?? '';
    $model = $settings['openai_realtime_model'] ?? 'gpt-realtime-2.1';
    if ($apiKey === '' || !preg_match('/\A[A-Za-z0-9_.-]+\z/', $model)
        || strpbrk($apiKey, "\r\n") !== false || !extension_loaded('curl')) {
        return [503, ['error' => 'realtime_not_configured']];
    }

    $handle = curl_init('https://api.openai.com/v1/realtime/client_secrets');
    curl_setopt_array($handle, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_TIMEOUT => 12,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $apiKey, 'Content-Type: application/json'],
        CURLOPT_POSTFIELDS => json_encode([
            'expires_after' => ['anchor' => 'created_at', 'seconds' => 60],
            'session' => ['type' => 'realtime', 'model' => $model],
        ], JSON_THROW_ON_ERROR),
    ]);
    $raw = curl_exec($handle);
    $status = (int) curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
    if ($raw === false || $status < 200 || $status >= 300) {
        error_log('PocketBrain Realtime issuance failed, upstream HTTP ' . $status . ', cURL ' . curl_errno($handle));
        return [502, ['error' => 'realtime_upstream_failed']];
    }

    $body = json_decode($raw, true);
    if (!is_string($body['value'] ?? null) || $body['value'] === '' || !is_int($body['expires_at'] ?? null)) {
        return [502, ['error' => 'realtime_invalid_upstream_response']];
    }

    return [200, [
        'value' => $body['value'],
        'expires_at' => $body['expires_at'],
        'model' => $model,
    ]];
}
