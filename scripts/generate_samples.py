"""Independent, synthetic-only demonstration fixtures. Never derived from financial data."""
import json
from pathlib import Path

from openpyxl import Workbook

HEADERS = ["业务日期", "付款单位", "金额"]


def row(name, amount, day="2026-10-01"):
    return [day, name, amount]


def fixture_rows():
    """Two parties only: bank statement and finance ledger, joined by payer + amount."""
    bank = [
        row("星海科技有限公司", "12000.00", "2026-10-01"),
        row("星海科技有限公司", "8000.00", "2026-10-02"),
        row("蓝湾贸易有限公司", "5600.00", "2026-10-03"),
        row("远山教育咨询有限公司", "3200.00", "2026-10-04"),
        row("云帆物流有限公司", "1500.00", "2026-10-05"),
        row("青禾文化传播有限公司", "2400.00", "2026-10-06"),
        row("青禾文化传播有限公司", "2400.00", "2026-10-06"),
        row("恒信建设有限公司", "9900.00", "2026-10-07"),
        row("恒信建设有限公司", "9900.00", "2026-10-07"),
        row("", "700.00", "2026-10-08"),
        row("星河餐饮管理有限公司", "-300.00", "2026-10-09"),
    ]
    ledger = [
        row("星海科技有限公司", "12000.00", "2026-10-01"),
        row("星海科技有限公司", "8000.00", "2026-10-02"),
        row("蓝湾贸易有限公司", "5600.00", "2026-10-03"),
        row("远山教育咨询中心", "3200.00", "2026-10-04"),
        row("青禾文化传播有限公司", "2400.00", "2026-10-06"),
        row("青禾文化传播有限公司", "2400.00", "2026-10-06"),
        row("恒信建设有限公司", "9900.00", "2026-10-07"),
        row("", "700.00", "2026-10-08"),
        row("星河餐饮管理有限公司", "-300.00", "2026-10-09"),
        row("明德物业管理有限公司", "2100.00", "2026-10-10"),
    ]
    return {"bank": bank, "ledger": ledger}


# Labels and expected decisions are authored from the business story, not from the engine.
EXPECTED = {
    "summary": {"records": 21, "groups": 14, "已匹配": 6, "异常差异": 1, "未匹配": 7},
    "groups": [
        {"label": "星海科技有限公司 · 12000.00", "status": "已匹配", "count": 1},
        {"label": "星海科技有限公司 · 8000.00", "status": "已匹配", "count": 1},
        {"label": "蓝湾贸易有限公司 · 5600.00", "status": "已匹配", "count": 1},
        {"label": "青禾文化传播有限公司 · 2400.00", "status": "已匹配", "count": 2},
        {"label": "星河餐饮管理有限公司 · -300.00", "status": "已匹配", "count": 1},
        {"label": "远山教育咨询有限公司 · 3200.00", "status": "异常差异", "count": 1},
        {"label": "云帆物流有限公司 · 1500.00", "status": "未匹配", "count": 1},
        {"label": "恒信建设有限公司 · 9900.00", "status": "未匹配", "count": 3},
        {"label": "明德物业管理有限公司 · 2100.00", "status": "未匹配", "count": 1},
        {"label": "付款单位缺失 · 700.00", "status": "未匹配", "count": 2},
    ],
}


def generate(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    names = {"bank": "银行流水", "ledger": "财务往来账"}
    for source, rows in fixture_rows().items():
        book = Workbook()
        ws = book.active
        ws.title = "演示明细"
        ws.append(HEADERS)
        for values in rows:
            ws.append(values)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 26
        note = book.create_sheet("使用说明")
        note.append(["全部为程序独立构造的合成演示数据，非财务处样例，不用于正式结算。"])
        note.append(["对账只比较付款单位与金额；日期仅作备注。同一付款单位同金额多笔按导入顺序一一对应。"])
        book.save(root / f"{names[source]}.xlsx")
    (root / "expected.json").write_text(json.dumps(EXPECTED, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "samples")
