# -*- coding: utf-8 -*-
"""直接验证按账号隔离：路径隔离 + 空库 load() 返回 None + 保存取回。"""
import sys, hashlib, re, os, tempfile, shutil
sys.path.insert(0, r"C:\Users\14724\Desktop\P14")
from reconcile.storage import Store
from reconcile.demo import load_demo

def store_rel(uname):
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", uname).strip("_") or "user"
    tag = hashlib.sha256(uname.encode("utf-8")).hexdigest()[:8]
    return f"tasks/{slug}_{tag}.db"

for n in ["admin", "zhang", "李四", "a/b:c"]:
    print(n, "->", store_rel(n), flush=True)
assert store_rel("admin") != store_rel("zhang")
assert store_rel("李四") != store_rel("李四2")

d = tempfile.mkdtemp()
try:
    s = Store(os.path.join(d, "fresh.db"))
    print("空库 load():", s.load(), flush=True)
    assert s.load() is None

    p = os.path.join(d, "admin_xxx.db")
    s2 = Store(p)
    t = load_demo()
    s2.save(t)
    t2 = s2.load()
    print("保存后取回记录数:", len(t2.records), "原:", len(t.records), flush=True)
    assert t2 is not None and len(t2.records) == len(t.records)
    print("STORE ISOLATION ALL PASS", flush=True)
finally:
    try:
        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
