"""Repository for RAB audit records and approval events."""

import logging
from datetime import datetime, timezone

from aiosqlite import IntegrityError

from app.database import get_db

logger = logging.getLogger(__name__)

ALLOWED_RAB_COLUMNS = frozenset({
    "issue_key", "summary", "status", "validation_result",
    "sdl_approval", "sdm_approval",
    "rejection_reason", "rejected_by", "meeting_needed",
    "azure_pr_status", "azure_pipeline_status",
})

ALLOWED_EVENT_COLUMNS = frozenset({"issue_key", "step", "action", "approver", "reason"})


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
            keys = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            values = list(data.values())
            await db.execute(
                f"INSERT INTO rab_records ({keys}, created_at, updated_at) VALUES ({placeholders}, ?, ?)",
                values + [now, now],
            )
            row_id = db.total_changes
        await db.commit()
        return row_id

    async def record_validation(self, issue_key: str, valid: bool, detail: str = "") -> None:
        await self.upsert_record(issue_key, {
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

        status_map = {"approve": "approved", "reject": "rejected"}
        col = f"{step.lower()}_approval"
        if col not in ALLOWED_RAB_COLUMNS:
            raise ValueError(f"Invalid approval column: {col}")
        await db.execute(
            f"UPDATE rab_records SET {col} = ?, rejection_reason = ?, rejected_by = ?, status = ?, updated_at = ? WHERE issue_key = ?",
            (status_map.get(action, action), reason, approver, f"{step.lower()}_{action}d", datetime.now(timezone.utc).isoformat(), issue_key),
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
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error recording webhook event")
            raise

    async def get_all_records(self, limit: int = 50, offset: int = 0) -> list[dict]:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT * FROM rab_records ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    async def get_all_records_with_count(self, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        db = await get_db()
        count_row = await db.execute_fetchall("SELECT COUNT(*) FROM rab_records")
        total = count_row[0][0] if count_row else 0
        rows = await db.execute_fetchall(
            "SELECT * FROM rab_records ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows], total

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
