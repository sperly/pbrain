-- Import once after 001, 002, and 003. Existing users are not marked as having accepted.
-- Immutable public-document snapshots preserve the text even if operator details change.
CREATE TABLE legal_documents (
    document_sha256 BINARY(32) NOT NULL,
    document_type ENUM('terms', 'privacy') NOT NULL,
    version VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    document_html MEDIUMTEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (document_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_legal_acceptances (
    user_id BIGINT UNSIGNED NOT NULL,
    terms_version VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    privacy_version VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    terms_sha256 BINARY(32) NOT NULL,
    privacy_sha256 BINARY(32) NOT NULL,
    accepted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (user_id),
    CONSTRAINT fk_legal_terms_document FOREIGN KEY (terms_sha256) REFERENCES legal_documents (document_sha256),
    CONSTRAINT fk_legal_privacy_document FOREIGN KEY (privacy_sha256) REFERENCES legal_documents (document_sha256),
    CONSTRAINT fk_legal_acceptance_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;
