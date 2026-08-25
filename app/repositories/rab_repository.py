"""Repository for RAB audit records and approval events."""

import logging
from datetime import datetime, timedelta, timezone

from aiosqlite import IntegrityError

from app.database import get_db

logger = logging.getLogger(__name__)

ALLOWED_RAB_COLUMNS = frozenset({
    "issue_key", "summary", "status", "validation_result",
    "sdl_approval", "sdm_approval",
    "sdl_approval_id", "sdm_approval_id",
    "creator", "assignee",
    "rejection_reason", "rejected_by", "meeting_needed",
})

ALLOWED_EVENT_COLUMNS = frozenset({"issue_key", "step", "action", "approver", "reason"})
_APPROVAL_STATUS_MAP = {"approve": "approved", "reject": "rejected"}
_PENDING_WHERE = "sdl_approval = 'requested' OR sdm_approval = 'requested'"
_FAILURE_STATUSES = ("validation_failed", "sdl_rejected", "sdm_rejected")


class RabRepository:

    def _validate_columns(self, data: dict, allowed: frozenset) -> None:
        bad = [k for k in data if k not in allowed]
        if bad:
            raise ValueError(f"Invalid column names: {bad}")

    async def upsert_record(self, issue_key: str, data: dict) -> int:
        self._validate_columns(data, ALLOWED_RAB_COLUMNS)
        db = await get_db()
        existing = await db.execute_fetchall(
            "SELECT id FROM rab_records WHERE issue_key = ?", (issue_key,)
        )
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in data)
            values = list(data.values()) + [now, issue_key]
            await db.execute(
                f"UPDATE rab_records SET {sets}, updated_at = ? WHERE issue_key = ?",
                values,
            )
            row_id = existing[0][0]
        else:
            payload = dict(data)
            payload["issue_key"] = issue_key
            keys = ", ".join(payload.keys())
            placeholders = ", ".join("?" for _ in payload)
            values = list(payload.values())
            cursor = await db.execute(
                f"INSERT INTO rab_records ({keys}, created_at, updated_at) VALUES ({placeholders}, ?, ?)",
                values + [now, now],
            )
            row_id = cursor.lastrowid
        await db.commit()
        return row_id

    async def record_validation(self, issue_key: str, valid: bool, detail: str = "") -> None:
        await self.upsert_record(issue_key, {
            "issue_key": issue_key,
            "status": "validated" if valid else "validation_failed",
            "validation_result": detail,
        })

    async def record_approval_event(
        self, issue_key: str, step: str, action: str,
        approver: str = "", reason: str = "",
    ) -> None:
        self._validate_columns({"step": step, "action": action}, ALLOWED_EVENT_COLUMNS)
        db = await get_db()
        await db.execute(
            "INSERT INTO approval_events (issue_key, step, action, approver, reason) VALUES (?, ?, ?, ?, ?)",
            (issue_key, step, action, approver, reason),
        )
        await db.commit()

        col = f"{step.lower()}_approval"
        if col not in ALLOWED_RAB_COLUMNS:
            raise ValueError(f"Invalid approval column: {col}")
        approval_status = _APPROVAL_STATUS_MAP.get(action, action)
        record_status = f"{step.lower()}_{approval_status}"
        is_reject = action == "reject"
        await db.execute(
            f"UPDATE rab_records SET {col} = ?, rejection_reason = ?, rejected_by = ?, status = ?, updated_at = ? WHERE issue_key = ?",
            (
                approval_status,
                reason if is_reject else "",
                approver if is_reject else "",
                record_status,
                datetime.now(timezone.utc).isoformat(),
                issue_key,
            ),
        )
        await db.commit()

    async def record_webhook_event(self, event_id: str, issue_key: str, event_type: str) -> bool:
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO webhook_events (event_id, issue_key, event_type) VALUES (?, ?, ?)",
                (event_id, issue_key, event_type),
            )
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False
        except Exception as e:
            await db.rollback()
            logger.exception("Unexpected error recording webhook event: %s", e)
            raise

    async def record_field_changes(self, issue_key: str, changelog: dict | None) -> None:
        if not changelog or not isinstance(changelog.get("items"), list):
            return
        db = await get_db()
        author_data = changelog.get("author") or {}
        author = author_data.get("displayName") or author_data.get("accountId") or author_data.get("name") or ""
        for item in changelog["items"]:
            if not isinstance(item, dict) or not item.get("field"):
                continue
            await db.execute(
                "INSERT INTO field_change_events (issue_key, field, from_value, to_value, author) VALUES (?, ?, ?, ?, ?)",
                (issue_key, str(item.get("field", "")), str(item.get("fromString") or item.get("from") or ""), str(item.get("toString") or item.get("to") or ""), author),
            )
        await db.commit()

    async def get_field_changes(self, issue_key: str) -> list[dict]:
        db = await get_db()
        rows = await db.execute_fetchall("SELECT * FROM field_change_events WHERE issue_key = ? ORDER BY created_at, id", (issue_key,))
        return [dict(r) for r in rows]

    async def update_webhook_event_status(self, event_id: str, result: str) -> None:
        db = await get_db()
        await db.execute(
            "UPDATE webhook_events SET status = ? WHERE event_id = ?",
            (result, event_id),
        )
        await db.commit()

    async def get_all_records_with_count(self, limit: int = 50, offset: int = 0, status: str = "", q: str = "") -> tuple[list[dict], int]:
        db = await get_db()
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if q:
            # Escape LIKE wildcards and limit length to prevent DoS/enumeration
            if len(q) > 100:
                q = q[:100]
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("issue_key LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count_row = await db.execute_fetchall(f"SELECT COUNT(*) FROM rab_records {where}", params)
        total = count_row[0][0] if count_row else 0
        rows = await db.execute_fetchall(
            f"SELECT * FROM rab_records {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [dict(r) for r in rows], total

    async def get_status_counts(self) -> dict[str, int]:
        db = await get_db()
        rows = await db.execute_fetchall("SELECT status, COUNT(*) AS c FROM rab_records GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    @staticmethod
    def _parse_ts(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None

    async def get_pending_approval_count(self) -> int:
        db = await get_db()
        rows = await db.execute_fetchall(
            f"SELECT COUNT(*) AS c FROM rab_records WHERE {_PENDING_WHERE}",
        )
        return rows[0]["c"] if rows else 0

    async def get_aging_records(self, days: int = 2) -> list[dict]:
        """Records still waiting for an approval decision for longer than ``days``."""
        db = await get_db()
        rows = await db.execute_fetchall(
            f"SELECT * FROM rab_records WHERE {_PENDING_WHERE} ORDER BY updated_at ASC",
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [
            dict(r) for r in rows
            if (updated := self._parse_ts(r["updated_at"])) and updated < cutoff
        ]

    async def get_recent_failures(self, limit: int = 5) -> list[dict]:
        """Most recent validation failures and rejections."""
        db = await get_db()
        placeholders = ", ".join("?" for _ in _FAILURE_STATUSES)
        rows = await db.execute_fetchall(
            f"SELECT * FROM rab_records WHERE status IN ({placeholders}) ORDER BY updated_at DESC LIMIT ?",
            (*_FAILURE_STATUSES, limit),
        )
        return [dict(r) for r in rows]

    async def get_webhook_events(self, limit: int = 100, offset: int = 0) -> list[dict]:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT * FROM webhook_events ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    async def get_webhook_events_with_count(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        db = await get_db()
        count_row = await db.execute_fetchall("SELECT COUNT(*) FROM webhook_events")
        total = count_row[0][0] if count_row else 0
        rows = await db.execute_fetchall(
            "SELECT * FROM webhook_events ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows], total

    async def get_webhook_event(self, event_id: str) -> dict | None:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT * FROM webhook_events WHERE event_id = ?", (event_id,)
        )
        return dict(rows[0]) if rows else None

    async def get_record(self, issue_key: str) -> dict | None:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT * FROM rab_records WHERE issue_key = ?", (issue_key,)
        )
        return dict(rows[0]) if rows else None

    async def get_approval_events(self, issue_key: str) -> list[dict]:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT * FROM approval_events WHERE issue_key = ? ORDER BY created_at", (issue_key,)
        )
        return [dict(r) for r in rows]

    async def delete_record(self, issue_key: str) -> None:
        """Remove all persisted state for an issue (used by the demo flow to allow re-runs)."""
        db = await get_db()
        await db.execute("DELETE FROM rab_records WHERE issue_key = ?", (issue_key,))
        await db.execute("DELETE FROM approval_events WHERE issue_key = ?", (issue_key,))
        await db.commit()
