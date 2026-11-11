<?php
declare(strict_types=1);

function authenticate(string $email, string $password): array|false
{
    $user = query(
        'SELECT id, password_hash FROM users WHERE email = ? AND disabled_at IS NULL',
        [$email]
    )->fetch();

    // A missing or disabled account still takes a bcrypt verification.
    $hash = $user['password_hash'] ?? '$2y$12$ArPz/tdDhT8a5B7vv4oFjuOhq5XhAmmAb6mN44M2ACdZzTQAK44Dy';
    $usable = strlen($password) <= 72 && !str_contains($password, "\0");
    $verified = password_verify($usable ? $password : '', $hash);
    return $usable && $verified ? $user : false;
}

function redeemInvite(string $digest, string $email, string $password): bool
{
    $passwordHash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
    try {
        return transaction(function () use ($digest, $email, $passwordHash): bool {
            $inviteId = query(
                'SELECT id FROM invitations
                 WHERE token_hash = UNHEX(?) AND revoked_at IS NULL AND redeemed_at IS NULL
                   AND expires_at > CURRENT_TIMESTAMP(6) FOR UPDATE',
                [$digest]
            )->fetchColumn();
            if ($inviteId === false) {
                return false;
            }

            query('INSERT INTO users (email, password_hash) VALUES (?, ?)', [$email, $passwordHash]);
            $userId = db()->lastInsertId();
            $updated = query(
                'UPDATE invitations SET redeemed_by_user_id = ?, redeemed_at = CURRENT_TIMESTAMP(6)
                 WHERE id = ? AND expires_at > CURRENT_TIMESTAMP(6)',
                [$userId, $inviteId]
            )->rowCount();
            if ($updated !== 1) {
                throw new DomainException('Invitation expired during signup');
            }
            return true;
        });
    } catch (DomainException) {
        return false;
    } catch (PDOException $error) {
        if (duplicateKey($error)) {
            return false;
        }
        throw $error;
    }
}

function unlinkDevice(string $userId, string $deviceId): void
{
    transaction(function () use ($userId, $deviceId): void {
        $updated = query(
            'UPDATE devices SET revoked_at = CURRENT_TIMESTAMP(6)
             WHERE user_id = ? AND id = ? AND revoked_at IS NULL',
            [$userId, $deviceId]
        )->rowCount();
        if ($updated === 1) {
            query('DELETE FROM device_active_conversations WHERE user_id = ? AND device_id = ?', [$userId, $deviceId]);
        }
    });
}
