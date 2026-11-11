<?php
// Test-only transport. No requests leave the container, and no real keys are used.
// These PHP functions are disabled and replaced only in the test API process.
function curl_init(string $url): object
{
    if (!in_array(parse_url($url, PHP_URL_HOST), ['api.openai.com', 'geocoding-api.open-meteo.com', 'api.open-meteo.com'], true)) {
        throw new RuntimeException('Unexpected upstream URL');
    }
    return (object) ['options' => [], 'status' => 200, 'url' => $url];
}
function curl_setopt_array(object $handle, array $options): bool
{
    $handle->options = $options;
    return true;
}
function curl_exec(object $handle): string|false
{
    $key = '';
    foreach ($handle->options[CURLOPT_HTTPHEADER] as $header) {
        if (str_starts_with($header, 'Authorization: Bearer ')) {
            $key = substr($header, strlen('Authorization: Bearer '));
        }
    }
    $payload = json_decode($handle->options[CURLOPT_POSTFIELDS] ?? '{}', true);
    if (str_contains($key, 'rejected')) {
        $handle->status = 401;
        $body = ['error' => ['message' => 'Rejected secret ' . $key]];
    } elseif (str_contains($key, 'quota')) {
        $handle->status = 429;
        $body = ['error' => ['message' => 'Quota secret ' . $key]];
    } elseif (str_contains($handle->url, 'geocoding-api.open-meteo.com')) {
        parse_str(parse_url($handle->url, PHP_URL_QUERY), $params);
        $body = ['results' => [['name' => 'Stockholm', 'country' => 'Sweden', 'admin1' => 'Stockholm',
                              'latitude' => 59.33, 'longitude' => 18.06]]];
        if ($params['name'] === 'Unknown') {
            $body = [];
        }
    } elseif (str_contains($handle->url, 'api.open-meteo.com')) {
        $body = ['timezone' => 'Europe/Stockholm',
                 'current' => ['time' => '2026-11-11T12:00', 'temperature_2m' => 6, 'weather_code' => 3],
                 'current_units' => ['temperature_2m' => '°C'],
                 'daily' => ['time' => ['2026-11-11'], 'temperature_2m_max' => [7]],
                 'daily_units' => ['temperature_2m_max' => '°C']];
    } elseif (str_ends_with($handle->url, '/responses')) {
        if (($payload['tool_choice'] ?? '') !== 'required' || ($payload['store'] ?? true)
            || ($payload['tools'][0]['type'] ?? '') !== 'web_search') {
            throw new RuntimeException('Search was not required or storage was enabled');
        }
        $body = ['status' => 'completed', 'output' => [
            ['type' => 'web_search_call', 'status' => 'completed'],
            ['type' => 'message', 'content' => [['type' => 'output_text', 'text' => 'Verified current information.',
             'annotations' => [['type' => 'url_citation', 'title' => 'Example source', 'url' => 'https://example.org/fact']]]]],
        ]];
        if ($payload['input'] === 'no sources') {
            $body['output'][1]['content'][0]['annotations'] = [];
        }
        if ($payload['input'] === 'incomplete') {
            $body['status'] = 'incomplete';
        }
        // A test-only fingerprint proves which key was selected, never the key itself.
        $body['output'][1]['content'][0]['text'] .= ' key-id:' . substr(hash('sha256', $key), 0, 12);
    } else {
        $body = ['value' => 'ephemeral-test-' . substr(hash('sha256', $key), 0, 12), 'expires_at' => time() + 60];
    }
    $json = json_encode($body);
    if (isset($handle->options[CURLOPT_WRITEFUNCTION])) {
        return ($handle->options[CURLOPT_WRITEFUNCTION])($handle, $json) === strlen($json) ? '' : false;
    }
    return $json;
}
function curl_getinfo(object $handle, int $option): int
{
    return $handle->status;
}
function curl_errno(object $handle): int
{
    return 0;
}
