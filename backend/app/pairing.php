<?php
declare(strict_types=1);

const PAIR_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';

function createPairing(): array
{
    for ($attempt = 0; $attempt < 3; $attempt++) {
        $code = '';
        for ($digit = 0; $digit < 8; $digit++) {
            $code .= PAIR_ALPHABET[random_int(0, strlen(PAIR_ALPHABET) - 1)];
        }
        $secret = randomToken();
        try {
            query(
                'INSERT INTO device_pairings (code_hash, polling_secret_hash, expires_at)
                 VALUES (UNHEX(?), UNHEX(?), CURRENT_TIMESTAMP(6) + INTERVAL 5 MINUTE)',
                [appMac('pair-code', $code), tokenHash($secret)]
            );
            return [
                'code' => substr($code, 0, 4) . '-' . substr($code, 4),
                'polling_secret' => $secret,
                'expires_in' => 300,
                'poll_interval' => 5,
                'verification_uri' => config()['base_url'] . '/index.php#devices',
            ];
        } catch (PDOException $error) {
            if (!duplicateKey($error)) {
                throw $error;
            }
        }
    }
    throw new RuntimeException('Could not generate a unique pairing code');
}

function approvePairing(string $userId, string $code): bool
{
    $code = strtoupper(str_replace(['-', ' '], '', trim($code)));
    if (strlen($code) !== 8 || strspn($code, PAIR_ALPHABET) !== 8) {
        return false;
    }
    return query(
        'UPDATE device_pairings SET approved_by_user_id = ?, approved_at = CURRENT_TIMESTAMP(6)
         WHERE code_hash = UNHEX(?) AND approved_by_user_id IS NULL AND expires_at > CURRENT_TIMESTAMP(6)',
        [$userId, appMac('pair-code', $code)]
    )->rowCount() === 1;
}

function pollPairing(string $secret): array
{
    return transaction(function () use ($secret): array {
        $pair = query(
            'SELECT id, approved_by_user_id, device_id FROM device_pairings
             WHERE polling_secret_hash = UNHEX(?) AND expires_at > CURRENT_TIMESTAMP(6) FOR UPDATE',
            [tokenHash($secret)]
        )->fetch();
        if ($pair === false) {
            return ['status' => 'expired_or_unknown'];
        }
        if ($pair['approved_by_user_id'] === null) {
            return ['status' => 'pending'];
        }

        $credential = appMac('pair-credential', $secret);
        if ($pair['device_id'] !== null) {
            // A lost HTTP response can be retried until the original expiry.
            $device = deviceByCredential($credential);
            if ($device === false || (string) $device['id'] !== (string) $pair['device_id']) {
                return ['status' => 'expired_or_unknown'];
            }
            return ['status' => 'linked', 'device_credential' => $credential];
        }

        $owner = query(
            'SELECT id FROM users WHERE id = ? AND disabled_at IS NULL FOR UPDATE',
            [$pair['approved_by_user_id']]
        )->fetchColumn();
        if ($owner === false) {
            return ['status' => 'expired_or_unknown'];
        }

        query(
            "INSERT INTO devices (user_id, display_name, credential_hash) VALUES (?, 'PocketBrain', UNHEX(?))",
            [$owner, tokenHash($credential)]
        );
        $deviceId = db()->lastInsertId();
        $updated = query(
            'UPDATE device_pairings SET device_id = ?, redeemed_at = CURRENT_TIMESTAMP(6)
             WHERE id = ? AND expires_at > CURRENT_TIMESTAMP(6)',
            [$deviceId, $pair['id']]
        )->rowCount();
        if ($updated !== 1) {
            throw new DomainException('Pairing expired during redemption');
        }
        return ['status' => 'linked', 'device_credential' => $credential];
    });
}
