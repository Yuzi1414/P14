"""Read-only Excel import and deterministic normalization."""
import hashlib
import io
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pandas as pd

from .models import FIELDS, SOURCES, Record

ALIASES = {
    "business_id": ["业务编号", "交易编号", "流水号", "订单号", "缴费单号", "凭证关联号"],
    "batch_id": ["结算批次号", "批次号", "结算单号"],
    "object_id": ["对象标识", "学号", "学生编号", "客户编号"],
    "name": ["往来对象", "姓名", "学生姓名", "户名", "对方名称"],
    "date": ["业务日期", "日期", "入账日期", "交易日期", "缴费日期", "记账日期"],
    "amount": ["金额", "入账金额", "收费金额", "记账金额", "交易金额", "缴费金额"],
    "direction": ["收支方向", "方向", "借贷方向", "收付标志"],
    "currency": ["币种", "货币"],
}


def fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _engine(filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        raise ValueError("仅支持 .xlsx / .xls 文件")
    return "xlrd" if suffix == ".xls" else "openpyxl"


def sheet_names(content: bytes, filename: str):
    with pd.ExcelFile(io.BytesIO(content), engine=_engine(filename)) as book:
        return book.sheet_names


def read_sheet(content: bytes, filename: str, sheet: str, header_row: int = 1):
    if header_row < 1:
        raise ValueError("表头行从 1 开始")
    frame = pd.read_excel(io.BytesIO(content), sheet_name=sheet, header=header_row - 1,
                          dtype=object, keep_default_na=False, engine=_engine(filename))
    frame.columns = [str(c).strip() for c in frame.columns]
    if len(frame.columns) != len(set(frame.columns)):
        raise ValueError("表头名称重复，请修正表头或选择正确的表头行")
    # pandas hides exact duplicate headers by appending .1; inspect actual header too.
    header = pd.read_excel(io.BytesIO(content), sheet_name=sheet, header=None,
                           nrows=header_row, dtype=object, keep_default_na=False,
                           engine=_engine(filename))
    names = [str(c).strip() for c in header.iloc[header_row - 1] if str(c).strip()]
    if len(names) != len(set(names)):
        raise ValueError("原始表头存在同名列，不能自动区分")
    # Preserve explicit numeric zero-padding such as 000000, not just text cells.
    if _engine(filename) == "openpyxl":
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            for i, cells in enumerate(book[sheet].iter_rows(min_row=header_row + 1)):
                if i >= len(frame):
                    break
                for j, cell in enumerate(cells[:len(frame.columns)]):
                    if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                        fmt = cell.number_format
                        if re.fullmatch(r"0{2,}", fmt) and float(cell.value).is_integer():
                            frame.iat[i, j] = str(int(cell.value)).zfill(len(fmt))
        finally:
            book.close()
        original_book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        originals = {}
        try:
            for i, cells in enumerate(original_book[sheet].iter_rows(min_row=header_row + 1)):
                if i >= len(frame):
                    break
                for j, cell in enumerate(cells[:len(frame.columns)]):
                    if cell.data_type == "f":
                        originals[(i, str(frame.columns[j]))] = cell.value
        finally:
            original_book.close()
        frame.attrs["original_formulas"] = originals
    else:
        import xlrd
        book = xlrd.open_workbook(file_contents=content, formatting_info=True)
        try:
            table = book.sheet_by_name(sheet)
            for i in range(len(frame)):
                row_index = i + header_row
                for j in range(len(frame.columns)):
                    cell = table.cell(row_index, j)
                    fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
                    if cell.ctype == xlrd.XL_CELL_NUMBER and re.fullmatch(r"0{2,}", fmt) and float(cell.value).is_integer():
                        frame.iat[i, j] = str(int(cell.value)).zfill(len(fmt))
        finally:
            book.release_resources()
    return frame


def suggest_mapping(columns):
    columns = list(columns)
    return {field: next((c for c in columns if c.strip() in names), "")
            for field, names in ALIASES.items()}


def text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_amount(value):
    value = text(value).replace("，", ",").replace("−", "-")
    value = re.sub(r"[¥￥元\s]", "", value)
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    if "," in value:
        if not re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", value):
            raise ValueError("金额千分位格式错误")
        value = value.replace(",", "")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", value):
        raise ValueError("金额缺失或不是有效数字（公式须有缓存数值）")
    try:
        with localcontext() as context:
            context.prec = max(28, len(value) + 4)
            amount = Decimal(value) * 100
            if not amount.is_finite() or amount != amount.to_integral_value():
                raise ValueError("金额精度超过分，不自动四舍五入")
            return int(amount)
    except InvalidOperation as exc:
        raise ValueError("金额无法解析") from exc


def parse_date(value):
    if not text(value):
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    value = text(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y年%m月%d日", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("日期无法解析，请采用明确年月日格式")


def normalize(frame, source, filename, sheet, header_row, mapping, file_hash):
    if source not in SOURCES:
        raise ValueError("未知数据来源")
    if not mapping.get("amount"):
        raise ValueError("必须映射金额字段")
    selected = [c for c in mapping.values() if c]
    if len(selected) != len(set(selected)):
        raise ValueError("同一列不能映射到多个标准字段")
    if any(c not in frame.columns for c in selected):
        raise ValueError("映射包含不存在的列")
    records = []
    for i, row in enumerate(frame.to_dict("records")):
        raw = {str(k): v if isinstance(v, str) else text(v) for k, v in row.items()}
        for column in raw:
            if (i, column) in frame.attrs.get("original_formulas", {}):
                raw[column] = frame.attrs["original_formulas"][(i, column)]
        row_no = header_row + 1 + i
        rid = hashlib.sha256(f"{source}:{file_hash}:{sheet}:{row_no}".encode()).hexdigest()[:20]
        get = lambda f: row.get(mapping.get(f, ""), "")
        record = Record(id=rid, source=source, file=Path(filename).name, sheet=sheet,
                        row=row_no, file_hash=file_hash, raw=raw)
        for field in ("business_id", "batch_id", "object_id", "name"):
            setattr(record, field, text(get(field)))
        if not any(v.strip() for v in raw.values()):
            record.errors.append("空白行：保留位置，不参与自动匹配")
        for field in ("business_id", "object_id", "batch_id"):
            v = get(field)
            if isinstance(v, (float, int)) and len(text(v).replace("-", "")) > 15:
                record.errors.append(f"{FIELDS[field]}为超过15位的Excel数值，可能已丢失精度")
        try:
            signed = parse_amount(get("amount"))
            record.amount_cents = abs(signed)
        except ValueError as exc:
            signed = None
            record.errors.append(str(exc))
        direction = text(get("direction"))
        directions = {"收入": "IN", "收": "IN", "入": "IN", "流入": "IN", "IN": "IN",
                      "支出": "OUT", "付": "OUT", "出": "OUT", "流出": "OUT", "OUT": "OUT", "退款": "OUT"}
        if not direction:
            record.direction = "OUT" if signed is not None and signed < 0 else "IN"
            record.warnings.append("收支方向缺失：依据金额符号推断，需确认")
        elif direction.upper() in directions:
            record.direction = directions[direction.upper()]
            if signed is not None and signed < 0 and record.direction == "IN":
                record.errors.append("负数金额与流入方向冲突")
        else:
            record.direction = "UNKNOWN"
            record.errors.append("收支方向无法识别（借贷不可直接等同收支）")
        currency = text(get("currency")).upper()
        record.currency = {"人民币": "CNY", "RMB": "CNY", "￥": "CNY", "¥": "CNY"}.get(currency, currency or "CNY")
        if not currency:
            record.warnings.append("币种缺失：演示默认CNY，需确认")
        if record.currency != "CNY":
            record.errors.append("演示规则仅支持CNY，不做汇率换算")
        try:
            record.date = parse_date(get("date"))
        except ValueError as exc:
            record.errors.append(str(exc))
        if not record.date:
            record.warnings.append("业务日期缺失，不能自动确认同日结算")
        if not record.business_id and not record.batch_id:
            record.warnings.append("业务编号和批次号均缺失：只能人工建立关联")
        records.append(record)
    return records


def mark_duplicates(records):
    # Recompute rather than accumulate warnings on each import.
    from collections import defaultdict
    buckets = defaultdict(list)
    marker = "疑似重复原始记录：已保留，暂停自动匹配"
    for r in records:
        r.errors = [e for e in r.errors if e != marker]
        signature = (r.source, r.business_id, r.batch_id, r.object_id, r.name,
                     r.date, r.amount_cents, r.direction, r.currency)
        if r.amount_cents is not None:
            buckets[signature].append(r)
    for group in buckets.values():
        if len(group) > 1:
            for r in group:
                r.errors.append(marker)
    return records
