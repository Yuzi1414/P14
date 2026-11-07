import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Task


def timestamp():
    # Windows installations may not include IANA tzdata.
    from datetime import timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class Store:
    def __init__(self, path="runtime/current.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS current_task (slot INTEGER PRIMARY KEY CHECK(slot=1), schema_version INTEGER NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, task):
        payload = json.dumps(task.to_dict(), ensure_ascii=False)
        with self.connect() as db:
            db.execute("INSERT INTO current_task VALUES (1,1,?) ON CONFLICT(slot) DO UPDATE SET schema_version=1,payload=excluded.payload", (payload,))

    def load(self):
        with self.connect() as db:
            row = db.execute("SELECT schema_version,payload FROM current_task WHERE slot=1").fetchone()
        if not row:
            return None
        if row[0] != 1:
            raise ValueError("任务存储版本不兼容，请保留数据并联系维护人员")
        return Task.from_dict(json.loads(row[1]))


def review_status(task, group_id):
    for item in reversed(task.reviews):
        if item.get("group_id") == group_id and item["action"] in ("确认", "驳回"):
            return "已确认" if item["action"] == "确认" else "已驳回"
    return "待复核"

