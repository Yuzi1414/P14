"""账户存储：本地 JSON（开发） / Supabase Postgres（线上）。

线上部署在 Render 免费实例上，容器磁盘是临时的——每次休眠唤醒、重新部署都会
把 runtime/ 清空，用户注册的账号随之丢失（表现为「第二天账号就失效」）。
因此线上改用 Supabase 托管存储，账号写在云端表里，重启不丢。

选择后端的规则：
    设置了 SUPABASE_URL 与 SUPABASE_KEY  → 走 Supabase
    否则                                  → 走本地 runtime/users.json（本地开发不受影响）

Supabase 侧需要一张表（SQL 见 docs/supabase_setup.sql）：

    create table if not exists app_users (
        username      text primary key,
        password_hash text not null,
        salt          text not null,
        role          text not null default '用户',
        status        text not null default 'active',
        created_at    text not null default ''
    );
"""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import httpx

ROLES = ("admin", "用户")

TABLE = "app_users"
TIMEOUT = 15.0


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return digest.hex(), salt.hex()


def verify_password(password, salt_hex, expected_hash):
    digest, _ = hash_password(password, salt_hex)
    return secrets.compare_digest(digest, expected_hash)


class SupabaseAuth:
    """基于 Supabase REST API 的账号存储。

    只用到 service_role key（服务端调用，不经浏览器），因此不做行级权限细分；
    请勿把该 key 写进前端代码。
    """

    def __init__(self, url, key):
        self.base = url.rstrip("/") + f"/rest/v1/{TABLE}"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._ensure_admin()

    # ---- low level ----
    def _request(self, method, params=None, body=None, headers=None):
        hdrs = dict(self.headers)
        if headers:
            hdrs.update(headers)
        try:
            resp = httpx.request(
                method, self.base, params=params, json=body, headers=hdrs, timeout=TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"云端账户服务暂时不可用：{exc}") from exc
        if resp.status_code >= 400:
            raise ValueError(f"云端账户服务返回 {resp.status_code}：{resp.text[:200]}")
        if not resp.content:
            return []
        try:
            return resp.json()
        except json.JSONDecodeError:
            return []

    # ---- queries ----
    def users(self):
        rows = self._request("GET", params={"select": "*", "order": "created_at.asc"})
        return [dict(r) for r in rows]

    def find(self, username):
        key = (username or "").strip().lower()
        if not key:
            return None
        rows = self._request(
            "GET", params={"select": "*", "username": f"eq.{key}", "limit": "1"}
        )
        return dict(rows[0]) if rows else None

    # ---- operations ----
    def _ensure_admin(self):
        if self.find("admin"):
            return
        digest, salt = hash_password("admin123")
        try:
            self._request(
                "POST",
                body={
                    "username": "admin",
                    "password_hash": digest,
                    "salt": salt,
                    "role": "admin",
                    "status": "active",
                    "created_at": _now(),
                },
                headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            )
        except ValueError:
            # 并发创建时可能撞主键，忽略即可
            pass

    def register(self, username, password):
        """注册即开通：账号直接生效，不区分录入/复核，统一为普通成员。"""
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(password) < 4:
            raise ValueError("密码至少 4 位")
        if self.find(username):
            raise ValueError("用户名已存在")
        digest, salt = hash_password(password)
        try:
            self._request(
                "POST",
                body={
                    "username": username.lower(),
                    "password_hash": digest,
                    "salt": salt,
                    "role": "用户",
                    "status": "active",
                    "created_at": _now(),
                },
            )
        except ValueError as exc:
            # 主键冲突说明刚好被别的请求注册了
            if "409" in str(exc) or "duplicate" in str(exc).lower():
                raise ValueError("用户名已存在") from exc
            raise

    def login(self, username, password):
        user = self.find(username)
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise ValueError("用户名或密码错误")
        if user["status"] != "active":
            raise ValueError("账号尚未启用，请联系管理员")
        return dict(user)

    def reject(self, username):
        if (username or "").strip().lower() == "admin":
            raise ValueError("不能移除管理员账号")
        user = self.find(username)
        if not user:
            raise ValueError("用户不存在")
        self._request("DELETE", params={"username": f"eq.{user['username']}"})

    def delete_account(self, username, password):
        """自助注销：校验密码后永久删除该账号（管理员账号不可注销）。"""
        if (username or "").strip().lower() == "admin":
            raise ValueError("管理员账号不能注销")
        user = self.find(username)
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise ValueError("密码错误，无法注销")
        self._request("DELETE", params={"username": f"eq.{user['username']}"})

    def change_password(self, username, old_password, new_password):
        if len(new_password) < 4:
            raise ValueError("新密码至少 4 位")
        user = self.find(username)
        if not user or not verify_password(old_password, user["salt"], user["password_hash"]):
            raise ValueError("原密码错误")
        digest, salt = hash_password(new_password)
        self._request(
            "PATCH",
            params={"username": f"eq.{user['username']}"},
            body={"password_hash": digest, "salt": salt},
        )


class AuthStore:
    """本地 JSON 存储。接口与 SupabaseAuth 完全一致，可互换。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = {"users": []}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {"users": []}
        self._data.setdefault("users", [])
        self._ensure_admin()

    # ---- persistence ----
    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _ensure_admin(self):
        if not any(u["username"] == "admin" for u in self._data["users"]):
            digest, salt = hash_password("admin123")
            self._data["users"].append({
                "username": "admin", "password_hash": digest, "salt": salt,
                "role": "admin", "status": "active",
                "requested_role": "admin", "created_at": _now(),
            })
            self._save()

    # ---- queries ----
    def users(self):
        return [dict(u) for u in self._data["users"]]

    def find(self, username):
        key = (username or "").strip().lower()
        return next((u for u in self._data["users"] if u["username"].lower() == key), None)

    # ---- operations ----
    def register(self, username, password):
        """注册即开通：账号直接生效，不区分录入/复核，统一为普通成员。"""
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(password) < 4:
            raise ValueError("密码至少 4 位")
        if self.find(username):
            raise ValueError("用户名已存在")
        digest, salt = hash_password(password)
        self._data["users"].append({
            "username": username, "password_hash": digest, "salt": salt,
            "role": "用户", "status": "active",
            "created_at": _now(),
        })
        self._save()

    def login(self, username, password):
        user = self.find(username)
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise ValueError("用户名或密码错误")
        if user["status"] != "active":
            raise ValueError("账号尚未启用，请联系管理员")
        return dict(user)

    def reject(self, username):
        if username == "admin":
            raise ValueError("不能移除管理员账号")
        before = len(self._data["users"])
        self._data["users"] = [u for u in self._data["users"] if u["username"] != username]
        if len(self._data["users"]) == before:
            raise ValueError("用户不存在")
        self._save()

    def delete_account(self, username, password):
        """自助注销：校验密码后永久删除该账号（管理员账号不可注销）。"""
        if username == "admin":
            raise ValueError("管理员账号不能注销")
        user = self.find(username)
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise ValueError("密码错误，无法注销")
        self._data["users"] = [u for u in self._data["users"] if u["username"] != user["username"]]
        self._save()

    def change_password(self, username, old_password, new_password):
        if len(new_password) < 4:
            raise ValueError("新密码至少 4 位")
        user = self.find(username)
        if not user or not verify_password(old_password, user["salt"], user["password_hash"]):
            raise ValueError("原密码错误")
        digest, salt = hash_password(new_password)
        user.update(password_hash=digest, salt=salt)
        self._save()


def build_auth(local_path):
    """按环境变量选择后端：有 Supabase 配置就用云端，否则用本地文件。

    返回对象同时暴露 .backend 属性，便于界面上提示当前存储位置。
    """
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    if url and key:
        store = SupabaseAuth(url, key)
        store.backend = "supabase"
        return store
    store = AuthStore(local_path)
    store.backend = "local"
    return store
