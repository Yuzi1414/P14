# -*- coding: utf-8 -*-
import openpyxl

wb = openpyxl.load_workbook(r"C:\Users\14724\Desktop\P14\示例财务三表.xlsx")
ws = wb["银行流水"]
prev = 1286500.00
ok = True
for r in range(3, ws.max_row):
    seq = ws.cell(row=r, column=1).value
    if seq is None:
        break
    inc = ws.cell(row=r, column=5).value or 0
    exp = ws.cell(row=r, column=6).value or 0
    bal = ws.cell(row=r, column=7).value
    expect = round(prev + inc - exp, 2)
    if abs(bal - expect) > 0.005:
        ok = False
        print("MISMATCH row", r, "bal", bal, "expect", expect, "prev", prev, "inc", inc, "exp", exp)
    prev = expect
# 合计行
inc_tot = ws.cell(row=ws.max_row, column=5).value
exp_tot = ws.cell(row=ws.max_row, column=6).value
end_bal = ws.cell(row=ws.max_row, column=7).value
print("期初1,286,500 + 收入", inc_tot, "- 支出", exp_tot, "= 期末", round(1286500+inc_tot-exp_tot,2))
print("汇总期末余额:", end_bal, "| 末行数据余额:", prev)
print("连续性检查:", "PASS" if ok and abs(end_bal-prev) < 0.005 else "FAIL")

# 学生收费：合计核对
ws2 = wb["学生收费"]
should = sum((ws2.cell(row=r, column=7).value or 0) for r in range(3, ws2.max_row))
paid = sum((ws2.cell(row=r, column=8).value or 0) for r in range(3, ws2.max_row))
print("学生收费 应缴合计:", round(should,2), "实缴合计:", round(paid,2), "| 汇总行:",
      ws2.cell(row=ws2.max_row, column=7).value, ws2.cell(row=ws2.max_row, column=8).value)

# 往来账：合计核对
ws3 = wb["往来账"]
dr = sum((ws3.cell(row=r, column=5).value or 0) for r in range(3, ws3.max_row))
cr = sum((ws3.cell(row=r, column=6).value or 0) for r in range(3, ws3.max_row))
print("往来账 借方合计:", round(dr,2), "贷方合计:", round(cr,2), "| 汇总行:",
      ws3.cell(row=ws3.max_row, column=5).value, ws3.cell(row=ws3.max_row, column=6).value)
