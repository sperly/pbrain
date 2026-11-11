<?php
declare(strict_types=1);

final class HistoryError extends RuntimeException
{
    public function __construct(public readonly int $status, string $reason)
    {
        parent::__construct($reason);
    }
}

function historyId(mixed $value): string
{
    if (!is_string($value) || !preg_match('/\A[1-9][0-9]{0,19}\z/D', $value)
        || (strlen($value) === 20 && strcmp($value, '18446744073709551615') > 0)) {
        throw new HistoryError(400, 'invalid_id');
    }
    return $value;
}

function historyPage(mixed $value): int
{
    if (!is_string($value) || !preg_match('/\A[0-9]{1,7}\z/D', $value)) {
        throw new HistoryError(400, 'invalid_offset');
    }
    return (int) $value;
}

function historyBody(): array
{
    $raw = file_get_contents('php://input', false, null, 0, 131073);
    if ($raw === false || strlen($raw) > 131072) {
        throw new HistoryError(413, 'body_too_large');
    }
    try {
        $body = json_decode($raw, false, 32, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        throw new HistoryError(400, 'invalid_json');
    }
    if (!$body instanceof stdClass) {
        throw new HistoryError(400, 'invalid_json_object');
    }
    return (array) $body;
}

function historyDeviceLock(array $device): void
{
    $row = query(
        'SELECT d.id FROM devices d JOIN users u ON u.id = d.user_id
         WHERE d.id = ? AND d.user_id = ? AND d.revoked_at IS NULL
         AND u.disabled_at IS NULL FOR UPDATE', [$device['id'], $device['user_id']]
    )->fetch();
    if (!$row) {
        throw new HistoryError(401, 'invalid_device_credential');
    }
}

function ownedConversation(string $owner, string $id, bool $lock = false): array
{
    $row = query(
        'SELECT id, title, language_tag, created_at, last_activity_at FROM conversations
         WHERE user_id = ? AND id = ?' . ($lock ? ' FOR UPDATE' : ''), [$owner, $id]
    )->fetch();
    if (!$row) {
        throw new HistoryError(404, 'conversation_not_found');
    }
    $row['id'] = (string) $row['id'];
    return $row;
}

function activeConversation(array $device): ?string
{
    $id = query('SELECT conversation_id FROM device_active_conversations
                 WHERE user_id = ? AND device_id = ?', [$device['user_id'], $device['id']])->fetchColumn();
    return $id === false ? null : (string) $id;
}

function selectConversation(array $device, ?string $id): void
{
    query('DELETE FROM device_active_conversations WHERE user_id = ? AND device_id = ?',
          [$device['user_id'], $device['id']]);
    if ($id !== null) {
        query('INSERT INTO device_active_conversations (device_id, user_id, conversation_id)
               VALUES (?, ?, ?)', [$device['id'], $device['user_id'], $id]);
    }
}

function listConversations(array $device, int $offset): array
{
    $rows = query(
        'SELECT id, title, language_tag, created_at, last_activity_at FROM conversations
         WHERE user_id = ? ORDER BY last_activity_at DESC, id DESC LIMIT 51 OFFSET ' . $offset,
        [$device['user_id']]
    )->fetchAll();
    $more = count($rows) > 50;
    $rows = array_slice($rows, 0, 50);
    foreach ($rows as &$row) {
        $row['id'] = (string) $row['id'];
    }
    return ['conversations' => $rows, 'next_offset' => $more ? (string) ($offset + 50) : null,
            'active_conversation_id' => activeConversation($device)];
}

function conversationPage(array $device, string $id, string $after): array
{
    // Lock the thread so deletion cannot race the transcript read.
    return transaction(function () use ($device, $id, $after): array {
        $conversation = ownedConversation((string) $device['user_id'], $id, true);
        $turns = query(
            'SELECT id, client_turn_id, question_text, reply_text, reply_status, created_at
             FROM conversation_turns WHERE user_id = ? AND conversation_id = ? AND id > ?
             ORDER BY id LIMIT 21', [$device['user_id'], $id, $after]
        )->fetchAll();
        $more = count($turns) > 20;
        $turns = array_slice($turns, 0, 20);
        foreach ($turns as &$turn) {
            $turn['id'] = (string) $turn['id'];
        }
        return ['conversation' => $conversation, 'turns' => $turns,
                'next_after_id' => $more ? $turns[count($turns) - 1]['id'] : null];
    });
}

function validateTurn(array $body): array
{
    $uuid = $body['client_turn_id'] ?? null;
    if (!is_string($uuid) || !preg_match('/\A[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\z/D', $uuid)) {
        throw new HistoryError(400, 'invalid_client_turn_id');
    }
    foreach (['question_text', 'reply_text'] as $key) {
        if (!isset($body[$key]) || !is_string($body[$key]) || strlen($body[$key]) > 32768
            || str_contains($body[$key], "\0")) {
            throw new HistoryError(400, 'invalid_' . $key);
        }
    }
    if (trim($body['question_text']) === '' && trim($body['reply_text']) === '') {
        throw new HistoryError(400, 'empty_turn');
    }
    $status = $body['reply_status'] ?? 'complete';
    if (!in_array($status, ['complete', 'interrupted'], true)) {
        throw new HistoryError(400, 'invalid_reply_status');
    }
    $id = $body['conversation_id'] ?? null;
    if ($id !== null) {
        $id = historyId($id);
    }
    $language = $body['language_tag'] ?? null;
    if ($language !== null && (!is_string($language) || strlen($language) > 63
        || !preg_match('/\A[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*\z/D', $language))) {
        throw new HistoryError(400, 'invalid_language_tag');
    }
    return ['client_turn_id' => $uuid, 'conversation_id' => $id,
            'question_text' => $body['question_text'], 'reply_text' => $body['reply_text'],
            'reply_status' => $status, 'language_tag' => $language];
}

function saveConversationTurn(array $device, array $body): array
{
    $turn = validateTurn($body);
    return transaction(function () use ($device, $turn): array {
        // Serialize this device's retries, including two simultaneous first-turn saves.
        historyDeviceLock($device);
        $existing = query(
            'SELECT id, conversation_id, question_text, reply_text, reply_status
             FROM conversation_turns WHERE user_id = ? AND device_id = ? AND client_turn_id = ?',
            [$device['user_id'], $device['id'], $turn['client_turn_id']]
        )->fetch();
        if ($existing) {
            foreach (['question_text', 'reply_text', 'reply_status'] as $key) {
                if ($existing[$key] !== $turn[$key]) {
                    throw new HistoryError(409, 'turn_id_conflict');
                }
            }
            if ($turn['conversation_id'] !== null && $turn['conversation_id'] !== (string) $existing['conversation_id']) {
                throw new HistoryError(409, 'turn_id_conflict');
            }
            return ['conversation_id' => (string) $existing['conversation_id'],
                    'turn_id' => (string) $existing['id'], 'created' => false];
        }
        $id = $turn['conversation_id'];
        if ($id === null) {
            $title = trim(preg_replace('/\s+/u', ' ', $turn['question_text']) ?? '');
            $title = implode('', array_slice(preg_split('//u', $title, -1, PREG_SPLIT_NO_EMPTY), 0, 160));
            query('INSERT INTO conversations (user_id, title, language_tag) VALUES (?, ?, ?)',
                  [$device['user_id'], $title ?: 'Conversation', $turn['language_tag']]);
            $id = db()->lastInsertId();
        } else {
            ownedConversation((string) $device['user_id'], $id, true);
        }
        query('INSERT INTO conversation_turns
               (user_id, conversation_id, device_id, client_turn_id, question_text, reply_text, reply_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)',
              [$device['user_id'], $id, $device['id'], $turn['client_turn_id'],
               $turn['question_text'], $turn['reply_text'], $turn['reply_status']]);
        $turnId = db()->lastInsertId();
        query('UPDATE conversations SET last_activity_at = CURRENT_TIMESTAMP(6),
               language_tag = COALESCE(language_tag, ?) WHERE user_id = ? AND id = ?',
              [$turn['language_tag'], $device['user_id'], $id]);
        selectConversation($device, $id);
        return ['conversation_id' => $id, 'turn_id' => $turnId, 'created' => true];
    });
}

function changeActiveConversation(array $device, ?string $id): array
{
    return transaction(function () use ($device, $id): array {
        historyDeviceLock($device);
        if ($id !== null) {
            ownedConversation((string) $device['user_id'], $id, true);
        }
        selectConversation($device, $id);
        return ['active_conversation_id' => $id];
    });
}

function deleteConversation(array $device, string $id): array
{
    return transaction(function () use ($device, $id): array {
        historyDeviceLock($device);
        // Idempotent deletion; never disclose whether another account owns the ID.
        query('DELETE FROM conversations WHERE user_id = ? AND id = ?', [$device['user_id'], $id]);
        return ['deleted' => true];
    });
}
