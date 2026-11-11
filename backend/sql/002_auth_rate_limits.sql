-- Run after 001_initial.sql. Import only this file if the initial schema exists.
CREATE TABLE auth_rate_limits (
    bucket_key BINARY(32) NOT NULL,
    window_start BIGINT UNSIGNED NOT NULL,
    attempts SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (bucket_key, window_start),
    KEY ix_auth_rate_limits_window (window_start)
) ENGINE=InnoDB;

-- Optional daily cleanup with the application database account:
-- DELETE FROM auth_rate_limits WHERE window_start < UNIX_TIMESTAMP() - 86400;
