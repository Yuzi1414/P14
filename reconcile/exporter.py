import io
import json
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import SOURCES
from .storage import review_status


def money(cents):
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def record_rows(task):
    return [{"记录标识": r.id, "来源": SOURCES.get(r.source, r.source), "文件": r.file,
             "工作表": r.sheet, "原始行号": r.row, "付款单位": r.name, "业务日期": r.date,
             "金额(元)": money(r.signed_cents if r.signed_cents is not None else r.amount_cents),
             "错误": "；".join(r.errors), "提示": "；".join(r.warnings)} for r in task.records]


def _group_notes(task):
    """按结果组聚合人工复核备注（含确认/驳回的说明），最新在前、去重保留顺序。"""
    notes_by_group = {}
    for rev in reversed(task.reviews):
        gid = rev.get("group_id")
        note = (rev.get("note") or "").strip()
        if gid and note:
            notes_by_group.setdefault(gid, []).append(note)
    return {gid: "；".join(dict.fromkeys(notes)) for gid, notes in notes_by_group.items()}


def group_rows(task):
    pairs = {p.id: p for p in task.pairs}
    record_map = {r.id: r for r in task.records}
    notes = _group_notes(task)
    rows = []
    for group in task.groups:
        members = [record_map[rid] for rid in group.record_ids if rid in record_map]
        primary = next((r for r in members if r.source == "bank"), members[0] if members else None)
        delta = [pairs[x].delta_cents for x in group.pair_ids if pairs[x].delta_cents is not None]
        rows.append({
            "结果组": group.id,
            "付款单位": primary.name if primary else "",
            "金额(元)": money(primary.signed_cents if primary else None),
            "自动分类": group.status,
            "人工复核": review_status(task, group.id),
            "原始记录数": len(group.record_ids),
            "差额(元)": money(sum(delta)) if delta else "",
            "判断依据": "；".join(group.reasons),
            "人工详细备注": notes.get(group.id, ""),
            "成员标识": "；".join(group.record_ids),
            "规则版本": task.rules.get("version", ""),
        })
    return rows


def _value(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def workbook_bytes(task):
    book = Workbook()
    book.remove(book.active)
    overflow = []

    def sheet(title, rows, empty_headers=None):
        ws = book.create_sheet(title)
        headers = list(rows[0]) if rows else empty_headers or ["说明"]
        ws.append(headers)
        for row in rows:
            cells = []
            for h in headers:
                value = _value(row.get(h, ""))
                if isinstance(value, str) and len(value) > 30000:
                    ref = f"text-{len(overflow) + 1}"
                    overflow.extend({"引用": ref, "原工作表": title, "原行号": ws.max_row + 1, "字段": h,
                                     "分段": index + 1, "内容": value[offset:offset + 30000]}
                                    for index, offset in enumerate(range(0, len(value), 30000)))
                    value = f"长文本请见‘长文本’工作表，引用 {ref}（按分段顺序拼接）"
                cells.append(value)
            ws.append(cells)
        if not rows:
            ws.append(["无记录"])
        for cells in ws.iter_rows():
            for cell in cells:
                if isinstance(cell.value, str):
                    # Preserve text including =,+,-,@ literally, never as formulas.
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="176B5B")
            cell.font = Font(color="FFFFFF", bold=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            letter = col[0].column_letter
            ws.column_dimensions[letter].width = min(55, max(14, max(len(str(c.value or "")) for c in col[:100]) + 2))
        return ws

    counts = Counter(g.status for g in task.groups)
    sheet("汇总", [{"项目": k, "值": v} for k, v in {
        "用途": "仅供辅助参考；演示规则未经财务确认，不用于正式财务结算",
        "任务": task.name, "创建时间": task.created_at, "规则": task.rules,
        "对账依据": "付款单位 + 金额（精确到分；日期、编号不参与判定）",
        "原始记录数": len(task.records), "结果组数": len(task.groups),
        "已匹配组数": counts["已匹配"], "未匹配组数": counts["未匹配"], "异常差异组数": counts["异常差异"],
        "待复核组数": sum(review_status(task, g.id) == "待复核" for g in task.groups),
        "差额定义": "银行有符号金额合计减财务往来账有符号金额合计；缺失或无效金额留空，不能视为零",
    }.items()])
    grows = group_rows(task)
    for status in ("已匹配", "未匹配", "异常差异"):
        sheet(status, [r for r in grows if r["自动分类"] == status], list(grows[0]) if grows else None)
    sheet("核对关系", [{"关系标识": p.id, "核对关系": p.relation, "银行记录": p.left_ids,
                          "往来记录": p.right_ids, "状态": p.status, "差额(元)": money(p.delta_cents),
                          "依据": p.reasons, "关联键": p.key, "人工建立关联": p.manual} for p in task.pairs])
    sheet("标准化数据", record_rows(task))
    sheet("原始数据", [{"记录标识": r.id, "文件": r.file, "工作表": r.sheet, "原始行号": r.row,
                        "原始内容": r.raw} for r in task.records])
    sheet("数据质量问题", [r for r in record_rows(task) if r["错误"] or r["提示"]])
    sheet("复核记录", task.reviews)
    sheet("AI使用记录", task.ai_logs)
    sheet("字段映射", task.mappings)
    if overflow:
        sheet("长文本", list(overflow))
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
