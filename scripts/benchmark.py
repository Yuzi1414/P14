import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil

from reconcile.engine import run
from reconcile.models import Record


def main():
    proc = psutil.Process()
    records = [Record(id=f"{source}-{i}", source=source, file="synthetic-benchmark", sheet="data",
                      row=i + 2, file_hash="synthetic", name=f"演示单位{i:05d}",
                      date="2026-10-01", amount_cents=(i % 100 + 1) * 10000)
               for source in ("bank", "ledger") for i in range(10000)]
    before = proc.memory_info().rss
    start = time.perf_counter()
    pairs, groups = run(records)
    elapsed = time.perf_counter() - start
    result = {"rows_per_source": 10000, "total_records": len(records), "pairs": len(pairs),
              "groups": len(groups), "matched_groups": sum(g.status == "已匹配" for g in groups),
              "rule_seconds": round(elapsed, 4), "rss_before_mb": round(before / 1024**2, 2),
              "rss_after_mb": round(proc.memory_info().rss / 1024**2, 2),
              "scope": "两方配对与覆盖检查；不含Excel读写、AI与浏览器；RSS为采样值，非峰值"}
    root = Path(__file__).resolve().parents[1]
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

