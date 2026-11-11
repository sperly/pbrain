<?php
declare(strict_types=1);

require_once __DIR__ . '/conversations.php';

function dashboardHistory(string $owner, array $params): array
{
    $device = ($params['device'] ?? '') === '' ? null : historyId($params['device']);
    $selected = ($params['conversation'] ?? '') === '' ? null : historyId($params['conversation']);
    $offset = historyPage($params['offset'] ?? '0');
    $after = ($params['after_id'] ?? '0') === '0' ? '0' : historyId($params['after_id']);
    if ($device !== null && !query('SELECT id FROM devices WHERE user_id = ? AND id = ?', [$owner, $device])->fetch()) {
        throw new HistoryError(404, 'Device not found.');
    }
    $filter = '';
    $bindings = [$owner];
    if ($device !== null) {
        $filter = ' AND EXISTS (SELECT 1 FROM conversation_turns dt WHERE dt.user_id = c.user_id
                               AND dt.conversation_id = c.id AND dt.device_id = ?)';
        $bindings[] = $device;
    }
    $rows = query(
        'SELECT c.id, c.title, c.last_activity_at, c.language_tag,
            (SELECT COUNT(*) FROM conversation_turns t WHERE t.user_id = c.user_id AND t.conversation_id = c.id) AS turn_count
         FROM conversations c WHERE c.user_id = ?' . $filter . '
         ORDER BY c.last_activity_at DESC, c.id DESC LIMIT 26 OFFSET ' . $offset, $bindings
    )->fetchAll();
    $next = count($rows) > 25 ? (string) ($offset + 25) : null;
    $thread = null;
    $turns = [];
    $nextAfter = null;
    if ($selected !== null) {
        // Lock through the read so deletion cannot leave metadata with a partial transcript.
        [$thread, $turns, $nextAfter] = transaction(function () use ($owner, $selected, $device, $after): array {
            $thread = ownedConversation($owner, $selected, true);
            if ($device !== null && !query(
                'SELECT id FROM conversation_turns WHERE user_id = ? AND conversation_id = ? AND device_id = ? LIMIT 1',
                [$owner, $selected, $device]
            )->fetch()) {
                throw new HistoryError(404, 'Conversation not found for this device.');
            }
            $turns = query(
                'SELECT t.id, t.question_text, t.reply_text, t.reply_status, t.created_at,
                        d.id AS device_id, d.display_name, d.revoked_at
                 FROM conversation_turns t JOIN devices d ON d.id = t.device_id AND d.user_id = t.user_id
                 WHERE t.user_id = ? AND t.conversation_id = ? AND t.id > ? ORDER BY t.id LIMIT 21',
                [$owner, $selected, $after]
            )->fetchAll();
            $more = count($turns) > 20;
            $turns = array_slice($turns, 0, 20);
            return [$thread, $turns, $more ? (string) $turns[count($turns) - 1]['id'] : null];
        });
    }
    return ['device' => $device, 'selected' => $selected, 'offset' => $offset, 'after' => $after,
            'rows' => array_slice($rows, 0, 25), 'next_offset' => $next,
            'thread' => $thread, 'turns' => $turns, 'next_after' => $nextAfter];
}
