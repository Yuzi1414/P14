"""任务存储：本地 SQLite（开发） / Supabase Postgres（线上）。

背景：线上跑在 Render 免费实例，容器磁盘是临时的——休眠唤醒、重新部署都会把
runtime/ 清空，任务数据随之丢失。因此线上改用 Supabase 托管存储。

选择后端的规则与 auth.py 一致：
    设置了 SUPABASE_URL 与 SUPABASE_KEY  → 走 Supabase
    否则                                  → 走本地 SQLite 文件（本地开发不受影响）

Supabase 侧需要一张表（SQL 见 docs/supabase_setup.sql）：

    create table if not exists app_tasks (
        task_key      text primary key,
        schema_version integer not null default 1,
        payload       text not null,
        updated_at    text not null default ''
    );

task_key 由「账号 + 设备」拼成，与本地文件名一一对应。
"""
import gc
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .models import Task

TABLE = "app_tasks"
TIMEOUT = 20.0


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class Store:
    """本地 SQLite 存储，单槽位：一个库对应一份任务。"""

    def __init__(self, path="runtime/current.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS current_task (slot INTEGER PRIMARY KEY CHECK(slot=1), schema_version INTEGER NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, task):
        payload = json.dumps(task.to_dict(), ensure_ascii=False)
        # 目录可能已被 clear() 删掉，重新建出来
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS current_task (slot INTEGER PRIMARY KEY CHECK(slot=1), schema_version INTEGER NOT NULL, payload TEXT NOT NULL)")
            db.execute("INSERT INTO current_task VALUES (1,1,?) ON CONFLICT(slot) DO UPDATE SET schema_version=1,payload=excluded.payload", (payload,))

    def load(self):
        # 文件或目录可能已被 clear() 删除（账号注销后），此时视为空库
        if not self.path.exists():
            return None
        try:
            with self.connect() as db:
                row = db.execute("SELECT schema_version,payload FROM current_task WHERE slot=1").fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        if row[0] != 1:
            raise ValueError("任务存储版本不兼容，请保留数据并联系维护人员")
        return Task.from_dict(json.loads(row[1]))


class SupabaseStore:
    """Supabase 版存储。构造时传入 task_key（账号+设备 的唯一标识）。"""

    def __init__(self, url, key, task_key):
        self.base = url.rstrip("/") + f"/rest/v1/{TABLE}"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.task_key = task_key

    def _request(self, method, params=None, body=None, headers=None):
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)
        try:
            resp = httpx.request(
                method, self.base, params=params, json=body, headers=hdrs, timeout=TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise OSError(f"云端任务存储暂时不可用：{exc}") from exc
        if resp.status_code >= 400:
            raise OSError(f"云端任务存储返回 {resp.status_code}：{resp.text[:200]}")
        if not resp.content:
            return []
        try:
            return resp.json()
        except json.JSONDecodeError:
            return []

    def save(self, task):
        payload = json.dumps(task.to_dict(), ensure_ascii=False)
        self._request(
            "POST",
            body={
                "task_key": self.task_key,
                "schema_version": 1,
                "payload": payload,
                "updated_at": timestamp(),
            },
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )

    def load(self):
        rows = self._request(
            "GET",
            params={"select": "schema_version,payload", "task_key": f"eq.{self.task_key}", "limit": "1"},
        )
        if not rows:
            return None
        row = rows[0]
        if int(row.get("schema_version", 1)) != 1:
            raise ValueError("任务存储版本不兼容，请保留数据并联系维护人员")
        return Task.from_dict(json.loads(row["payload"]))

    def clear(self):
        """删除本条记录，用于账号注销。"""
        self._request("DELETE", params={"task_key": f"eq.{self.task_key}"})


def _supabase_conf():
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    return (url, key) if url and key else (None, None)


def build_store(local_path, task_key):
    """按环境变量选择后端。

    local_path : 本地 SQLite 文件路径
    task_key   : 云端主键（账号+设备），本地后端会忽略它
    返回对象带 .backend 属性（"supabase" / "local"）和 .clear() 方法。
    """
    url, key = _supabase_conf()
    if url and key:
        store = SupabaseStore(url, key, task_key)
        store.backend = "supabase"
        return store
    store = Store(local_path)
    store.backend = "local"

    # 本地后端补一个同名方法，注销账号时接口保持一致
    def _clear(_path=Path(local_path)):
        # Windows 上文件被 sqlite 连接占用时无法删除：先关连接、再删文件、再删空目录
        try:
            conn = sqlite3.connect(_path, timeout=10)
            conn.close()
        except sqlite3.Error:
            pass
        gc.collect()
        for attempt in (0, 1, 2):
            try:
                _path.unlink(missing_ok=True)
                break
            except OSError:
                time.sleep(0.15 * (attempt + 1))
        try:
            _path.parent.rmdir()
        except OSError:
            pass

    store.clear = _clear
    return store


def review_status(task, group_id):
    for item in reversed(task.reviews):
        if item.get("group_id") == group_id and item["action"] in ("确认", "驳回"):
            return "已确认" if item["action"] == "确认" else "已驳回"
    return "待复核"
