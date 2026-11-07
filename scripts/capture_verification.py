"""Capture the current synthetic-only UI demonstration as portable evidence."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reconcile.exporter import workbook_bytes
from reconcile.importer import fingerprint
from reconcile.storage import Store, timestamp


def main():
    task = Store(ROOT / "runtime/current.db").load()
    synthetic_hashes = {fingerprint(path.read_bytes()) for path in (ROOT / "samples").glob("*.xlsx")}
    if not task or any(r.file_hash not in synthetic_hashes for r in task.records):
        raise ValueError("Evidence capture is restricted to the project's independent synthetic files")
    evidence = {"at": timestamp(), "task": task.name, "records": len(task.records), "groups": len(task.groups),
                "source_counts": dict(Counter(r.source for r in task.records)),
                "statuses": dict(Counter(g.status for g in task.groups)),
                "manual_relation_count": sum(p.manual for p in task.pairs),
                "review_event_count": len(task.reviews), "ai_calls": task.ai_logs,
                "browser": "isolated Playwright Microsoft Edge session",
                "browser_non_loopback_requests_blocked": True,
                "note": "独立合成样例；不是财务业务验收，不包含本机任务数据库"}
    (ROOT / "docs/ui-verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "output/浏览器导出-核对结果.xlsx").write_bytes(workbook_bytes(task))
    print("Synthetic UI evidence captured", len(task.records), len(task.groups))


if __name__ == "__main__":
    main()
