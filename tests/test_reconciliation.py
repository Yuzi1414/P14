import copy
import io
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from reconcile.demo import load_demo
from reconcile.engine import assert_coverage, candidate_records, run
from reconcile.exporter import group_rows, workbook_bytes
from reconcile.importer import fingerprint, normalize, parse_amount, parse_date, read_sheet, suggest_mapping
from reconcile.models import Record
from reconcile.service import accept_candidate, confirm_all_matched, create_task, record_review
from reconcile.storage import Store, review_status


@pytest.fixture
def task():
    return load_demo()


def test_independent_expected_classification_and_coverage(task):
    expected = json.loads((Path(__file__).resolve().parents[1] / "samples/expected.json").read_text(encoding="utf-8"))
    actual = {g.label: g.status for g in task.groups}
    for label, status in expected.items():
        assert actual[label] == status, label
    assert len(task.records) == sum(len(g.record_ids) for g in task.groups)
    assert_coverage(task.records, task.pairs, task.groups)
    assert sum(g.status == "已匹配" for g in task.groups) == 4
    assert sum(g.status == "异常差异" for g in task.groups) == 2
    assert len(task.groups) == 19
    assert sum(g.status == "未匹配" for g in task.groups) == 13
    assert sum(g.label == "NO-ID" for g in task.groups) == 2  # No bank key: fee/ledger stay separate.
    assert all(review_status(task, g.id) == "待复核" for g in task.groups)


@pytest.mark.parametrize("value,cents", [("￥1,234.56",123456), ("(100.00)",-10000), ("0.01",1), ("0.100",10), ("−1.00",-100)])
def test_money_exact(value,cents):
    assert parse_amount(value) == cents


@pytest.mark.parametrize("value", ["1.001", "12,34", "NaN", "Infinity", "=1+1", "", "1e8"])
def test_invalid_money_is_not_rounded(value):
    with pytest.raises(ValueError):
        parse_amount(value)


def test_date_formats():
    assert parse_date("2026年10月01日") == "2026-10-01"
    with pytest.raises(ValueError):
        parse_date("10/01/26")


def workbook(headers, rows, numeric_padding=False):
    book = Workbook()
    ws = book.active
    ws.title = "明细"
    ws.append(["抬头"])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    if numeric_padding:
        ws["A3"].number_format = "000000"
    book.create_sheet("其他")
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_multisheet_header_padding_and_bad_rows():
    data = workbook(["业务编号","金额","日期"], [[123,"1,000.00","2026/10/01"], ["000002","BAD","2026/10/01"], [None,None,None], ["000004","20","2026/10/01"]], True)
    frame = read_sheet(data, "test.xlsx", "明细", 2)
    records = normalize(frame, "bank", "test.xlsx", "明细", 2, suggest_mapping(frame.columns), fingerprint(data))
    assert records[0].business_id == "000123"
    assert records[0].row == 3
    assert records[1].amount_cents is None and records[1].errors
    assert len(records) == 4 and records[2].errors


def test_xls_numeric_padding():
    import xlwt
    book = xlwt.Workbook()
    ws = book.add_sheet("明细")
    ws.write(0, 0, "业务编号")
    ws.write(0, 1, "金额")
    ws.write(1, 0, 123, xlwt.easyxf(num_format_str="000000"))
    ws.write(1, 1, 100)
    out = io.BytesIO()
    book.save(out)
    frame = read_sheet(out.getvalue(), "old.xls", "明细")
    assert frame.iloc[0,0] == "000123"


def test_duplicate_header_rejected():
    with pytest.raises(ValueError, match="同名"):
        read_sheet(workbook(["金额","金额"], [[1,2]]), "test.xlsx", "明细", 2)


def test_formula_original_preserved_but_uncached_amount_rejected():
    data = workbook(["业务编号","金额"], [["00001","=1+1"]])
    frame = read_sheet(data, "formulas.xlsx", "明细", 2)
    records = normalize(frame,"bank","formulas.xlsx","明细",2,suggest_mapping(frame.columns),fingerprint(data))
    assert records[0].raw["金额"] == "=1+1"
    assert records[0].amount_cents is None and records[0].errors


def test_same_sheet_cannot_impersonate_three_sources():
    r=Record(id="bank",source="bank",file="same.xlsx",file_hash="same",sheet="S",row=2,business_id="B",amount_cents=100,date="2026-10-01")
    with pytest.raises(ValueError, match="不同数据来源"):
        create_task([r,replace(r,id="fees",source="fees"),replace(r,id="ledger",source="ledger")])


def test_repeat_import_does_not_duplicate(task):
    with pytest.raises(ValueError, match="标识重复"):
        create_task(task.records + [copy.deepcopy(task.records[0])])


def test_review_persists_and_does_not_hide_difference(task, tmp_path):
    group = next(g for g in task.groups if g.label == "000002")
    record_review(task, group.id, "确认", "演示复核员", "确认收费少100元")
    db = Store(tmp_path / "task.db")
    db.save(task)
    restored = Store(tmp_path / "task.db").load()
    assert review_status(restored, group.id) == "已确认"
    assert next(g for g in restored.groups if g.id == group.id).status == "异常差异"
    with pytest.raises(ValueError, match="原因"):
        record_review(restored, group.id, "驳回", "人", "")


def _matched(task):
    return [g for g in task.groups if g.status == "已匹配"]


def test_batch_confirm_only_matched_and_pending(task):
    """一键确认只处理「已匹配 + 待复核」，异常差异和未匹配保持原样。"""
    assert len(_matched(task)) == 4
    confirmed = confirm_all_matched(task, "演示复核员")
    assert confirmed == 4
    assert all(review_status(task, g.id) == "已确认" for g in _matched(task))
    assert all(review_status(task, g.id) == "待复核" for g in task.groups if g.status != "已匹配")
    # 再点一次不会重复写入
    assert confirm_all_matched(task, "演示复核员") == 0
    assert sum(item["action"] == "确认" for item in task.reviews) == 4
    # 备注统一写清楚是批量确认，导出时能区分逐组确认
    assert {item["note"] for item in task.reviews} == {"一键确认全部已匹配组（未逐组填写备注）"}
    assert all(item["batch"] for item in task.reviews)


def test_batch_confirm_keeps_rejected_groups(task):
    """已驳回的已匹配组不会被批量确认覆盖。"""
    rejected = _matched(task)[0]
    record_review(task, rejected.id, "驳回", "复核员", "金额口径待财务确认")
    assert confirm_all_matched(task, "复核员") == 3
    assert review_status(task, rejected.id) == "已驳回"


def test_batch_confirm_requires_actor(task):
    with pytest.raises(ValueError, match="复核人"):
        confirm_all_matched(task, "   ")


def test_batch_confirm_persists(task, tmp_path):
    confirm_all_matched(task, "复核员")
    db = Store(tmp_path / "task.db")
    db.save(task)
    restored = Store(tmp_path / "task.db").load()
    assert all(review_status(restored, g.id) == "已确认" for g in _matched(restored))
    assert any(item.get("batch") for item in restored.reviews)


def test_candidate_manual_link_and_no_double_consumption(task):
    bank = next(r for r in task.records if r.source == "bank" and not r.business_id)
    fee = next(r for r in task.records if r.source == "fees" and r.business_id == "NO-ID")
    assert fee.id in {r.id for _,r in candidate_records(task, bank.id, "bank-fees")}
    old_group = next(g for g in task.groups if bank.id in g.record_ids)
    record_review(task, old_group.id, "确认", "人", "原先缺少关联")
    accept_candidate(task, bank.id, fee.id, "bank-fees", "人", "核对原始单据")
    new_group = next(g for g in task.groups if bank.id in g.record_ids)
    assert review_status(task, new_group.id) == "待复核"
    assert new_group.status == "未匹配"  # ledger still missing
    with pytest.raises(ValueError, match="已被分配"):
        accept_candidate(task, bank.id, fee.id, "bank-fees", "人", "重复")
    assert_coverage(task.records, task.pairs, task.groups)


def test_manual_link_recalculates_difference(task):
    bank = next(r for r in task.records if r.source == "bank" and not r.business_id)
    fee = next(r for r in task.records if r.source == "fees" and r.business_id == "NO-ID")
    fee.amount_cents -= 100
    accept_candidate(task, bank.id, fee.id, "bank-fees", "人", "人工凭据")
    pair = next(p for p in task.pairs if p.manual)
    assert pair.delta_cents == 100 and pair.status == "异常差异"


def test_identical_amounts_do_not_establish_match(task):
    for label in ("SAME-B","SAME-F","SAME-L"):
        assert next(g.status for g in task.groups if g.label == label) == "未匹配"


def test_export_roundtrip_and_formula_safety(task):
    task.records[0].name = '=HYPERLINK("https://example.com")'
    task.records[0].raw["往来对象"] = task.records[0].name
    task.reviews.append({"id":"note","group_id":"","action":"备注","actor":"+1+1","note":"=2+2","at":"now"})
    book = load_workbook(io.BytesIO(workbook_bytes(task)), data_only=False)
    assert {"汇总","已匹配","未匹配","异常差异","数据质量问题","复核记录","AI使用记录","标准化数据","原始数据"} <= set(book.sheetnames)
    assert book["标准化数据"].max_row == len(task.records)+1
    assert book["已匹配"].max_row == 5
    for ws in book:
        for row in ws:
            assert all(c.data_type != "f" for c in row)
    assert any(c.value == "=2+2" for row in book["复核记录"] for c in row)


def test_export_long_text_preserved_in_segments(task):
    large = "长内容" * 20000
    task.records[0].raw["附注"] = large
    book = load_workbook(io.BytesIO(workbook_bytes(task)))
    segments = list(book["长文本"].values)
    content_index = segments[0].index("内容")
    combined = "".join(row[content_index] for row in segments[1:])
    assert large in combined
    assert all(len(c.value) <= 32767 for ws in book for row in ws for c in row if isinstance(c.value,str))


def test_missing_date_and_conflicting_batches_cannot_match():
    records=[Record(id=s,source=s,file=s,sheet="S",row=2,file_hash=s,business_id="X",amount_cents=100,date="2026-10-01") for s in ("bank","fees","ledger")]
    records[1].date=""
    assert run(records)[1][0].status == "未匹配"
    records[1].date="2026-10-01"
    records[0].batch_id="B1"
    records[1].batch_id="B2"
    assert run(records)[1][0].status == "未匹配"

