<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';
require dirname(__DIR__) . '/app/accounts.php';
require dirname(__DIR__) . '/app/pairing.php';
require dirname(__DIR__) . '/app/openai_keys.php';
require dirname(__DIR__) . '/app/dashboard_history.php';

header('Content-Type: text/html; charset=UTF-8');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");

function h(string|int|null $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function historyUrl(array $changes = []): string
{
    global $history;
    $params = array_replace([
        'device' => $history['device'] ?? null,
        'conversation' => $history['selected'] ?? null,
        'offset' => ($history['offset'] ?? 0) ?: null,
    ], $changes);
    $query = http_build_query(array_filter($params, static fn($value) => $value !== null && $value !== ''));
    return 'index.php' . ($query === '' ? '' : '?' . $query) . '#conversations';
}

function transcriptHtml(string $text): string
{
    $parts = preg_split('/(https?:\/\/[^\s<>"\x00-\x1f]+)/u', $text, -1, PREG_SPLIT_DELIM_CAPTURE);
    if ($parts === false) {
        return nl2br(h($text));
    }
    $html = '';
    foreach ($parts as $index => $part) {
        if ($index % 2 === 1) {
            $url = rtrim($part, '.,;:!?');
            foreach ([')' => '(', ']' => '['] as $close => $open) {
                while (str_ends_with($url, $close) && substr_count($url, $close) > substr_count($url, $open)) {
                    $url = substr($url, 0, -1);
                }
            }
            $html .= '<a href="' . h($url) . '" target="_blank" rel="noopener noreferrer">' . h($url) . '</a>'
                   . h(substr($part, strlen($url)));
        } else {
            $html .= nl2br(h($part));
        }
    }
    return $html;
}

function field(string $name): string
{
    return is_string($_POST[$name] ?? null) ? $_POST[$name] : '';
}

function csrfInput(): void
{
    echo '<input type="hidden" name="csrf" value="' . h($_SESSION['csrf']) . '">';
}

function redirect(string $anchor = ''): never
{
    header('Location: index.php' . $anchor, true, 303);
    exit;
}

function notifyAndRedirect(string $message, string $anchor = ''): never
{
    $_SESSION['message'] = $message;
    redirect($anchor);
}

function requireSignedIn(array|false $user): void
{
    if ($user === false) {
        notifyAndRedirect('Sign in to continue.');
    }
}

function requireAdmin(array|false $user): void
{
    if (($user['role'] ?? '') !== 'admin') {
        http_response_code(403);
        exit('Administrator access required.');
    }
}

if (!isHttps()) {
    http_response_code(400);
    exit('HTTPS is required.');
}

try {
    $cookiePath = rtrim(parse_url(config()['base_url'], PHP_URL_PATH) ?? '', '/') . '/';
    session_name('PocketBrain');
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    session_set_cookie_params([
        'path' => $cookiePath,
        'secure' => true,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    if (!session_start()) {
        throw new RuntimeException('Could not start session');
    }

    $user = false;
    if (isset($_SESSION['user_id'], $_SESSION['signed_in_at'])) {
        if ($_SESSION['signed_in_at'] > time() - 12 * 3600) {
            $user = query(
                'SELECT id, email, role FROM users WHERE id = ? AND disabled_at IS NULL',
                [$_SESSION['user_id']]
            )->fetch();
        }
        if ($user === false) {
            $_SESSION = [];
            session_regenerate_id(true);
        }
    }
    $_SESSION['csrf'] ??= randomToken();

    if ($_SERVER['REQUEST_METHOD'] === 'GET' && array_key_exists('invite', $_GET)) {
        if ($user !== false) {
            notifyAndRedirect('Sign out before opening an invitation for another account.');
        }
        $token = $_GET['invite'];
        if (!is_string($token) || !validToken($token)) {
            unset($_SESSION['invite_hash']);
            notifyAndRedirect('This invitation link is invalid.');
        }
        $_SESSION['invite_hash'] = tokenHash($token);
        redirect();
    }

    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        if (!hash_equals($_SESSION['csrf'], field('csrf'))) {
            http_response_code(403);
            exit('This form has expired. Reload the page and try again.');
        }

        switch (field('action')) {
            case 'sign-in':
                if ($user !== false) {
                    redirect();
                }
                $email = normalizedEmail(field('email')) ?? '';
                if (!rateAllowed('login-ip', clientIp(), 30, 300)
                    || !rateAllowed('login-email', $email, 10, 300)) {
                    notifyAndRedirect('Too many sign-in attempts. Try again in a few minutes.');
                }
                $account = authenticate($email, field('password'));
                if ($account === false) {
                    notifyAndRedirect('Invalid email address or password.');
                }
                session_regenerate_id(true);
                $_SESSION = ['user_id' => $account['id'], 'signed_in_at' => time()];
                redirect();

            case 'sign-out':
                $_SESSION = [];
                session_regenerate_id(true);
                redirect();

            case 'cancel-signup':
                unset($_SESSION['invite_hash']);
                redirect();

            case 'sign-up':
                if ($user !== false || !isset($_SESSION['invite_hash'])) {
                    redirect();
                }
                if (!rateAllowed('signup-ip', clientIp(), 15, 300)) {
                    notifyAndRedirect('Too many signup attempts. Try again in a few minutes.');
                }
                $email = normalizedEmail(field('email'));
                $password = field('password');
                if ($email === null || !validPassword($password) || $password !== field('confirmation')) {
                    notifyAndRedirect('Enter a valid email and matching passwords of 15 to 72 bytes.');
                }
                if (!redeemInvite($_SESSION['invite_hash'], $email, $password)) {
                    notifyAndRedirect('Could not create the account. Check the email or request a fresh invitation.');
                }
                unset($_SESSION['invite_hash']);
                notifyAndRedirect('Account created. You can now sign in.');

            case 'create-invite':
                requireAdmin($user);
                $token = randomToken();
                query(
                    'INSERT INTO invitations (token_hash, created_by_user_id, expires_at)
                     VALUES (UNHEX(?), ?, CURRENT_TIMESTAMP(6) + INTERVAL 1 DAY)',
                    [tokenHash($token), $user['id']]
                );
                $_SESSION['new_invite'] = config()['base_url'] . '/index.php?invite=' . $token;
                notifyAndRedirect('Invitation created. Copy the link now.', '#invitations');

            case 'revoke-invite':
                requireAdmin($user);
                $id = field('id');
                if (ctype_digit($id) && strlen($id) <= 20) {
                    query(
                        'UPDATE invitations SET revoked_at = CURRENT_TIMESTAMP(6)
                         WHERE id = ? AND revoked_at IS NULL AND redeemed_at IS NULL
                           AND expires_at > CURRENT_TIMESTAMP(6)',
                        [$id]
                    );
                }
                redirect('#invitations');

            case 'approve-pairing':
                requireSignedIn($user);
                if (!rateAllowed('approve-ip', clientIp(), 30, 300)
                    || !rateAllowed('approve-user', (string) $user['id'], 10, 300)) {
                    notifyAndRedirect('Too many pairing attempts. Try again in a few minutes.', '#devices');
                }
                $approved = approvePairing((string) $user['id'], field('code'));
                notifyAndRedirect(
                    $approved ? 'Pairing approved. The device can now finish linking.'
                              : 'The pairing code is invalid, expired or already used.',
                    '#devices'
                );

            case 'save-openai-key':
                requireSignedIn($user);
                if (!rateAllowed('openai-key-user', (string) $user['id'], 10, 300)) {
                    notifyAndRedirect('Too many key changes. Try again in a few minutes.', '#openai');
                }
                $apiKey = trim(field('openai_api_key'));
                if (!validOpenaiKey($apiKey)) {
                    notifyAndRedirect('Enter an OpenAI API key starting with sk-.', '#openai');
                }
                saveUserOpenaiKey((string) $user['id'], $apiKey);
                notifyAndRedirect('API key saved. It will be checked on your next voice request.', '#openai');

            case 'remove-openai-key':
                requireSignedIn($user);
                removeUserOpenaiKey((string) $user['id']);
                notifyAndRedirect('Your API key was removed from PocketBrain. You can also revoke it in OpenAI.', '#openai');

            case 'unlink-device':
                requireSignedIn($user);
                $id = field('id');
                if (ctype_digit($id) && strlen($id) <= 20) {
                    unlinkDevice((string) $user['id'], $id);
                }
                redirect('#devices');
        }
        http_response_code(400);
        exit('Unknown form action.');
    }
    if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
        header('Allow: GET, POST');
        http_response_code(405);
        exit('Method not allowed.');
    }

    $message = $_SESSION['message'] ?? '';
    $newInvite = $_SESSION['new_invite'] ?? '';
    $signup = isset($_SESSION['invite_hash']);
    unset($_SESSION['message'], $_SESSION['new_invite']);
    $devices = [];
    $invitations = [];
    $accounts = [];
    $openaiKeyStatus = false;
    $history = [];
    $historyError = null;
    $allDevices = [];
    $totals = [];
    if ($user !== false) {
        $openaiKeyStatus = userOpenaiKeyStatus((string) $user['id']);
        $allDevices = query(
            'SELECT d.id, d.display_name, d.linked_at, d.last_seen_at, d.revoked_at,
                    (SELECT COUNT(DISTINCT t.conversation_id) FROM conversation_turns t
                     WHERE t.user_id = d.user_id AND t.device_id = d.id) AS conversation_count
             FROM devices d WHERE d.user_id = ? ORDER BY d.revoked_at IS NOT NULL, d.id DESC',
            [$user['id']]
        )->fetchAll();
        $devices = array_values(array_filter($allDevices, static fn($d) => $d['revoked_at'] === null));
        $totals = query(
            'SELECT (SELECT COUNT(*) FROM conversations WHERE user_id = ?) AS conversations,
                    (SELECT COUNT(*) FROM conversation_turns WHERE user_id = ?) AS turns',
            [$user['id'], $user['id']]
        )->fetch();
        try {
            $history = dashboardHistory((string) $user['id'], $_GET);
        } catch (HistoryError $error) {
            http_response_code($error->status);
            $historyError = $error->status === 404 ? 'That device or conversation is unavailable.' : 'This history link is invalid.';
        }
        if ($user['role'] === 'admin') {
            $accounts = query(
                'SELECT email, role, created_at, disabled_at FROM users ORDER BY id DESC LIMIT 100'
            )->fetchAll();
            $invitations = query(
                "SELECT id, created_at, expires_at,
                    CASE WHEN redeemed_at IS NOT NULL THEN 'Redeemed'
                         WHEN revoked_at IS NOT NULL THEN 'Revoked'
                         WHEN expires_at <= CURRENT_TIMESTAMP(6) THEN 'Expired'
                         ELSE 'Open' END AS state
                 FROM invitations ORDER BY id DESC LIMIT 100"
            )->fetchAll();
        }
    }
} catch (Throwable $error) {
    error_log('PocketBrain web error: ' . get_class($error) . ' ' . $error->getCode());
    http_response_code(500);
    exit('PocketBrain could not complete this request.');
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="style.css">
    <title>PocketBrain</title>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<main id="main">
    <header class="site-header">
        <a class="brand" href="index.php"><span class="brand-mark" aria-hidden="true">p.</span><span>PocketBrain<span class="brand-caption">A little space for your thoughts.</span></span></a>
        <?php if ($user !== false): ?>
            <form method="post" class="account-menu">
                <?php csrfInput(); ?>
                <span><?= h($user['email']) ?></span>
                <button class="secondary" name="action" value="sign-out">Sign out</button>
            </form>
        <?php endif; ?>
    </header>
    <?php if ($message !== ''): ?><p class="message" role="status"><?= h($message) ?></p><?php endif; ?>

    <?php if ($user === false && $signup): ?>
        <div class="auth-panel"><p class="eyebrow">You're invited</p><h1>Make room for a thought.</h1><h2>Accept invitation</h2>
        <form method="post">
            <?php csrfInput(); ?>
            <label>Email <input type="email" name="email" maxlength="254" autocomplete="email" required></label>
            <label>Password <input type="password" name="password" minlength="15" maxlength="72" autocomplete="new-password" required></label>
            <label>Confirm password <input type="password" name="confirmation" minlength="15" maxlength="72" autocomplete="new-password" required></label>
            <button name="action" value="sign-up">Create account</button>
            <button name="action" value="cancel-signup" formnovalidate>Back to sign in</button>
        </form>
        </div>
    <?php elseif ($user === false): ?>
        <div class="auth-panel"><p class="eyebrow">Welcome back</p><h1>Your thoughts, all together.</h1>
        <p class="muted">Sign in to revisit a conversation or connect your PocketBrain.</p><h2>Sign in</h2>
        <form method="post">
            <?php csrfInput(); ?>
            <label>Email <input type="email" name="email" maxlength="254" autocomplete="username" required></label>
            <label>Password <input type="password" name="password" maxlength="72" autocomplete="current-password" required></label>
            <button name="action" value="sign-in">Sign in</button>
        </form>
        </div>
    <?php else: ?>
        <nav class="page-nav" aria-label="Dashboard sections">
            <a href="#conversations">Conversations</a><a href="#devices">Devices</a><a href="#openai">API key</a>
            <?php if ($user['role'] === 'admin'): ?><a href="#accounts">Accounts</a><a href="#invitations">Invitations</a><?php endif; ?>
        </nav>
        <div class="page-intro"><div><p class="eyebrow">Your PocketBrain</p><h1>Pick up a thought.</h1>
            <p class="muted">Revisit your questions, discoveries, and everything in between.</p></div>
            <dl class="stats"><div><dt>Devices linked</dt><dd><?= count($devices) ?></dd></div>
                <div><dt>Conversations</dt><dd><?= h($totals['conversations']) ?></dd></div>
                <div><dt>Questions saved</dt><dd><?= h($totals['turns']) ?></dd></div></dl>
        </div>
        <section id="conversations" class="history-section">
            <div class="section-heading"><div><p class="eyebrow">Your history</p><h2>Conversations</h2></div>
                <form method="get" action="index.php#conversations" class="device-filter">
                    <label for="device-filter">Show conversations from</label>
                    <div class="inline"><select id="device-filter" name="device">
                        <option value="">All my devices</option>
                        <?php foreach ($allDevices as $device): ?>
                            <option value="<?= h($device['id']) ?>" <?= (string) $device['id'] === ($history['device'] ?? '') ? 'selected' : '' ?>><?= h($device['display_name']) ?> #<?= h($device['id']) ?><?= $device['revoked_at'] === null ? '' : ' · Unlinked' ?></option>
                        <?php endforeach; ?>
                    </select><button class="secondary" type="submit">Show</button></div>
                </form>
            </div>
            <?php if ($historyError !== null): ?>
                <div class="empty-state"><h3>Nothing to open here</h3><p><?= h($historyError) ?></p><a href="index.php#conversations">Back to my conversations</a></div>
            <?php else: ?>
                <div class="history-layout">
                    <aside class="thread-index" aria-label="Saved conversations">
                        <div class="index-caption">Latest activity <span>UTC</span></div>
                        <?php if (!$history['rows']): ?>
                            <div class="empty-state"><h3>No conversations yet</h3><p>Ask your PocketBrain a question. Saved conversations from this device will appear here.</p></div>
                        <?php endif; ?>
                        <?php foreach ($history['rows'] as $thread): ?>
                            <a class="thread-link <?= (string) $thread['id'] === $history['selected'] ? 'is-selected' : '' ?>" href="<?= h(historyUrl(['conversation' => (string) $thread['id']])) ?>" <?= (string) $thread['id'] === $history['selected'] ? 'aria-current="page"' : '' ?>>
                                <span class="thread-title"><?= h($thread['title']) ?></span>
                                <span class="thread-meta"><?= h(substr($thread['last_activity_at'], 0, 16)) ?> <span>· <?= h($thread['turn_count']) ?> <?= (int) $thread['turn_count'] === 1 ? 'question' : 'questions' ?></span></span>
                            </a>
                        <?php endforeach; ?>
                        <nav class="pagination" aria-label="Conversation pages">
                            <?php if ($history['offset'] > 0): ?><a href="<?= h(historyUrl(['offset' => max(0, $history['offset'] - 25), 'conversation' => null])) ?>">← Newer</a><?php endif; ?>
                            <?php if ($history['next_offset'] !== null): ?><a href="<?= h(historyUrl(['offset' => $history['next_offset'], 'conversation' => null])) ?>">Older →</a><?php endif; ?>
                        </nav>
                    </aside>
                    <div class="thread-reader" id="thread-reader">
                        <?php if ($history['thread'] === null): ?>
                            <div class="reader-placeholder"><span class="placeholder-mark" aria-hidden="true">“</span><h3>A conversation worth coming back to.</h3><p>Choose a conversation to read your questions and replies.</p><p class="muted">Filter by device to find where a thought began.</p></div>
                        <?php else: ?>
                            <header class="reader-heading"><p class="eyebrow">Saved conversation<?= $history['thread']['language_tag'] === null ? '' : ' · ' . h($history['thread']['language_tag']) ?></p>
                                <h3><?= h($history['thread']['title']) ?></h3>
                                <p class="muted">Shared across your devices. Each question shows where it was asked. Times are UTC.</p>
                            </header>
                            <?php if ($history['after'] !== '0'): ?><a class="back-link" href="<?= h(historyUrl()) ?>">← Back to the first question</a><?php endif; ?>
                            <?php foreach ($history['turns'] as $turn): ?>
                                <article class="conversation-turn">
                                    <div class="turn-meta"><span><?= h($turn['display_name']) ?> #<?= h($turn['device_id']) ?><?= $turn['revoked_at'] === null ? '' : ' · Unlinked' ?></span><time><?= h(substr($turn['created_at'], 0, 16)) ?></time></div>
                                    <div class="question"><p class="speaker">You</p><div class="transcript"><?= transcriptHtml($turn['question_text'] ?: 'No question transcript available.') ?></div></div>
                                    <div class="answer"><p class="speaker">PocketBrain <?php if ($turn['reply_status'] === 'interrupted'): ?><span class="badge">Interrupted</span><?php endif; ?></p><div class="transcript"><?= transcriptHtml($turn['reply_text'] ?? 'No reply text saved.') ?></div></div>
                                </article>
                            <?php endforeach; ?>
                            <?php if ($history['next_after'] !== null): ?><nav class="pagination" aria-label="Transcript pages"><a href="<?= h(historyUrl(['after_id' => $history['next_after']])) ?>">Read the next questions →</a></nav><?php endif; ?>
                        <?php endif; ?>
                    </div>
                </div>
            <?php endif; ?>
        </section>

        <section id="openai">
            <h2>My OpenAI API key</h2>
            <p>Your linked devices use this key for voice requests, billed to your OpenAI API project.</p>
            <p>Create a dedicated key in the <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI API Platform</a>
               and check its <a href="https://platform.openai.com/settings/organization/billing/overview" target="_blank" rel="noopener noreferrer">credits and billing</a>.
               <a href="https://developers.openai.com/api/docs/guides/chatgpt-api-credits" target="_blank" rel="noopener noreferrer">Eligible ChatGPT plans may offer API credits</a>; activate them in your OpenAI account.</p>
            <?php if ($openaiKeyStatus !== false): ?>
                <p>Personal key saved. Updated <?= h(substr($openaiKeyStatus['updated_at'], 0, 19)) ?> UTC.</p>
            <?php elseif ((config()['allow_shared_openai_key'] ?? false) === true && (config()['openai_api_key'] ?? '') !== ''): ?>
                <p>No personal key saved. Voice currently uses the site's shared API account.</p>
            <?php else: ?>
                <p>No key saved. Add a key to enable voice on your devices.</p>
            <?php endif; ?>
            <details><summary><?= $openaiKeyStatus === false ? 'Add an API key' : 'Manage my API key' ?></summary>
            <form method="post">
                <?php csrfInput(); ?>
                <label><?= $openaiKeyStatus === false ? 'API key' : 'Replacement API key' ?>
                    <input type="password" name="openai_api_key" maxlength="1024" autocomplete="off" spellcheck="false" required>
                </label>
                <p>The key is encrypted on this server and never displayed again or sent to your devices.
                   Saving replaces your previous key. Removing it here does not revoke it at OpenAI.</p>
                <button name="action" value="save-openai-key"><?= $openaiKeyStatus === false ? 'Save key' : 'Replace key' ?></button>
            </form>
            <?php if ($openaiKeyStatus !== false): ?>
                <form method="post">
                    <?php csrfInput(); ?>
                    <button name="action" value="remove-openai-key">Remove my key</button>
                </form>
            <?php endif; ?>
            </details>
        </section>

        <section id="devices">
            <h2>My devices</h2>
            <p>Start linking on your PocketBrain, then enter the code shown on its display.</p>
            <form method="post">
                <?php csrfInput(); ?>
                <label>Pairing code <input name="code" maxlength="12" placeholder="ABCD-EFGH" autocomplete="off" autocapitalize="characters" required></label>
                <button name="action" value="approve-pairing">Approve pairing</button>
            </form>
            <?php if (!$devices): ?>
                <p>No devices linked yet.</p>
            <?php else: ?>
                <div class="scroll"><table>
                    <thead><tr><th>Device</th><th>Linked (UTC)</th><th>Last seen (UTC)</th><th>Conversations</th><th>Action</th></tr></thead>
                    <tbody>
                    <?php foreach ($devices as $device): ?>
                        <tr>
                            <td><?= h($device['display_name']) ?> #<?= h($device['id']) ?></td>
                            <td><?= h(substr($device['linked_at'], 0, 19)) ?></td>
                            <td><?= $device['last_seen_at'] === null ? '—' : h(substr($device['last_seen_at'], 0, 19)) ?></td>
                            <td><a class="device-history-link" href="<?= h(historyUrl(['device' => (string) $device['id'], 'conversation' => null, 'offset' => null])) ?>"><?= h($device['conversation_count']) ?> conversations →</a></td>
                            <td><form method="post">
                                <?php csrfInput(); ?>
                                <input type="hidden" name="id" value="<?= h($device['id']) ?>">
                                <button name="action" value="unlink-device">Unlink</button>
                            </form></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table></div>
            <?php endif; ?>
        </section>

        <?php if ($user['role'] === 'admin'): ?>
            <section id="accounts">
                <h2>Recent accounts</h2>
                <div class="scroll"><table>
                    <thead><tr><th>Email</th><th>Role</th><th>Created (UTC)</th><th>Status</th></tr></thead>
                    <tbody>
                    <?php foreach ($accounts as $account): ?>
                        <tr>
                            <td><?= h($account['email']) ?></td>
                            <td><?= h($account['role']) ?></td>
                            <td><?= h(substr($account['created_at'], 0, 19)) ?></td>
                            <td><?= $account['disabled_at'] === null ? 'Active' : 'Disabled' ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table></div>
            </section>
            <section id="invitations">
                <h2>Invitations</h2>
                <form method="post">
                    <?php csrfInput(); ?>
                    <button name="action" value="create-invite">Create 24-hour invitation</button>
                </form>
                <?php if ($newInvite !== ''): ?>
                    <label>Copy this one-time link <input type="url" readonly value="<?= h($newInvite) ?>"></label>
                <?php endif; ?>
                <?php if ($invitations): ?>
                    <div class="scroll"><table>
                        <thead><tr><th>Invite</th><th>Created (UTC)</th><th>Expires (UTC)</th><th>Status</th><th>Action</th></tr></thead>
                        <tbody>
                        <?php foreach ($invitations as $invite): ?>
                            <tr>
                                <td>#<?= h($invite['id']) ?></td>
                                <td><?= h(substr($invite['created_at'], 0, 19)) ?></td>
                                <td><?= h(substr($invite['expires_at'], 0, 19)) ?></td>
                                <td><?= h($invite['state']) ?></td>
                                <td><?php if ($invite['state'] === 'Open'): ?>
                                    <form method="post">
                                        <?php csrfInput(); ?>
                                        <input type="hidden" name="id" value="<?= h($invite['id']) ?>">
                                        <button name="action" value="revoke-invite">Revoke</button>
                                    </form>
                                <?php endif; ?></td>
                            </tr>
                        <?php endforeach; ?>
                        </tbody>
                    </table></div>
                <?php endif; ?>
            </section>
        <?php endif; ?>
    <?php endif; ?>
<footer class="site-footer">PocketBrain · A little thought goes a long way.</footer>
</main>
</body>
</html>
