-- Run once after 001_initial.sql and 002_auth_rate_limits.sql.
-- Keys are encrypted by PHP with a purpose-derived key from the private app_key.
-- Back up app_key separately from the database and keep it stable.
CREATE TABLE user_openai_keys (
    user_id BIGINT UNSIGNED NOT NULL,
    encrypted_key VARBINARY(2048) NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id),
    CONSTRAINT fk_user_openai_keys_owner
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;
