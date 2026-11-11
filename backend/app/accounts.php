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

require_once __DIR__ . '/legal.php';

function redeemInvite(string $digest, string $email, string $password, array $acceptance): bool
{
    if ($acceptance !== currentLegalAcceptance()) {
        return false;
    }
    $passwordHash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
    try {
        return transaction(function () use ($digest, $email, $passwordHash, $acceptance): bool {
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
            foreach (['terms', 'privacy'] as $document) {
                query('INSERT INTO legal_documents (document_sha256, document_type, version, document_html)
                       VALUES (UNHEX(?), ?, ?, ?) ON DUPLICATE KEY UPDATE document_sha256 = VALUES(document_sha256)',
                      [$acceptance[$document . '_sha256'], $document, $acceptance[$document . '_version'],
                       legalDocument($document, $acceptance[$document . '_version'])]);
            }
            query('INSERT INTO user_legal_acceptances
                   (user_id, terms_version, privacy_version, terms_sha256, privacy_sha256)
                   VALUES (?, ?, ?, UNHEX(?), UNHEX(?))',
                  [$userId, $acceptance['terms_version'], $acceptance['privacy_version'],
                   $acceptance['terms_sha256'], $acceptance['privacy_sha256']]);
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
