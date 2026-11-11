"""Shared conversation operations; local storage remains an offline cache."""
from transport import api


def listing(base, token, request=api):
    rows = []
    offset = "0"
    while True:
        page = request(base, "conversations", token, params={"offset": offset})
        rows.extend(page["conversations"])
        if page["next_offset"] is None:
            return rows, page["active_conversation_id"]
        offset = page["next_offset"]


def transcript(base, token, key, request=api):
    turns = []
    after = "0"
    while True:
        page = request(base, "conversation", token, params={"id": key, "after_id": after})
        turns.extend({"id": turn["client_turn_id"], "question": turn["question_text"],
                      "reply": turn["reply_text"] or "",
                      "interrupted": turn["reply_status"] == "interrupted"}
                     for turn in page["turns"])
        if page["next_after_id"] is None:
            return {"title": page["conversation"]["title"], "turns": turns,
                    "language_tag": page["conversation"]["language_tag"]}
        after = page["next_after_id"]


def sync(base, token, cached, request=api):
    rows, active = listing(base, token, request)
    # Replace the index so server-side deletions also remove cached transcripts.
    threads = {row["id"]: {**cached.get(row["id"], {"turns": []}),
                            "title": row["title"], "language_tag": row["language_tag"]}
               for row in reversed(rows)}
    if active in threads:
        threads[active] = transcript(base, token, active, request)
    return {"active": active if active in threads else None, "threads": threads}


def save(base, token, pending, request=api):
    return request(base, "turn-save", token, payload={
        "client_turn_id": pending["id"], "conversation_id": pending["thread"],
        **pending["transcript"],
    })
