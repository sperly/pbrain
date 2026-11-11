<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

require dirname(__DIR__) . '/app/bootstrap.php';

$email = normalizedEmail($argv[1] ?? '');
if ($argc !== 2 || $email === null) {
    fwrite(STDERR, "Usage: php bin/create-admin.php you@example.com\n");
    exit(1);
}

function readPassword(string $prompt): string
{
    fwrite(STDERR, $prompt);
    $tty = stream_isatty(STDIN);
    if ($tty) {
        system('stty -echo < /dev/tty', $status);
        if ($status !== 0) {
            throw new RuntimeException('Could not disable terminal echo. Use a protected stdin pipe.');
        }
    }
    try {
        $line = fgets(STDIN);
    } finally {
        if ($tty) {
            system('stty echo < /dev/tty');
            fwrite(STDERR, "\n");
        }
    }

    if ($line === false) {
        throw new RuntimeException('Missing password input');
    }
    return rtrim($line, "\r\n");
}

try {
    $password = readPassword('Admin password (15 to 72 bytes): ');
    if (!validPassword($password) || $password !== readPassword('Confirm password: ')) {
        throw new RuntimeException('Invalid password length or confirmation mismatch');
    }
    $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
    if ((int) query("SELECT GET_LOCK(SHA2(CONCAT(DATABASE(), ':pocketbrain-admin'), 256), 5)")->fetchColumn() !== 1) {
        throw new RuntimeException('Could not acquire the admin bootstrap lock');
    }
    try {
        if (query("SELECT id FROM users WHERE role = 'admin' LIMIT 1")->fetchColumn() !== false) {
            throw new RuntimeException('An admin already exists');
        }
        query("INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'admin')", [$email, $hash]);
    } finally {
        query("SELECT RELEASE_LOCK(SHA2(CONCAT(DATABASE(), ':pocketbrain-admin'), 256))");
    }
    fwrite(STDOUT, "Administrator created.\n");
} catch (PDOException $error) {
    fwrite(STDERR, 'Database error. Check config.php and the schema. SQLSTATE: ' . $error->getCode() . "\n");
    exit(1);
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . "\n");
    exit(1);
}
