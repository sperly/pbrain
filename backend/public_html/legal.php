<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';
require dirname(__DIR__) . '/app/legal.php';

header('Content-Type: text/html; charset=UTF-8');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");

if (!isHttps()) {
    http_response_code(400);
    exit('HTTPS is required.');
}
if ($_SERVER['REQUEST_METHOD'] !== 'GET' && $_SERVER['REQUEST_METHOD'] !== 'HEAD') {
    header('Allow: GET, HEAD');
    http_response_code(405);
    exit('Method not allowed.');
}
$document = $_GET['document'] ?? 'privacy';
if (!is_string($document) || !in_array($document, ['privacy', 'terms'], true)) {
    http_response_code(404);
    exit('Document not found.');
}
$version = $_GET['version'] ?? ($document === 'terms' ? TERMS_VERSION : PRIVACY_VERSION);
if (!is_string($version)) {
    http_response_code(404);
    exit('Document version not found.');
}
try {
    $content = legalDocument($document, $version);
    $draft = legalIsDraft();
} catch (InvalidArgumentException) {
    http_response_code(404);
    exit('Document version not found.');
} catch (Throwable $error) {
    error_log('PocketBrain legal page error: ' . get_class($error));
    http_response_code(500);
    exit('This document could not be loaded.');
}
$title = $document === 'terms' ? 'Terms and Conditions' : 'Privacy Policy';
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="style.css">
    <link rel="icon" type="image/svg+xml" href="assets/pocketbrain-icon.svg">
    <title><?= legalEscape($title) ?> · PocketBrain</title>
</head>
<body>
<a class="skip-link" href="#legal-content">Skip to content</a>
<main>
    <header class="site-header"><a class="brand" href="index.php"><img class="brand-logo" src="assets/pocketbrain-web.svg" alt="PocketBrain" width="489" height="125"><span class="brand-caption">A little space for your thoughts.</span></a><a href="index.php">Back to PocketBrain</a></header>
    <article class="legal-page" id="legal-content">
        <p class="eyebrow">PocketBrain · Version <?= legalEscape($version) ?></p>
        <h1><?= legalEscape($title) ?></h1>
        <?php if ($draft): ?><aside class="message legal-draft-note"><strong>Draft for operator review.</strong> This generic text needs completed operator details and review of actual retention, provider arrangements, and applicable requirements before public use.</aside><?php endif; ?>
        <nav class="legal-nav" aria-label="Legal documents"><a href="<?= legalEscape(legalUrl('privacy')) ?>">Privacy policy</a><a href="<?= legalEscape(legalUrl('terms')) ?>">Terms and conditions</a></nav>
        <?= $content ?>
    </article>
    <footer class="site-footer"><a href="index.php">PocketBrain</a><a href="<?= legalEscape(legalUrl('privacy')) ?>">Privacy policy</a><a href="<?= legalEscape(legalUrl('terms')) ?>">Terms and conditions</a><a href="index.php?cookie-settings=1#cookie-banner">Cookie preferences</a></footer>
</main>
</body>
</html>
