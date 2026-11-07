# -*- coding: utf-8 -*-
"""生成三张示例财务表格：银行流水、学生收费、往来账（单个工作簿，三个子表）"""
import random
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

random.seed(20261104)

# ---------- 样式 ----------
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
BAND_FILL = PatternFill("solid", fgColor="D9E1F2")
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY_FMT = "#,##0.00"


def make_sheet(ws, title, headers, rows, widths, money_cols):
    ncols = len(headers)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(row=1, column=1, value=title)
    c.font = TITLE_FONT
    c.alignment = CENTER
    ws.row_dimensions[1].height = 26

    for j, h in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=j, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER
    ws.row_dimensions[2].height = 22

    for i, row in enumerate(rows, start=3):
        for j, v in enumerate(row, start=1):
            cell = ws.cell(row=i, column=j, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER
            if j in money_cols:
                cell.number_format = MONEY_FMT
                cell.alignment = RIGHT
            elif isinstance(v, (int, float)):
                cell.alignment = RIGHT
            else:
                cell.alignment = LEFT
            if (i % 2) == 1:
                cell.fill = BAND_FILL

    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "A3"


def money(v):
    return round(v, 2)


def bold_row(ws, row, ncols, last_money_col=None):
    for j in range(1, ncols + 1):
        cell = ws.cell(row=row, column=j)
        cell.font = Font(name="微软雅黑", size=10, bold=True)
        cell.border = BORDER
        if last_money_col and j in last_money_col:
            cell.number_format = MONEY_FMT
            cell.alignment = RIGHT


# ================= 1. 银行流水 =================
def gen_bank(ws):
    opening = 1286500.00
    balance = opening
    rows = []
    income_pool = [
        ("货款回收-客户转账", (80000, 320000)),
        ("销售回款", (50000, 250000)),
        ("银行季度结息", (1500, 6000)),
        ("退税到账", (30000, 90000)),
        ("保证金退回", (20000, 50000)),
    ]
    expense_pool = [
        ("原材料采购", (30000, 150000)),
        ("员工工资发放", (80000, 160000)),
        ("水电费", (5000, 20000)),
        ("办公费用", (3000, 15000)),
        ("房租缴纳", (30000, 60000)),
        ("设备购置", (20000, 120000)),
        ("差旅费报销", (2000, 10000)),
        ("缴纳税费", (10000, 40000)),
        ("业务招待费", (2000, 12000)),
    ]
    channels = ["网银", "柜台", "手机银行", "POS", "代发"]
    acc = "6222021000123456789"

    for d in range(1, 41):
        kind = "收入" if d % 3 != 0 else "支出"
        pool = income_pool if kind == "收入" else expense_pool
        desc, rng = random.choice(pool)
        amt = money(random.uniform(*rng))
        if kind == "收入":
            in_, out = amt, 0
        else:
            if balance < amt:
                amt = money(balance * 0.5)
            in_, out = 0, amt
        month = random.choice(["09", "10"])
        day = random.randint(1, 28)
        rows.append([
            f"2026-{month}-{day:02d}",
            f"凭证号2026{month}{day:02d}{d:04d}",
            desc, in_, out, random.choice(channels), acc,
        ])
    rows.sort(key=lambda r: r[0])
    # 排序后按序重算账户余额
    balance = opening
    data = []
    for i, r in enumerate(rows, start=1):
        date, voucher, desc, in_, out, channel, acc_ = r
        balance = money(balance + in_ - out)
        data.append([i, date, voucher, desc, in_, out, balance, channel, acc_])

    headers = ["序号", "交易日期", "凭证号", "摘要", "收方金额(收入)", "付方金额(支出)",
               "账户余额", "交易渠道", "本方账号"]
    widths = [6, 12, 22, 20, 16, 16, 16, 10, 22]
    make_sheet(ws, "银行流水表（示例）", headers, data, widths, {5, 6, 7})

    total_in = money(sum(r[4] for r in data))
    total_out = money(sum(r[5] for r in data))
    n = len(data) + 3
    ws.cell(row=n, column=3, value="合计")
    ws.cell(row=n, column=4, value="期初余额 " + f"{opening:,.2f}")
    ws.cell(row=n, column=5, value=total_in)
    ws.cell(row=n, column=6, value=total_out)
    ws.cell(row=n, column=7, value=balance)
    bold_row(ws, n, len(headers), last_money_col={5, 6, 7})


# ================= 2. 学生收费 =================
def gen_student(ws):
    surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    given = "伟芳娜敏静丽强磊军洋勇艳杰娟涛明超秀兰霞平刚桂英"
    def rand_name():
        return random.choice(surnames) + random.choice(given) + random.choice(given)
    majors = ["计算机科学与技术", "信息管理与信息系统", "软件工程", "会计学", "市场营销", "英语"]
    grades = ["2023级", "2024级", "2025级"]
    items = [("学费", 15000), ("住宿费", 1200), ("教材费", 500), ("体检费", 150), ("保险费", 100)]
    pay_methods = ["银行卡", "支付宝", "微信", "POS", "现金"]

    rows = []
    for i in range(1, 36):
        item, base = random.choice(items)
        year = random.randint(2021, 2026)
        sno = f"{year}{random.randint(1, 9999):05d}"
        amount = base
        if item == "学费":
            paid, status = amount, "已缴清"
        else:
            paid = money(random.choice([amount, amount, amount, amount * random.uniform(0.5, 1), 0]))
            paid = min(paid, amount)
            status = "已缴清" if paid >= amount else ("部分缴费" if paid > 0 else "未缴费")
        month = random.choice(["08", "09"])
        day = random.randint(1, 30)
        rows.append([
            i, sno, rand_name(), random.choice(majors), random.choice(grades),
            item, amount, paid, f"2026-{month}-{day:02d}",
            random.choice(pay_methods), status,
            "" if status == "已缴清" else "示例数据",
        ])

    headers = ["序号", "学号", "姓名", "专业", "年级", "收费项目", "应缴金额", "实缴金额",
               "缴费日期", "缴费方式", "缴费状态", "备注"]
    widths = [6, 12, 10, 22, 10, 12, 14, 14, 12, 12, 10, 12]
    make_sheet(ws, "学生收费明细表（示例）", headers, rows, widths, {7, 8})

    total_should = money(sum(r[6] for r in rows))
    total_paid = money(sum(r[7] for r in rows))
    n = len(rows) + 3
    ws.cell(row=n, column=6, value="合计")
    ws.cell(row=n, column=7, value=total_should)
    ws.cell(row=n, column=8, value=total_paid)
    bold_row(ws, n, len(headers), last_money_col={7, 8})


# ================= 3. 往来账 =================
def gen_current(ws):
    units = ["杭州盛达贸易有限公司", "上海蓝天供应链", "宁波海威机械", "苏州宏远电子",
             "浙江润泽科技", "北京恒信咨询", "广州星辰物流", "深圳市博创数码",
             "成都川渝商贸", "南京金陵实业", "武汉江汉化工", "青岛远洋食品"]
    desc_pool = ["货款往来", "采购应付款", "销售应收款", "预付款", "押金往来", "借款", "其他应收应付款"]
    staff = ["张伟", "李娜", "王强", "赵敏", "陈杰"]

    rows = []
    for i in range(1, 36):
        month = random.choice(["09", "10"])
        day = random.randint(1, 30)
        if random.random() < 0.5:
            dr, cr = money(random.uniform(10000, 120000)), 0
        else:
            dr, cr = 0, money(random.uniform(8000, 150000))
        direction = "应收(借)" if dr else "应付(贷)"
        rows.append([
            i, random.choice(units), f"2026-{month}-{day:02d}", random.choice(desc_pool),
            dr, cr, direction, random.choice(staff), "示例往来",
        ])

    headers = ["序号", "往来单位", "业务日期", "业务摘要", "借方发生额(应收/增)", "贷方发生额(应付/减)",
               "往来方向", "经办人", "备注"]
    widths = [6, 26, 12, 16, 22, 22, 12, 10, 12]
    make_sheet(ws, "往来账明细表（示例）", headers, rows, widths, {5, 6})

    total_dr = money(sum(r[4] for r in rows))
    total_cr = money(sum(r[5] for r in rows))
    n = len(rows) + 3
    ws.cell(row=n, column=4, value="合计")
    ws.cell(row=n, column=5, value=total_dr)
    ws.cell(row=n, column=6, value=total_cr)
    bold_row(ws, n, len(headers), last_money_col={5, 6})


if __name__ == "__main__":
    import os
    desktop = r"C:\Users\14724\Desktop"
    targets = [
        ("银行流水", gen_bank, os.path.join(desktop, "银行流水.xlsx")),
        ("学生收费", gen_student, os.path.join(desktop, "学生收费.xlsx")),
        ("往来账", gen_current, os.path.join(desktop, "往来账.xlsx")),
    ]
    for name, gen, out in targets:
        wb = Workbook()
        ws = wb.active
        ws.title = name
        gen(ws)
        wb.save(out)
        print("saved", out)
