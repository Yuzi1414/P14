# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"C:\Users\14724\Desktop\P14")
from reconcile.auth import AuthStore
import tempfile, os, shutil

d = tempfile.mkdtemp()
try:
    a = AuthStore(os.path.join(d, "users.json"))
    assert a.find("admin")["role"] == "admin" and a.find("admin")["status"] == "active"
    try:
        a.login("admin", "wrong"); raise SystemExit("FAIL: wrong pw accepted")
    except ValueError: pass
    assert a.login("admin", "admin123")["role"] == "admin"
    # 注册即开通，无需角色，统一为"用户"
    a.register("zhang", "pass123")
    u = a.login("zhang", "pass123")
    assert u["role"] == "用户" and u["status"] == "active", u
    try:
        a.register("zhang", "x123"); raise SystemExit("FAIL: dup user")
    except ValueError: pass
    a.change_password("zhang", "pass123", "newpass456")
    try:
        a.login("zhang", "pass123"); raise SystemExit("FAIL: old pw works")
    except ValueError: pass
    assert a.login("zhang", "newpass456")["username"] == "zhang"
    a.reject("zhang"); assert a.find("zhang") is None
    try:
        a.reject("admin"); raise SystemExit("FAIL: admin removed")
    except ValueError: pass
    # 自助注销：密码错误拒绝、正确密码注销、管理员不可注销
    a.register("lisi", "pw1234")
    try:
        a.delete_account("lisi", "wrongpw"); raise SystemExit("FAIL: bad pw still deleted")
    except ValueError: pass
    assert a.find("lisi") is not None
    a.delete_account("lisi", "pw1234")
    assert a.find("lisi") is None, "delete_account did not remove user"
    try:
        a.delete_account("admin", "admin123"); raise SystemExit("FAIL: admin deleted")
    except ValueError: pass
    print("auth flow (no-role + self-delete) ALL PASS")
finally:
    shutil.rmtree(d, ignore_errors=True)
