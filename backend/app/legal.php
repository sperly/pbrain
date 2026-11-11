<?php
declare(strict_types=1);

const TERMS_VERSION = '2026-11-11';
const PRIVACY_VERSION = '2026-11-11';

function legalEscape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function legalUrl(string $document): string
{
    $version = $document === 'terms' ? TERMS_VERSION : PRIVACY_VERSION;
    return 'legal.php?' . http_build_query(['document' => $document, 'version' => $version]);
}

function legalOperator(): array
{
    $settings = config();
    $name = trim((string) ($settings['legal_operator_name'] ?? ''));
    $email = trim((string) ($settings['legal_contact_email'] ?? ''));
    return ['name' => $name, 'email' => filter_var($email, FILTER_VALIDATE_EMAIL) ? $email : '',
            'address' => trim((string) ($settings['legal_operator_address'] ?? ''))];
}

function legalIsDraft(): bool
{
    $operator = legalOperator();
    return $operator['name'] === '' || $operator['email'] === ''
        || (config()['legal_documents_reviewed'] ?? false) !== true;
}

function legalDocument(string $document, string $version): string
{
    // Explicit archive map: query parameters can never become arbitrary include paths.
    $archives = [
        'terms' => ['2026-11-11' => __DIR__ . '/legal/2026-11-11/terms.php'],
        'privacy' => ['2026-11-11' => __DIR__ . '/legal/2026-11-11/privacy.php'],
    ];
    $path = $archives[$document][$version] ?? null;
    if ($path === null) {
        throw new InvalidArgumentException('Document version not found');
    }
    $operator = legalOperator();
    ob_start();
    try {
        require $path;
        return trim(ob_get_clean());
    } catch (Throwable $error) {
        ob_end_clean();
        throw $error;
    }
}

function currentLegalAcceptance(): array
{
    return ['terms_version' => TERMS_VERSION, 'privacy_version' => PRIVACY_VERSION,
            'terms_sha256' => hash('sha256', legalDocument('terms', TERMS_VERSION)),
            'privacy_sha256' => hash('sha256', legalDocument('privacy', PRIVACY_VERSION))];
}

function legalRevision(array $acceptance): string
{
    return hash('sha256', implode("\n", $acceptance));
}
