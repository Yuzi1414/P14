"""Independent, synthetic-only demonstration fixtures. Never derived from financial data."""
import json
from pathlib import Path

from openpyxl import Workbook

HEADERS = ["业务编号", "结算批次号", "对象标识", "往来对象", "业务日期", "金额", "收支方向", "币种"]


def row(bid, amount, batch="", obj="S001", name="演示学生甲", day="2026-10-01", direction="收入"):
    return [bid, batch, obj, name, day, amount, direction, "CNY"]


def fixture_rows():
    bank, fees, ledger = [], [], []
    # Labels and expected decisions are authored independently of the engine.
    for bid, amount in [("000001", "1000.00"), ("000002", "2000.00"), ("000003", "3000.00")]:
        bank.append(row(bid, amount))
        ledger.append(row(bid, amount))
        if bid != "000003":
            fees.append(row(bid, "1900.00" if bid == "000002" else amount))
    fees.append(row("F-ONLY", "4000.00", obj="S004"))
    bank.extend([row("DUP", "500.00"), row("DUP", "500.00")])
    fees.append(row("DUP", "500.00"))
    ledger.append(row("DUP", "500.00"))
    bank.append(row("OBJECT", "600.00", obj="S006"))
    fees.append(row("OBJECT", "600.00", obj="S999"))
    ledger.append(row("OBJECT", "600.00", obj="S006"))
    bank.append(row("BK-B1", "3000.00", batch="BATCH001", obj="", name="演示批量结算"))
    fees.extend([row("FE-B1", "1000.00", batch="BATCH001", obj="S101"),
                 row("FE-B2", "2000.00", batch="BATCH001", obj="S102")])
    ledger.append(row("LG-B1", "3000.00", batch="BATCH001", obj="", name="演示批量结算"))
    bank.extend([row("BK-M1", "1000.00", batch="MANY001"), row("BK-M2", "2000.00", batch="MANY001", obj="S002")])
    fees.append(row("FE-M1", "3000.00", batch="MANY001", obj="", name="演示批量结算"))
    ledger.append(row("LG-M1", "3000.00", batch="MANY001", obj="", name="演示批量结算"))
    for target in (bank, fees, ledger):
        target.append(row("REFUND", "-100.00", direction="退款"))
        target.append(row("CROSS", "700.00", day="2026-10-02" if target is fees else "2026-10-01"))
        target.append(row("DIR", "800.00", direction="支出" if target is fees else "收入"))
        target.append(row("FEE", "990.00" if target is bank else "1000.00"))
        target.append(row("BAD", "金额不明" if target is fees else "900.00"))
        target.append(row("NO-ID", "1100.00"))
    # The bank has no strong key; only a human may join its similar fee/ledger record.
    bank[-1] = row("", "1100.00", name="演示学生甲缴费")
    # Orphans with identical amounts must not match just because of equal amounts.
    bank.append(row("SAME-B", "1234.00", obj="S201"))
    fees.append(row("SAME-F", "1234.00", obj="S202"))
    ledger.append(row("SAME-L", "1234.00", obj="S203"))
    return {"bank": bank, "fees": fees, "ledger": ledger}


EXPECTED = {
    "000001": "已匹配", "000002": "异常差异", "000003": "未匹配",
    "F-ONLY": "未匹配", "DUP": "未匹配", "OBJECT": "未匹配",
    "BATCH001": "已匹配", "MANY001": "已匹配", "REFUND": "已匹配",
    "CROSS": "未匹配", "DIR": "未匹配", "FEE": "异常差异", "BAD": "未匹配",
    "NO-ID": "未匹配", "SAME-B": "未匹配", "SAME-F": "未匹配", "SAME-L": "未匹配",
}


def generate(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    names = {"bank": "银行流水", "fees": "学生收费", "ledger": "财务往来账"}
    for source, rows in fixture_rows().items():
        book = Workbook()
        ws = book.active
        ws.title = "演示明细"
        ws.append(HEADERS)
        for values in rows:
            ws.append(values)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22
        note = book.create_sheet("使用说明")
        note.append(["全部为程序独立构造的合成演示数据，非财务处样例，不用于正式结算。"])
        book.save(root / f"{names[source]}.xlsx")
    (root / "expected.json").write_text(json.dumps(EXPECTED, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "samples")

