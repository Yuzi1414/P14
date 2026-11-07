# -*- coding: utf-8 -*-
import openpyxl, os

desktop = r"C:\Users\14724\Desktop"
for name in ["银行流水", "学生收费", "往来账"]:
    p = os.path.join(desktop, name + ".xlsx")
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    print("=" * 50)
    print(name, "| sheet:", ws.title, "| rows:", ws.max_row, "| cols:", ws.max_column)
    print("headers:", [c.value for c in ws[2]])

# 银行流水余额连续性
ws = openpyxl.load_workbook(os.path.join(desktop, "银行流水.xlsx")).active
prev = 1286500.00
ok = True
for r in range(3, ws.max_row):
    if ws.cell(row=r, column=1).value is None:
        break
    inc = ws.cell(row=r, column=5).value or 0
    exp = ws.cell(row=r, column=6).value or 0
    bal = ws.cell(row=r, column=7).value
    if abs(bal - round(prev + inc - exp, 2)) > 0.005:
        ok = False
        print("MISMATCH row", r)
    prev = round(prev + inc - exp, 2)
print("银行流水余额连续性:", "PASS" if ok else "FAIL", "| 期末:", prev)

# 合计核对
for name, cols in [("学生收费", (7, 8)), ("往来账", (5, 6))]:
    ws = openpyxl.load_workbook(os.path.join(desktop, name + ".xlsx")).active
    sums = []
    for c in cols:
        sums.append(round(sum((ws.cell(row=r, column=c).value or 0) for r in range(3, ws.max_row)), 2))
    row_s = [ws.cell(row=ws.max_row, column=c).value for c in cols]
    print(name, "明细合计:", sums, "| 汇总行:", row_s, "|", "PASS" if sums == row_s else "FAIL")
