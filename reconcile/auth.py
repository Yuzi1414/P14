"""Minimal account store for the deployed prototype.

Flow: register → immediately active → login. No admin approval.
Passwords are salted PBKDF2-HMAC-SHA256, never stored in plaintext.
Accounts: admin (账号管理) / 用户 (全部业务操作，不区分录入与复核).
"""
import hashlib
import json
import secrets
import time
from pathlib import Path

ROLES = ("admin", "用户")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return digest.hex(), salt.hex()


def verify_password(password, salt_hex, expected_hash):
    digest, _ = hash_password(password, salt_hex)
    return secrets.compare_digest(digest, expected_hash)


class AuthStore:
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
        key = username.strip().lower()
        return next((u for u in self._data["users"] if u["username"].lower() == key), None)

    # ---- operations ----
    def register(self, username, password):
        """注册即开通：账号直接生效，不区分录入/复核，统一为普通成员。"""
        username = username.strip()
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
