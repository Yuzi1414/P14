"""Actual local inference plus client-offline import/review/export/restore evidence."""
import asyncio
import io
import json
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook
from reconcile.ai import LocalAI, MODEL, PROMPT_VERSION
from reconcile.demo import load_demo
from reconcile.engine import candidate_records
from reconcile.exporter import money, workbook_bytes
from reconcile.models import FIELDS
from reconcile.service import accept_candidate, record_review
from reconcile.storage import Store, timestamp


def local_only_connect(original):
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("Verification guard: non-loopback network disabled")
        return original(sock, address)
    return connect


async def verify():
    client = LocalAI()
    if not client.health():
        raise RuntimeError("qwen3:4b not ready; run scripts/setup-ai.ps1")
    task = load_demo()
    rows = []
    mapping_payload = {"standard_fields": FIELDS, "columns": ["缴费单号", "缴费金额", "学生姓名", "缴费日期"],
                       "sample_rows": [{"缴费单号": "000001", "缴费金额": "1000.00", "学生姓名": "演示学生甲", "缴费日期": "2026-10-01"}]}
    start = time.perf_counter()
    result = await client.complete("mapping", mapping_payload)
    assert any(m["field"] == "amount" and m["column"] == "缴费金额" for m in result["mappings"])
    rows.append({"kind": "mapping", "result": result, "elapsed_seconds": round(time.perf_counter() - start, 3)})
    bank = next(r for r in task.records if r.source == "bank" and not r.business_id)
    candidates = candidate_records(task, bank.id, "bank-fees")
    minimal = lambda r: {"id": r.id, "business_id": r.business_id, "object_id": r.object_id, "name": r.name,
                         "date": r.date, "amount": money(r.amount_cents), "direction": r.direction}
    payload = {"bank": minimal(bank), "candidates": [minimal(r) for _, r in candidates]}
    start = time.perf_counter()
    result = await client.complete("candidate", payload)
    rows.append({"kind": "candidate", "result": result, "elapsed_seconds": round(time.perf_counter() - start, 3)})
    fee = next(r for _, r in candidates if r.business_id == "NO-ID")
    assert result["candidate_id"] == fee.id, "真实模型未选中合成样例预期候选"
    accept_candidate(task, bank.id, fee.id, "bank-fees", "本地验证员", "合成样例已知关联，仅用于验证")
    ledger = next(r for r in task.records if r.source == "ledger" and r.business_id == "NO-ID")
    accept_candidate(task, bank.id, ledger.id, "bank-ledger", "本地验证员", "合成样例已知关联，仅用于验证")
    group = next(g for g in task.groups if bank.id in g.record_ids)
    assert group.status == "已匹配"
    record_review(task, group.id, "确认", "本地验证员", "三方重算完成")
    for i, item in enumerate(rows):
        task.ai_logs.append({"id": "real-verification-" + str(i), "model": MODEL, "prompt_version": PROMPT_VERSION,
                             "status": "success", "at": timestamp(), "suggestion": item["result"],
                             "elapsed_seconds": item["elapsed_seconds"], "kind": item["kind"], "adoption": "测试检查通过"})
    with tempfile.TemporaryDirectory(prefix="p14-offline-") as tmp:
        store = Store(Path(tmp) / "current.db")
        store.save(task)
        restored = store.load()
        assert restored.reviews == task.reviews
        book = load_workbook(io.BytesIO(workbook_bytes(restored)))
        assert book["标准化数据"].max_row == len(task.records) + 1
    evidence = {"at": timestamp(), "model": MODEL, "endpoint": "127.0.0.1:11434", "client_non_loopback_blocked": True,
                "whole_machine_disconnected": False,
                "offline_scope": "Python客户端禁止非回环连接；真实本地模型推理、合成导入、人工关联复核、SQLite恢复、Excel导出通过；未修改整机网络",
                "records": len(task.records), "calls": rows}
    (ROOT / "docs/ai-verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/合成演示-核对与复核.xlsx").write_bytes(workbook_bytes(task))
    print(json.dumps(evidence, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    original = socket.socket.connect
    socket.socket.connect = local_only_connect(original)
    try:
        asyncio.run(verify())
    finally:
        socket.socket.connect = original
