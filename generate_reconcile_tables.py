# -*- coding: utf-8 -*-
"""生成可互相对账的三张示例表：银行流水、学生收费、财务往来账。
三张表共享 业务编号/日期/金额/收支方向，使对账引擎能跨来源配对。
设计：10 笔三方完全匹配 + 1 笔金额差异(异常) + 1 笔银行独有(未匹配)。
表头放第 1 行（表头行填 1），无合并标题行。
"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
BAND_FILL = PatternFill("solid", fgColor="D9E1F2")
RIGHT = Alignment(horizontal="right", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
CENTER = Alignment(horizontal="center", vertical="center")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY = "#,##0.00"


def money(v):
    return round(v, 2)


def build(ws, headers, rows, widths, money_cols, freeze="A2"):
    for j, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=j, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER
    ws.row_dimensions[1].height = 22
    for i, row in enumerate(rows, start=2):
        for j, v in enumerate(row, start=1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER
            if j in money_cols:
                cell.number_format = MONEY
                cell.alignment = RIGHT
            elif isinstance(v, (int, float)):
                cell.alignment = RIGHT
            else:
                cell.alignment = LEFT
            if i % 2 == 0:
                cell.fill = BAND_FILL
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = freeze


# ===== 事务定义：10 匹配 + 1 金额差异 + 1 银行独有 =====
# (业务编号, 日期, 姓名/对象, 项目, 银行金额, 收费金额, 往来金额)
matched = [
    ("J20260901001", "2026-09-01", "赵艳梅", "学费", 15000, 15000, 15000),
    ("J20260902002", "2026-09-02", "钱丽娜", "住宿费", 1200, 1200, 1200),
    ("J20260903003", "2026-09-03", "孙志强", "学费", 15000, 15000, 15000),
    ("J20260904004", "2026-09-04", "李婷", "教材费", 500, 500, 500),
    ("J20260905005", "2026-09-05", "周晓磊", "住宿费", 1200, 1200, 1200),
    ("J20260908006", "2026-09-08", "吴静", "学费", 15000, 15000, 15000),
    ("J20260909007", "2026-09-09", "郑明", "体检费", 150, 150, 150),
    ("J20260910008", "2026-09-10", "王芳", "学费", 15000, 15000, 15000),
    ("J20260911009", "2026-09-11", "冯杰", "保险费", 100, 100, 100),
    ("J20260912010", "2026-09-12", "陈娟", "教材费", 500, 500, 500),
]
# 金额差异：银行 14850 vs 收费/往来 15000（演示"异常差异"）
mismatch = ("J20260915011", "2026-09-15", "褚涛", "学费", 14850, 15000, 15000)
# 银行独有：银行有利息收入，收费/往来无对应记录（演示"未匹配"）
bank_only = ("J20260916012", "2026-09-16", "银行利息收入", "利息", 800, None, None)

ALL = matched + [mismatch, bank_only]


# ===== 1. 银行流水 =====
def gen_bank():
    wb = Workbook()
    ws = wb.active
    ws.title = "银行流水"
    opening = 500000.00
    bal = opening
    rows = []
    acc = "6222021000123456789"
    for i, (bid, date, name, item, bank_amt, _, _) in enumerate(ALL, start=1):
        if bank_amt is None:
            continue
        bal = money(bal + bank_amt)
        rows.append([
            bid, date, f"{item}收款-{name}", bank_amt, "收入", bal,
            ["网银", "柜台", "手机银行", "POS", "代发"][i % 5], acc,
        ])
    build(ws,
          ["业务编号", "交易日期", "摘要", "金额", "收支方向", "账户余额", "交易渠道", "本方账号"],
          rows, [18, 12, 24, 14, 12, 16, 10, 22], {4, 6})
    return wb


# ===== 2. 学生收费 =====
def gen_fees():
    wb = Workbook()
    ws = wb.active
    ws.title = "学生收费"
    grades = {"2023级", "2024级", "2025级"}
    majors = ["信息管理与信息系统", "计算机科学与技术", "软件工程", "会计学", "市场营销", "英语"]
    pay = ["银行卡", "支付宝", "微信", "POS", "现金"]
    g = list(grades)
    m = list(majors)
    rows = []
    idx = 0
    for bid, date, name, item, _, fee_amt, _ in ALL:
        if fee_amt is None:
            continue
        idx += 1
        rows.append([
            bid, f"2023{idx:05d}", name, m[idx % len(m)], g[idx % len(g)], item, date,
            fee_amt, "收入", pay[idx % len(pay)], "已缴清",
        ])
    build(ws,
          ["业务编号", "学号", "姓名", "专业", "年级", "收费项目", "缴费日期",
           "金额", "收支方向", "缴费方式", "缴费状态"],
          rows, [18, 12, 10, 22, 10, 12, 12, 14, 12, 10, 10], {8})
    return wb


# ===== 3. 财务往来账 =====
def gen_ledger():
    wb = Workbook()
    ws = wb.active
    ws.title = "财务往来账"
    staff = ["张伟", "李娜", "王强", "赵敏", "陈杰"]
    rows = []
    idx = 0
    for bid, date, name, item, _, _, led_amt in ALL:
        if led_amt is None:
            continue
        idx += 1
        rows.append([
            bid, name, date, f"应收{item}款", led_amt, "收入",
            staff[idx % len(staff)], "演示数据",
        ])
    build(ws,
          ["业务编号", "往来对象", "业务日期", "业务摘要", "金额", "收支方向", "经办人", "备注"],
          rows, [18, 12, 12, 20, 14, 12, 10, 12], {5})
    return wb


if __name__ == "__main__":
    import os
    desk = r"C:\Users\14724\Desktop"
    for name, gen in [("银行流水", gen_bank), ("学生收费", gen_fees), ("财务往来账", gen_ledger)]:
        p = os.path.join(desk, name + ".xlsx")
        gen().save(p)
        print("saved", p)
