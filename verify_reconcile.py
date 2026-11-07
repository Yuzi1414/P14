# -*- coding: utf-8 -*-
"""用平台真实逻辑验证三张表能否互相匹配。"""
import os, sys
sys.path.insert(0, r"C:\Users\14724\Desktop\P14")
from reconcile.importer import read_sheet, normalize, fingerprint
from reconcile.engine import run
from collections import Counter

desk = r"C:\Users\14724\Desktop"
files = {
    "bank": ("银行流水.xlsx", "银行流水",
             {"business_id": "业务编号", "date": "交易日期", "amount": "金额", "direction": "收支方向"}),
    "fees": ("学生收费.xlsx", "学生收费",
             {"business_id": "业务编号", "date": "缴费日期", "amount": "金额", "direction": "收支方向"}),
    "ledger": ("财务往来账.xlsx", "财务往来账",
               {"business_id": "业务编号", "date": "业务日期", "amount": "金额", "direction": "收支方向"}),
}
all_records = []
for source, (fname, sheet, mapping) in files.items():
    path = os.path.join(desk, fname)
    content = open(path, "rb").read()
    frame = read_sheet(content, fname, sheet, 1)
    print(f"--- {fname}: 表头={list(frame.columns)}, 行数={len(frame)}")
    recs = normalize(frame, source, fname, sheet, 1, mapping, fingerprint(content))
    all_records.extend(recs)

pairs, groups = run(all_records)
print("\n===== 对账结果 =====")
print("总记录:", len(all_records))
print("结果组:", len(groups))
print("分组状态:", Counter(g.status for g in groups))
print("配对状态:", Counter(p.status for p in pairs))
print("\n--- 分组明细 ---")
for g in sorted(groups, key=lambda g: (g.status, g.label)):
    print(f"{g.status:4s} | {g.label:16s} | 成员来源={sorted({r.source for r in all_records if r.id in g.record_ids})} | 依据={g.reasons}")
