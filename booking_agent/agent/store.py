from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import Slot

SCHEMA = """
CREATE TABLE IF NOT EXISTS slot_state (
    watch_id TEXT, slot_key TEXT, available INTEGER, last_alert TEXT,
    PRIMARY KEY (watch_id, slot_key)
);
CREATE TABLE IF NOT EXISTS events (
    at TEXT, watch_id TEXT, kind TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    watch_id TEXT PRIMARY KEY, slot_key TEXT, at TEXT, total_krw INTEGER, ref TEXT
);
CREATE TABLE IF NOT EXISTS blocked_hosts (
    host TEXT PRIMARY KEY, at TEXT, reason TEXT
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def slots_to_alert(self, watch_id: str, matches: list[Slot], now: datetime, realert: timedelta) -> list[Slot]:
        """새로 열린 슬롯, 또는 열린 채로 realert 이상 지난 슬롯만 반환하고 상태를 갱신."""
        rows = self.db.execute(
            "SELECT slot_key, available, last_alert FROM slot_state WHERE watch_id=?", (watch_id,)
        ).fetchall()
        prev = {k: (bool(a), datetime.fromisoformat(t) if t else None) for k, a, t in rows}
        current = {s.key for s in matches}

        out = []
        for s in matches:
            was_open, last = prev.get(s.key, (False, None))
            if not was_open or last is None or now - last >= realert:
                out.append(s)
                last = now
            self.db.execute(
                "INSERT OR REPLACE INTO slot_state VALUES (?,?,1,?)",
                (watch_id, s.key, last.isoformat() if last else None),
            )
        for key, (was_open, _) in prev.items():
            if was_open and key not in current:
                self.db.execute(
                    "UPDATE slot_state SET available=0 WHERE watch_id=? AND slot_key=?", (watch_id, key)
                )
        self.db.commit()
        return out

    def log(self, watch_id: str, kind: str, detail: dict | str = "") -> None:
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False, default=str)
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?)", (datetime.now().isoformat(), watch_id, kind, detail)
        )
        self.db.commit()

    def booked(self, watch_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM bookings WHERE watch_id=?", (watch_id,)).fetchone() is not None

    def record_booking(self, watch_id: str, slot_key: str, total_krw: int | None, ref: str) -> None:
        self.db.execute(
            "INSERT INTO bookings VALUES (?,?,?,?,?)",
            (watch_id, slot_key, datetime.now().isoformat(), total_krw, ref),
        )
        self.db.commit()

    def block_host(self, host: str, reason: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO blocked_hosts VALUES (?,?,?)", (host, datetime.now().isoformat(), reason)
        )
        self.db.commit()

    def blocked_reason(self, host: str) -> str | None:
        row = self.db.execute("SELECT reason FROM blocked_hosts WHERE host=?", (host,)).fetchone()
        return row[0] if row else None

    def unblock_host(self, host: str) -> bool:
        cur = self.db.execute("DELETE FROM blocked_hosts WHERE host=?", (host,))
        self.db.commit()
        return cur.rowcount > 0

    def spent_today(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(total_krw), 0) FROM bookings WHERE substr(at, 1, 10) = ?",
            (datetime.now().date().isoformat(),),
        ).fetchone()
        return int(row[0])
