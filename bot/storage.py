"""CSV-парсинг, синхронизация CSV -> SQLite, CRUD по state.db (см. BOT_DESIGN.md §3)."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REMINDER_INTERVAL = timedelta(hours=2)

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id                INTEGER PRIMARY KEY,
    date              TEXT NOT NULL,
    source            TEXT NOT NULL,
    amount            INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    done_by           TEXT,
    done_at           TEXT,
    last_reminded_at  TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipients (
    source       TEXT PRIMARY KEY,
    chat_id      INTEGER NOT NULL,
    is_owner     INTEGER NOT NULL DEFAULT 0,
    confirmed_at TEXT NOT NULL
);
"""


@dataclass
class Payment:
    id: int
    date: str
    source: str
    amount: int
    status: str
    done_by: str | None
    done_at: str | None
    last_reminded_at: str | None


@dataclass
class Recipient:
    source: str
    chat_id: int
    is_owner: bool
    confirmed_at: str


class Storage:
    def __init__(self, db_path: str | Path, csv_path: str | Path):
        self.db_path = Path(db_path)
        self.csv_path = Path(csv_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._csv_mtime: float | None = None

    def close(self) -> None:
        self._conn.close()

    # ---------- CSV -> DB sync (§3.2) ----------

    def sync_csv(self, force: bool = False) -> int:
        """Перечитывает payments.csv, если он изменился с прошлого раза
        (по mtime), и добавляет новые строки. Существующие статусы не трогает.
        Возвращает число добавленных платежей.
        """
        mtime = self.csv_path.stat().st_mtime
        if not force and self._csv_mtime is not None and mtime == self._csv_mtime:
            return 0
        self._csv_mtime = mtime

        rows = self._read_csv()
        existing_ids = {row[0] for row in self._conn.execute("SELECT id FROM payments")}
        new_rows = [row for row in rows if row["id"] not in existing_ids]
        if new_rows:
            now = datetime.now().isoformat(timespec="seconds")
            self._conn.executemany(
                """INSERT INTO payments (id, date, source, amount, created_at)
                   VALUES (:id, :date, :source, :amount, :created_at)""",
                [{**row, "created_at": now} for row in new_rows],
            )
            self._conn.commit()
        return len(new_rows)

    def _read_csv(self) -> list[dict]:
        with self.csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [
                {
                    "id": int(row["id"]),
                    "date": row["date"].strip(),
                    "source": row["source"].strip(),
                    "amount": int(row["amount"]),
                }
                for row in reader
            ]

    # ---------- payments (§4, §5) ----------

    def due_payments(self, now: datetime | None = None) -> list[Payment]:
        """date <= today AND status='pending' AND (last_reminded_at IS NULL
        OR now - last_reminded_at >= 2h) — см. §4."""
        now = now or datetime.now()
        today = now.date().isoformat()
        threshold = (now - REMINDER_INTERVAL).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """SELECT * FROM payments
               WHERE date <= ? AND status = 'pending'
                 AND (last_reminded_at IS NULL OR last_reminded_at <= ?)
               ORDER BY date, id""",
            (today, threshold),
        ).fetchall()
        return [self._row_to_payment(row) for row in rows]

    def get_payment(self, payment_id: int) -> Payment | None:
        row = self._conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return self._row_to_payment(row) if row else None

    def pending_payments(self, source: str | None = None) -> list[Payment]:
        """Для /pending: все неподтверждённые платежи, опционально по source."""
        if source is None:
            rows = self._conn.execute(
                "SELECT * FROM payments WHERE status = 'pending' ORDER BY date, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM payments WHERE status = 'pending' AND source = ? ORDER BY date, id",
                (source,),
            ).fetchall()
        return [self._row_to_payment(row) for row in rows]

    def upcoming_payments(self, days: int, source: str | None = None, today: str | None = None) -> list[Payment]:
        """Для /list: платежи в диапазоне [today, today + days], опционально по source."""
        start = today or datetime.now().date().isoformat()
        end = (datetime.fromisoformat(start) + timedelta(days=days)).date().isoformat()
        if source is None:
            rows = self._conn.execute(
                "SELECT * FROM payments WHERE date BETWEEN ? AND ? ORDER BY date, id",
                (start, end),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM payments WHERE date BETWEEN ? AND ? AND source = ? ORDER BY date, id",
                (start, end, source),
            ).fetchall()
        return [self._row_to_payment(row) for row in rows]

    def mark_reminded(self, payment_id: int, when: datetime | None = None) -> None:
        when = when or datetime.now()
        self._conn.execute(
            "UPDATE payments SET last_reminded_at = ? WHERE id = ?",
            (when.isoformat(timespec="seconds"), payment_id),
        )
        self._conn.commit()

    def mark_done(self, payment_id: int, done_by: str, when: datetime | None = None) -> None:
        when = when or datetime.now()
        self._conn.execute(
            "UPDATE payments SET status = 'done', done_by = ?, done_at = ? WHERE id = ?",
            (done_by, when.isoformat(timespec="seconds"), payment_id),
        )
        self._conn.commit()

    def list_sources(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT source FROM payments ORDER BY source").fetchall()
        return [row[0] for row in rows]

    # ---------- recipients (§3.2, §5) ----------

    def upsert_recipient(
        self,
        source: str,
        chat_id: int,
        is_owner: bool = False,
        confirmed_at: datetime | None = None,
    ) -> Recipient:
        confirmed_at = confirmed_at or datetime.now()
        confirmed_at_iso = confirmed_at.isoformat(timespec="seconds")
        self._conn.execute(
            """INSERT INTO recipients (source, chat_id, is_owner, confirmed_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET
                   chat_id = excluded.chat_id,
                   is_owner = excluded.is_owner,
                   confirmed_at = excluded.confirmed_at""",
            (source, chat_id, int(is_owner), confirmed_at_iso),
        )
        self._conn.commit()
        return Recipient(source=source, chat_id=chat_id, is_owner=is_owner, confirmed_at=confirmed_at_iso)

    def get_recipient(self, source: str) -> Recipient | None:
        row = self._conn.execute("SELECT * FROM recipients WHERE source = ?", (source,)).fetchone()
        return self._row_to_recipient(row) if row else None

    def get_recipient_by_chat_id(self, chat_id: int) -> Recipient | None:
        row = self._conn.execute("SELECT * FROM recipients WHERE chat_id = ?", (chat_id,)).fetchone()
        return self._row_to_recipient(row) if row else None

    def get_owner(self) -> Recipient | None:
        row = self._conn.execute("SELECT * FROM recipients WHERE is_owner = 1").fetchone()
        return self._row_to_recipient(row) if row else None

    def list_recipients(self) -> list[Recipient]:
        rows = self._conn.execute("SELECT * FROM recipients ORDER BY source").fetchall()
        return [self._row_to_recipient(row) for row in rows]

    # ---------- row conversion ----------

    @staticmethod
    def _row_to_payment(row: sqlite3.Row) -> Payment:
        return Payment(
            id=row["id"],
            date=row["date"],
            source=row["source"],
            amount=row["amount"],
            status=row["status"],
            done_by=row["done_by"],
            done_at=row["done_at"],
            last_reminded_at=row["last_reminded_at"],
        )

    @staticmethod
    def _row_to_recipient(row: sqlite3.Row) -> Recipient:
        return Recipient(
            source=row["source"],
            chat_id=row["chat_id"],
            is_owner=bool(row["is_owner"]),
            confirmed_at=row["confirmed_at"],
        )
