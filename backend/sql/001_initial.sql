-- PocketBrain initial MariaDB schema
--
-- Create/select an empty database in your hosting panel. Import this file
-- into that database, for example:
--   mariadb -h HOST -u USER -p DATABASE < PocketBrain_MariaDB_Setup.sql
--
-- Import once. If an import fails, earlier CREATE TABLE statements may have
-- succeeded. Check which tables were created before retrying.
-- PHP should use utf8mb4 and set time_zone = '+00:00' on each connection.
-- The PHP bootstrap creates the first admin with password_hash().
-- Store SHA-256 digests of random tokens as 32 raw bytes, not hex.
-- The pairing code uses a separate server-keyed HMAC-SHA-256 digest.
-- Keep the HMAC key and long-lived OpenAI key in PHP server configuration.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET SESSION time_zone = '+00:00';

CREATE TABLE users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    role ENUM('member', 'admin') NOT NULL DEFAULT 'member',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at DATETIME(6) NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Redeem the invite and create the account in one PHP transaction.
CREATE TABLE invitations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    token_hash BINARY(32) NOT NULL,
    created_by_user_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    redeemed_at DATETIME(6) NULL,
    redeemed_by_user_id BIGINT UNSIGNED NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_invitations_token (token_hash),
    KEY ix_invitations_expiry (expires_at),
    CONSTRAINT fk_invitations_creator
        FOREIGN KEY (created_by_user_id) REFERENCES users (id),
    CONSTRAINT fk_invitations_redeemer
        FOREIGN KEY (redeemed_by_user_id) REFERENCES users (id),
    CONSTRAINT ck_invitations_redemption CHECK (
        (redeemed_at IS NULL AND redeemed_by_user_id IS NULL)
        OR (redeemed_at IS NOT NULL AND redeemed_by_user_id IS NOT NULL
            AND revoked_at IS NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Unlink by revoking the device row. Pairing again creates a new row so
-- previous turns keep their original attribution.
CREATE TABLE devices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    credential_hash BINARY(32) NOT NULL,
    linked_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_seen_at DATETIME(6) NULL,
    revoked_at DATETIME(6) NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_devices_credential (credential_hash),
    UNIQUE KEY uq_devices_owner_id (user_id, id),
    CONSTRAINT fk_devices_owner
        FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHP locks the pairing row before approval or redemption. Check expiry
-- under that lock. Rate-limit code guesses and polling in PHP.
-- Delete expired rows periodically to make their codes available again.
CREATE TABLE device_pairings (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code_hash BINARY(32) NOT NULL,
    polling_secret_hash BINARY(32) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    approved_by_user_id BIGINT UNSIGNED NULL,
    approved_at DATETIME(6) NULL,
    redeemed_at DATETIME(6) NULL,
    device_id BIGINT UNSIGNED NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_pairings_code (code_hash),
    UNIQUE KEY uq_pairings_polling_secret (polling_secret_hash),
    UNIQUE KEY uq_pairings_device (device_id),
    KEY ix_pairings_expiry (expires_at),
    CONSTRAINT fk_pairings_approver
        FOREIGN KEY (approved_by_user_id) REFERENCES users (id),
    CONSTRAINT fk_pairings_device_owner
        FOREIGN KEY (approved_by_user_id, device_id)
        REFERENCES devices (user_id, id),
    CONSTRAINT ck_pairings_approval CHECK (
        (approved_by_user_id IS NULL AND approved_at IS NULL)
        OR (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)
    ),
    CONSTRAINT ck_pairings_redemption CHECK (
        (redeemed_at IS NULL AND device_id IS NULL)
        OR (redeemed_at IS NOT NULL AND device_id IS NOT NULL
            AND approved_at IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PHP sets the BCP 47 language tag from the first substantive question and
-- updates last_activity_at in the same transaction as a new turn.
CREATE TABLE conversations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(160) NOT NULL,
    language_tag VARCHAR(63) CHARACTER SET ascii COLLATE ascii_general_ci NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_activity_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),
    UNIQUE KEY uq_conversations_owner_id (user_id, id),
    KEY ix_conversations_history (user_id, last_activity_at, id),
    CONSTRAINT fk_conversations_owner
        FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- client_turn_id is a lowercase UUID supplied by the device. On retry, PHP
-- returns the existing turn. For a first turn, create the conversation and
-- insert the turn in one transaction, rolling back if the insert loses a race.
-- Token counts are optional per-turn figures and are deleted with the thread.
CREATE TABLE conversation_turns (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NOT NULL,
    device_id BIGINT UNSIGNED NOT NULL,
    client_turn_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    question_text MEDIUMTEXT NOT NULL,
    reply_text MEDIUMTEXT NULL,
    reply_status ENUM('complete', 'interrupted') NOT NULL DEFAULT 'complete',
    input_tokens INT UNSIGNED NULL,
    output_tokens INT UNSIGNED NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (id),
    UNIQUE KEY uq_turns_device_client_id (device_id, client_turn_id),
    KEY ix_turns_history (user_id, conversation_id, id),
    CONSTRAINT fk_turns_conversation_owner
        FOREIGN KEY (user_id, conversation_id)
        REFERENCES conversations (user_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_turns_device_owner
        FOREIGN KEY (user_id, device_id) REFERENCES devices (user_id, id),
    CONSTRAINT ck_turns_complete_reply CHECK (
        reply_status <> 'complete' OR reply_text IS NOT NULL
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- No row means the next Talk can start a new conversation. Deleting an active
-- conversation removes the selection for every device that selected it.
CREATE TABLE device_active_conversations (
    device_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NOT NULL,
    selected_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (device_id),
    CONSTRAINT fk_active_device_owner
        FOREIGN KEY (user_id, device_id)
        REFERENCES devices (user_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_active_conversation_owner
        FOREIGN KEY (user_id, conversation_id)
        REFERENCES conversations (user_id, id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
