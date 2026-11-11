<?php
declare(strict_types=1);

function validOpenaiKey(string $key): bool
{
    return strlen($key) <= 1024 && preg_match('/\Ask-[A-Za-z0-9_-]{16,1021}\z/D', $key) === 1;
}

function openaiEncryptionKey(): string
{
    return hash_hkdf('sha256', config()['app_key'], 32, 'PocketBrain user OpenAI keys v1');
}

function encryptOpenaiKey(string $owner, string $key): string
{
    $nonce = random_bytes(12);
    $tag = '';
    $encrypted = openssl_encrypt($key, 'aes-256-gcm', openaiEncryptionKey(), OPENSSL_RAW_DATA,
                                 $nonce, $tag, 'PocketBrain OpenAI key v1:' . $owner, 16);
    if ($encrypted === false) {
        throw new RuntimeException('Could not encrypt API key');
    }
    return "\x01" . $nonce . $tag . $encrypted;
}

function decryptOpenaiKey(string $owner, string $encrypted): string
{
    if (strlen($encrypted) < 30 || $encrypted[0] !== "\x01") {
        throw new RuntimeException('Invalid encrypted API key');
    }
    $key = openssl_decrypt(substr($encrypted, 29), 'aes-256-gcm', openaiEncryptionKey(), OPENSSL_RAW_DATA,
                           substr($encrypted, 1, 12), substr($encrypted, 13, 16),
                           'PocketBrain OpenAI key v1:' . $owner);
    if ($key === false || !validOpenaiKey($key)) {
        throw new RuntimeException('Could not decrypt API key');
    }
    return $key;
}

function saveUserOpenaiKey(string $owner, string $key): void
{
    if (!validOpenaiKey($key)) {
        throw new InvalidArgumentException('Invalid API key format');
    }
    query('INSERT INTO user_openai_keys (user_id, encrypted_key) VALUES (?, ?)
           ON DUPLICATE KEY UPDATE encrypted_key = VALUES(encrypted_key), updated_at = CURRENT_TIMESTAMP(6)',
          [$owner, encryptOpenaiKey($owner, $key)]);
}

function removeUserOpenaiKey(string $owner): void
{
    query('DELETE FROM user_openai_keys WHERE user_id = ?', [$owner]);
}

function userOpenaiKeyStatus(string $owner): array|false
{
    // Status only: never return the stored secret to the dashboard.
    return query('SELECT updated_at FROM user_openai_keys WHERE user_id = ?', [$owner])->fetch();
}

function openaiKeyForUser(string $owner): ?string
{
    $encrypted = query('SELECT encrypted_key FROM user_openai_keys WHERE user_id = ?', [$owner])->fetchColumn();
    if ($encrypted !== false) {
        // Fail closed if corrupt: never switch the user's billing source on an error.
        return decryptOpenaiKey($owner, $encrypted);
    }
    $settings = config();
    if (($settings['allow_shared_openai_key'] ?? false) === true) {
        $key = $settings['openai_api_key'] ?? '';
        return $key !== '' ? $key : null;
    }
    return null;
}
