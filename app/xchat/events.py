"""Read decrypted XChat messages out of the bot browser's OPFS chat.db
and shape them like REST 1.1 dm_events so the worker pipeline can consume
both legacy DMs and XChat DMs through a single endpoint.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Optional

from .bridge import XChatBridgeRegistry

log = logging.getLogger(__name__)


async def fetch_chat_db_snapshot(auth_token: str, user_id: str) -> Optional[Path]:
    """Pull a fresh snapshot of chat_{userId}.db onto local disk.

    Returns the path to the snapshot, or ``None`` if the bot browser hasn't
    produced a chat.db yet (e.g. brand new profile). The caller owns the
    file and should delete it when done.
    """
    bridge = await XChatBridgeRegistry.get().acquire(auth_token, user_id)
    db_bytes = await bridge.read_chat_db()
    if not db_bytes:
        return None

    tmp = Path(tempfile.mkstemp(prefix="xchat-snap-", suffix=".db")[1])
    tmp.write_bytes(db_bytes)
    return tmp


def _query_messages(
    db_path: Path,
    bot_user_id: str,
    since_ts: Optional[int],
    include_outbound: bool = True,
) -> list[dict[str, Any]]:
    """Return XChat messages from a chat.db snapshot, shaped like dm_events.

    Both inbound (from peers) and outbound (sent by the bot itself) rows are
    returned by default; outbound rows are flagged with ``sender_is_owner``
    so the worker can use them to confirm send-side delivery on XChat-only
    conversations. Pass ``include_outbound=False`` for the legacy
    inbound-only behaviour.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        entry_cols = {c[1] for c in conn.execute("PRAGMA table_info(dm_entry)").fetchall()}
        attach_cols = {c[1] for c in conn.execute("PRAGMA table_info(dm_local_attachment)").fetchall()}
        has_owner_col = "sender_is_owner" in entry_cols
        has_attach_meta = bool(attach_cols)

        select_extra = ""
        join = ""
        if has_attach_meta:
            select_extra = (
                ", la.local_path AS attach_local_path, "
                "la.attachment_type AS attach_type, "
                "la.mime_type AS attach_mime, "
                "la.file_size AS attach_size"
            )
            # message_id on dm_local_attachment maps to dm_entry.entry_id when
            # the client has downloaded a media payload locally.
            join = "LEFT JOIN dm_local_attachment la ON la.message_id = e.entry_id "

        sql = (
            "SELECT e.entry_id, e.conversation_id, e.sequence_number, e.timestamp, "
            "e.sender_id, e.plain_text, e.message_status, e.has_attachment, "
            "e.attachment_types"
            + (", e.sender_is_owner AS owner_flag" if has_owner_col else "")
            + select_extra
            + " FROM dm_entry e "
            + join
            + "WHERE e.entry_type = 'message' AND e.plain_text IS NOT NULL "
        )
        params: list[Any] = []
        if not include_outbound:
            if has_owner_col:
                sql += "AND e.sender_is_owner = 0 "
            else:
                sql += "AND e.sender_id != ? "
                params.append(int(bot_user_id))
        if since_ts is not None:
            sql += "AND e.timestamp > ? "
            params.append(since_ts)
        sql += "ORDER BY e.timestamp DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    bot_id_int = int(bot_user_id)
    for r in rows:
        keys = r.keys()
        # Convert "{u1}:{u2}" XChat conv_id to legacy "{u1}-{u2}" so the
        # worker's BigInt cursor logic still works.
        conv_id_xchat = r["conversation_id"]
        conv_id_legacy = conv_id_xchat.replace(":", "-")
        sender = int(r["sender_id"])
        owner = (
            bool(r["owner_flag"]) if "owner_flag" in keys else (sender == bot_id_int)
        )
        attach: Optional[dict[str, Any]] = None
        if "attach_local_path" in keys and r["attach_local_path"]:
            attach = {
                "local_path": r["attach_local_path"],
                "type": r["attach_type"],
                "mime_type": r["attach_mime"],
                "size": r["attach_size"],
            }
        out.append(
            {
                "id": r["entry_id"],
                "event_type": "MessageCreate",
                "created_at": _ms_to_iso(r["timestamp"]),
                "created_at_ms": r["timestamp"],
                "sender_id": str(sender),
                "sender_is_owner": owner,
                "dm_conversation_id": conv_id_legacy,
                "text": r["plain_text"],
                "_xchat": True,
                "_sequence_number": r["sequence_number"],
                "_attachment": bool(r["has_attachment"]),
                "_attachment_types": r["attachment_types"],
                "_attachment_meta": attach,
            }
        )
    return out


def _ms_to_iso(ms: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


async def read_xchat_events(
    auth_token: str,
    bot_user_id: str,
    since_ts: Optional[int] = None,
    include_outbound: bool = True,
    include_reactions: bool = True,
    include_read_receipts: bool = False,
) -> list[dict[str, Any]]:
    """High-level helper: snapshot chat.db, return decrypted events.

    By default messages (inbound + outbound) and reactions are returned.
    Read receipts are off by default — they're noisy and the bot rarely
    cares which conversation the peer scrolled to.
    """
    snap = await fetch_chat_db_snapshot(auth_token, bot_user_id)
    if snap is None:
        return []
    try:
        out = _query_messages(snap, bot_user_id, since_ts, include_outbound=include_outbound)
        if include_reactions:
            out.extend(_query_reactions(snap, bot_user_id, since_ts))
        if include_read_receipts:
            out.extend(_query_read_receipts(snap, bot_user_id, since_ts))
        out.sort(key=lambda r: r.get("created_at_ms", 0), reverse=True)
        return out
    finally:
        try:
            snap.unlink()
        except Exception:  # noqa: BLE001
            pass


def _peer_from_conv(conv_id: str, bot_user_id: str) -> str:
    """Extract the non-bot user id from a "{u1}-{u2}" XChat conv id.

    XChat 1:1 conv ids encode both participants; for read receipts the
    schema doesn't carry sender_id, so the *other* user is the receipt
    sender by definition.
    """
    parts = [p for p in conv_id.replace(":", "-").split("-") if p]
    for p in parts:
        if p != bot_user_id:
            return p
    return ""


def _query_reactions(db_path: Path, bot_user_id: str, since_ts: Optional[int]) -> list[dict[str, Any]]:
    """Surface dm_reaction rows as v2-shape MessageReact events.

    Schema (X v2026): entry_sequence_number, attachment_id, emoji, conv_id,
    added_at_timestamp, added_at_sequence_number, added_by_user, deleted,
    deleted_at_sequence_number, should_notify.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    bot_id_int = int(bot_user_id)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(dm_reaction)").fetchall()}
        if not cols or "added_at_timestamp" not in cols:
            return []
        sql = (
            "SELECT entry_sequence_number, attachment_id, emoji, conv_id, "
            "added_at_timestamp, added_by_user, deleted "
            "FROM dm_reaction WHERE COALESCE(deleted, 0) = 0 "
        )
        params: list[Any] = []
        if since_ts is not None:
            sql += "AND added_at_timestamp > ? "
            params.append(since_ts)
        sql += "ORDER BY added_at_timestamp DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        ts = r["added_at_timestamp"] or 0
        sender = r["added_by_user"]
        conv = (r["conv_id"] or "").replace(":", "-")
        out.append({
            "id": f"react-{r['entry_sequence_number']}-{sender}",
            "event_type": "MessageReact",
            "created_at": _ms_to_iso(ts),
            "created_at_ms": ts,
            "sender_id": str(sender) if sender is not None else "",
            "sender_is_owner": int(sender or 0) == bot_id_int,
            "dm_conversation_id": conv,
            "reaction": r["emoji"],
            "target_event_id": r["entry_sequence_number"],
            "_xchat": True,
        })
    return out


def _query_read_receipts(db_path: Path, bot_user_id: str, since_ts: Optional[int]) -> list[dict[str, Any]]:
    """Surface dm_mark_read_event rows as v2-shape MessageRead events.

    Schema (X v2026): event_sequence_number, conversation_id, timestamp,
    seen_until_sequence_number. There is no sender_id column — receipts
    come from the peer side of the conv by definition; we infer sender
    from the conv id.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(dm_mark_read_event)").fetchall()}
        if not cols or "timestamp" not in cols:
            return []
        sql = (
            "SELECT event_sequence_number, conversation_id, timestamp, "
            "seen_until_sequence_number FROM dm_mark_read_event WHERE 1=1 "
        )
        params: list[Any] = []
        if since_ts is not None:
            sql += "AND timestamp > ? "
            params.append(since_ts)
        sql += "ORDER BY timestamp DESC LIMIT 200"
        rows = conn.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for r in rows:
        ts = r["timestamp"] or 0
        conv = (r["conversation_id"] or "").replace(":", "-")
        peer = _peer_from_conv(conv, bot_user_id)
        out.append({
            "id": f"read-{r['event_sequence_number']}",
            "event_type": "MessageRead",
            "created_at": _ms_to_iso(ts),
            "created_at_ms": ts,
            "sender_id": peer,
            "sender_is_owner": False,  # peer-side receipts only
            "dm_conversation_id": conv,
            "last_read_event_id": r["seen_until_sequence_number"],
            "_xchat": True,
        })
    return out
