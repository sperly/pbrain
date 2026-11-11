<?php
declare(strict_types=1);

function config(): array
{
    static $config;
    if ($config !== null) {
        return $config;
    }

    $path = dirname(__DIR__) . '/config.php';
    if (!is_file($path)) {
        throw new RuntimeException('Missing config.php');
    }

    $settings = require $path;
    $url = parse_url($settings['base_url']);
    if (($url['scheme'] ?? '') !== 'https' || !isset($url['host'])
        || isset($url['user']) || isset($url['pass']) || isset($url['query']) || isset($url['fragment'])
        || !preg_match('/\A[a-f0-9]{64}\z/D', $settings['app_key'])) {
        throw new RuntimeException('Set an HTTPS base_url and a 64-character lowercase hex app_key');
    }

    $settings['base_url'] = rtrim($settings['base_url'], '/');
    $settings['app_key'] = hex2bin($settings['app_key']);
    return $config = $settings;
}

function db(): PDO
{
    static $db;
    if ($db === null) {
        $c = config();
        $db = new PDO(
            "mysql:host={$c['db_host']};port={$c['db_port']};dbname={$c['db_name']};charset=utf8mb4",
            $c['db_user'],
            $c['db_password'],
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]
        );
        $db->exec("SET SESSION time_zone = '+00:00'");
    }
    return $db;
}

function query(string $sql, array $params = []): PDOStatement
{
    $stmt = db()->prepare($sql);
    $stmt->execute($params);
    return $stmt;
}

function transaction(callable $operation): mixed
{
    $db = db();
    $db->beginTransaction();
    try {
        $result = $operation();
        $db->commit();
        return $result;
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $error;
    }
}

function duplicateKey(PDOException $error): bool
{
    return ($error->errorInfo[1] ?? null) === 1062;
}

function normalizedEmail(string $email): ?string
{
    $email = strtolower(trim($email));
    return strlen($email) <= 254 && filter_var($email, FILTER_VALIDATE_EMAIL) ? $email : null;
}

function validPassword(string $password): bool
{
    return strlen($password) >= 15 && strlen($password) <= 72 && !str_contains($password, "\0");
}

function randomToken(): string
{
    return bin2hex(random_bytes(32));
}

function validToken(string $token): bool
{
    return preg_match('/\A[a-f0-9]{64}\z/D', $token) === 1;
}

function bearerToken(): string
{
    // CGI/FastCGI and internal rewrites can expose the same request header
    // through a different server variable. Never accept a query/body token.
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
    if ($header === null && function_exists('getallheaders')) {
        foreach (getallheaders() as $name => $value) {
            if (strcasecmp($name, 'Authorization') === 0) {
                $header = $value;
                break;
            }
        }
    }
    return is_string($header) && preg_match('/\ABearer ([a-f0-9]{64})\z/iD', $header, $match) === 1
        ? $match[1] : '';
}

function tokenHash(string $token): string
{
    return hash('sha256', $token);
}

function appMac(string $purpose, string $value): string
{
    return hash_hmac('sha256', $purpose . "\0" . $value, config()['app_key']);
}

function rateAllowed(string $scope, string $subject, int $limit, int $seconds): bool
{
    $now = time();
    $start = $now - $now % $seconds;
    query(
        'INSERT INTO auth_rate_limits (bucket_key, window_start, attempts)
         VALUES (UNHEX(?), ?, LAST_INSERT_ID(1))
         ON DUPLICATE KEY UPDATE attempts = LAST_INSERT_ID(LEAST(attempts + 1, 10000))',
        [appMac('rate', $scope . "\0" . $subject), $start]
    );
    return (int) db()->query("SELECT LAST_INSERT_ID()")->fetchColumn() <= $limit;
}

function isHttps(): bool
{
    return in_array(strtolower($_SERVER['HTTPS'] ?? ''), ['on', '1'], true);
}

function clientIp(): string
{
    return $_SERVER['REMOTE_ADDR'] ?? 'unknown';
}

function deviceByCredential(string $credential): array|false
{
    if (!validToken($credential)) {
        return false;
    }
    return query(
        'SELECT d.id, d.display_name, d.user_id
         FROM devices d JOIN users u ON u.id = d.user_id
         WHERE d.credential_hash = UNHEX(?) AND d.revoked_at IS NULL AND u.disabled_at IS NULL',
        [tokenHash($credential)]
    )->fetch();
}

function recordDeviceSeen(string $deviceId): void
{
    query(
        'UPDATE devices SET last_seen_at = CURRENT_TIMESTAMP(6)
         WHERE id = ? AND revoked_at IS NULL',
        [$deviceId]
    );
}
