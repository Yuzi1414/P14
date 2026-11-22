"""共享空间（发布 / 载入）与云端连通自检。

线上「发布到云端共享」写的是 Supabase 的 app_tasks 表（task_key = shared_global）。
这里用假 httpx 验证读写协议，用临时目录验证本地后端的回环，避免测试依赖真实云端。
"""
import json
from pathlib import Path

import httpx
import pytest

from reconcile.demo import load_demo
from reconcile.storage import Store, SupabaseStore, build_store


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status_code = status
        self._payload = [] if payload is None else payload
        self.content = b"{}"
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def fake_supabase(monkeypatch):
    """最小的 app_tasks 服务端：主键 task_key，支持插入 / 查询 / 删除。"""
    rows = {}
    calls = []

    def request(method, url, params=None, json=None, headers=None, timeout=None):
        calls.append({"method": method, "params": params or {}, "body": json, "headers": headers or {}})
        params = params or {}
        if method == "POST":
            rows[json["task_key"]] = dict(json)
            return FakeResponse([json])
        if method == "GET":
            select = params.get("select", "")
            key = str(params.get("task_key", "")).removeprefix("eq.")
            row = rows.get(key) if key else next(iter(rows.values()), None)
            if row is None:
                return FakeResponse([])
            if select == "updated_at":
                return FakeResponse([{"updated_at": row["updated_at"]}])
            return FakeResponse([{"schema_version": row["schema_version"], "payload": row["payload"]}])
        if method == "DELETE":
            rows.pop(str(params.get("task_key", "")).removeprefix("eq."), None)
            return FakeResponse([])
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(httpx, "request", request)
    return rows, calls


def test_local_store_publish_and_meta(tmp_path):
    """本地后端：发布后能读回同一份任务，并给出最后写入时间。"""
    store = build_store(tmp_path / "shared_global.db", "shared_global")
    assert store.backend == "local"
    assert store.ping() is True
    assert store.load() is None

    task = load_demo()
    store.save(task)
    again = store.load()
    assert again is not None
    assert again.name == task.name
    assert len(again.records) == len(task.records)

    meta = store.meta()
    assert meta and meta["updated_at"]


def test_supabase_store_publish_and_meta(monkeypatch):
    """云端后端：写入用 merge-duplicates 覆盖同一 task_key，读回校验字段齐全。"""
    rows, calls = fake_supabase(monkeypatch)
    store = SupabaseStore("https://demo.supabase.co", "service-key", "shared_global")
    assert store.ping() is True

    task = load_demo()
    store.save(task)

    assert "shared_global" in rows
    post = next(call for call in calls if call["method"] == "POST")
    assert post["body"]["task_key"] == "shared_global"
    assert post["body"]["schema_version"] == 1
    assert post["headers"]["Prefer"] == "resolution=merge-duplicates,return=representation"

    loaded = store.load()
    assert loaded is not None and loaded.name == task.name
    assert len(loaded.records) == len(task.records)

    meta = store.meta()
    assert meta and meta["updated_at"]


def test_supabase_store_reports_failure(monkeypatch):
    """云端返回错误时抛 OSError，界面才能把原因显示给用户而不是白屏。"""
    def bad_request(*args, **kwargs):
        return FakeResponse({"message": "relation does not exist"}, status=404)

    monkeypatch.setattr(httpx, "request", bad_request)
    store = SupabaseStore("https://demo.supabase.co", "service-key", "shared_global")
    with pytest.raises(OSError) as excinfo:
        store.ping()
    assert "404" in str(excinfo.value)


def test_publish_then_load_as_another_device(tmp_path, monkeypatch):
    """发布到共享空间后，另一个账号/设备能载入到同一份任务。"""
    import reconcile.storage as storage

    # app.py 里 store 和 shared_store 都用 build_store，这里按文件名分开落盘，
    # 模拟「本设备任务」与「全局共享空间」两个不同的库。
    monkeypatch.setattr(storage, "Store", lambda path: Store(tmp_path / Path(str(path)).name))

    shared = build_store(tmp_path / "shared_global.db", "shared_global")
    shared.save(load_demo())

    other_device = build_store(tmp_path / "someone_else_00000000.db", "someone_else_00000000")
    assert other_device.load() is None
    other_device.save(shared.load())
    assert other_device.load().name == shared.load().name
