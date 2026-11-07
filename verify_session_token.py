# -*- coding: utf-8 -*-
"""复现 app.py 里的令牌签名/校验算法，验证刷新恢复机制是否正确。"""
import hashlib, hmac, os, shutil, sys, tempfile
sys.path.insert(0, r"C:\Users\14724\Desktop\P14")
from reconcile.auth import AuthStore

SECRET = "0123456789abcdef" * 4

def sign(user):
    msg = (str(user.get("username", "")) + "|" + str(user.get("password_hash", ""))).encode("utf-8")
    return hmac.new(SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:32]

def make_token(user):
    return user["username"] + "." + sign(user)

def verify_token(auth, token):
    if not token or "." not in token:
        return None
    name, _, sig = token.partition(".")
    user = auth.find(name)
    if not user or user.get("status") != "active":
        return None
    if not hmac.compare_digest(sig, sign(user)):
        return None
    return dict(user)

d = tempfile.mkdtemp()
try:
    a = AuthStore(os.path.join(d, "users.json"))
    admin = a.login("admin", "admin123")
    tok = make_token(admin)
    assert verify_token(a, tok)["username"] == "admin", "valid token rejected"
    # 篡改签名
    assert verify_token(a, tok[:-3] + "abc") is None, "tampered token accepted"
    # 不存在的用户
    assert verify_token(a, "nobody.abc") is None
    # 空/格式错
    assert verify_token(a, "") is None and verify_token(a, "badformat") is None
    # 改密码后旧令牌失效
    a.change_password("admin", "admin123", "admin999")
    assert verify_token(a, tok) is None, "old token still valid after password change"
    new_tok = make_token(a.login("admin", "admin999"))
    assert verify_token(a, new_tok)["username"] == "admin"
    print("token mechanism ALL PASS")
finally:
    shutil.rmtree(d, ignore_errors=True)
