"""操作记录（审计轨迹）：谁在什么时候做了什么。

「用户与权限」页光有「最近操作时间」只能说明这个账号动过，回答不了
「他到底做了哪几步」。这里按条记录成功完成的业务动作：登录、确认字段映射、
建立对账、提交复核结论、人工建立关联、发布共享、修改密码、管理员改角色等。

后端选择与账户 / 任务存储一致：
    设置了 SUPABASE_URL 与 SUPABASE_KEY  → 写 Supabase 的 app_audit_log 表
    否则                                  → 写本地 runtime/audit.db（SQLite）

Supabase 侧建表 SQL 见 docs/supabase_setup.sql。线上若还没建表，读取时会报错：
页面只提示「暂时读不到」，不影响登录、导入和对账；写入失败同样静默忽略，
日志不能反过来阻断业务。
"""
import sqlite3
from pathlib import Path

import httpx

from .storage import _supabase_conf, timestamp

TABLE = "app_audit_log"
TIMEOUT = 15.0

# 与 SELECT 列顺序一致
COLUMNS = ("at", "actor", "role", "action", "detail", "page", "task")


def _text(value, limit):
    """压成单行并截断，避免一条日志把表格撑开。"""
    return " ".join(str(value or "").split())[:limit]


def _event(actor, role, action, detail="", page="", task=""):
    return {
        "at": timestamp(),
        "actor": _text(actor, 60),
        "role": _text(role, 20),
        "action": _text(action, 40),
        "detail": _text(detail, 300),
        "page": _text(page, 30),
        "task": _text(task, 80),
    }


class AuditStore:
    """本地 SQLite 存储。接口与 SupabaseAudit 一致，可互换。"""

    backend = "local"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',"
                "action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',"
                "page TEXT NOT NULL DEFAULT '', task TEXT NOT NULL DEFAULT '')"
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, actor, role, action, detail="", page="", task=""):
        event = _event(actor, role, action, detail, page, task)
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit_log(at,actor,role,action,detail,page,task) VALUES(?,?,?,?,?,?,?)",
                tuple(event[key] for key in COLUMNS),
            )
        return event

    def recent(self, limit=200, actor=None):
        limit = max(1, min(int(limit), 2000))
        sql = "SELECT " + ",".join(COLUMNS) + " FROM audit_log"
        args = []
        if actor:
            sql += " WHERE actor = ?"
            args.append(actor)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, args).fetchall()
        return [dict(zip(COLUMNS, row)) for row in rows]


class SupabaseAudit:
    """Supabase 版操作记录。只写入服务端，浏览器拿不到。"""

    backend = "supabase"

    def __init__(self, url, key):
        self.base = url.rstrip("/") + f"/rest/v1/{TABLE}"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _request(self, method, params=None, body=None):
        try:
            resp = httpx.request(
                method, self.base, params=params, json=body, headers=self.headers, timeout=TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise OSError(f"云端操作记录暂时不可用：{exc}") from exc
        if resp.status_code >= 400:
            text = resp.text or ""
            missing_table = resp.status_code == 404 and (
                "PGRST205" in text or "42P01" in text or "does not exist" in text
            )
            if missing_table:
                raise OSError(
                    "线上还没有建操作记录表：请在 Supabase → SQL Editor 执行 "
                    "docs/supabase_setup.sql 里的 app_audit_log 建表语句，然后刷新本页。"
                )
            raise OSError(f"云端操作记录返回 {resp.status_code}：{text[:200]}")
        if not resp.content:
            return []
        try:
            return resp.json()
        except ValueError:
            return []

    def add(self, actor, role, action, detail="", page="", task=""):
        self._request("POST", body=_event(actor, role, action, detail, page, task))

    def recent(self, limit=200, actor=None):
        limit = max(1, min(int(limit), 2000))
        params = {"select": "*", "order": "id.desc", "limit": str(limit)}
        if actor:
            params["actor"] = f"eq.{actor}"
        rows = self._request("GET", params=params)
        return [dict(row) for row in rows]


def build_audit(local_path):
    """按环境变量选择后端：有 Supabase 配置就写云端，否则写本地 SQLite。"""
    url, key = _supabase_conf()
    if url and key:
        return SupabaseAudit(url, key)
    return AuditStore(local_path)
