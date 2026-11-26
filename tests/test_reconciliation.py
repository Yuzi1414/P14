import copy
import io
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from reconcile.demo import load_demo
from reconcile.engine import assert_coverage, candidate_records, evaluate, run
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
    summary = expected["summary"]
    counts = Counter(g.status for g in task.groups)
    assert len(task.records) == summary["records"] == 21
    assert len(task.groups) == summary["groups"] == 14
    for status in ("已匹配", "异常差异", "未匹配"):
        assert counts[status] == summary[status], status
    assert len(task.records) == sum(len(g.record_ids) for g in task.groups)
    assert_coverage(task.records, task.pairs, task.groups)
    actual = Counter((g.label, g.status) for g in task.groups)
    for item in expected["groups"]:
        assert actual[(item["label"], item["status"])] == item["count"], item
    assert all(review_status(task, g.id) == "待复核" for g in task.groups)


def test_same_amount_different_payer_is_exception_not_match():
    records = [Record(id="b", source="bank", file="b.xlsx", sheet="S", row=2, file_hash="b",
                      name="甲公司", amount_cents=10000, date="2026-10-01"),
               Record(id="l", source="ledger", file="l.xlsx", sheet="S", row=2, file_hash="l",
                      name="乙公司", amount_cents=10000, date="2026-10-01")]
    pairs, groups = run(records)
    assert groups[0].status == "异常差异"
    assert "付款单位不一致" in "；".join(groups[0].reasons)


def test_same_amount_and_payer_matches():
    records = [Record(id="b", source="bank", file="b.xlsx", sheet="S", row=2, file_hash="b",
                      name="甲公司", amount_cents=10000),
               Record(id="l", source="ledger", file="l.xlsx", sheet="S", row=2, file_hash="l",
                      name="甲公司", amount_cents=10000)]
    pairs, groups = run(records)
    assert groups[0].status == "已匹配"
    assert pairs[0].delta_cents == 0


def test_missing_payer_cannot_be_matched():
    records = [Record(id="b", source="bank", file="b.xlsx", sheet="S", row=2, file_hash="b",
                      amount_cents=70000),
               Record(id="l", source="ledger", file="l.xlsx", sheet="S", row=2, file_hash="l",
                      amount_cents=70000)]
    pairs, groups = run(records)
    assert {g.status for g in groups} == {"未匹配"}
    assert all("付款单位为空" in "；".join(g.reasons) for g in groups)


def test_signed_amounts_keep_refunds_apart():
    records = [Record(id="b", source="bank", file="b.xlsx", sheet="S", row=2, file_hash="b", name="甲",
                      amount_cents=10000, direction="IN"),
               Record(id="l", source="ledger", file="l.xlsx", sheet="S", row=2, file_hash="l", name="甲",
                      amount_cents=10000, direction="OUT")]
    pairs, groups = run(records)
    assert groups[0].status == "未匹配"


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
    data = workbook(["付款单位","金额","日期"], [[123,"1,000.00","2026/10/01"], ["000002","BAD","2026/10/01"], [None,None,None], ["000004","20","2026/10/01"]], True)
    frame = read_sheet(data, "test.xlsx", "明细", 2)
    records = normalize(frame, "bank", "test.xlsx", "明细", 2, suggest_mapping(frame.columns), fingerprint(data))
    assert records[0].name == "000123"
    assert records[0].row == 3
    assert records[1].amount_cents is None and records[1].errors
    assert len(records) == 4 and records[2].errors


def test_xls_numeric_padding():
    import xlwt
    book = xlwt.Workbook()
    ws = book.add_sheet("明细")
    ws.write(0, 0, "付款单位")
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
    data = workbook(["付款单位","金额"], [["甲公司","=1+1"]])
    frame = read_sheet(data, "formulas.xlsx", "明细", 2)
    records = normalize(frame,"bank","formulas.xlsx","明细",2,suggest_mapping(frame.columns),fingerprint(data))
    assert records[0].raw["金额"] == "=1+1"
    assert records[0].amount_cents is None and records[0].errors


def test_payer_and_amount_are_required():
    data = workbook(["金额"], [["100"]])
    frame = read_sheet(data, "test.xlsx", "明细", 2)
    with pytest.raises(ValueError, match="付款单位"):
        normalize(frame, "bank", "test.xlsx", "明细", 2, suggest_mapping(frame.columns), fingerprint(data))


def test_same_sheet_cannot_impersonate_two_sources():
    r=Record(id="bank",source="bank",file="same.xlsx",file_hash="same",sheet="S",row=2,name="甲",amount_cents=100)
    with pytest.raises(ValueError, match="不同数据来源"):
        create_task([r,Record(id="ledger",source="ledger",file="same.xlsx",file_hash="same",sheet="S",row=3,name="甲",amount_cents=100)])


def test_repeat_import_does_not_duplicate(task):
    with pytest.raises(ValueError, match="标识重复"):
        create_task(task.records + [copy.deepcopy(task.records[0])])


def test_review_persists_and_does_not_hide_difference(task, tmp_path):
    group = next(g for g in task.groups if g.label == "远山教育咨询有限公司 · 3200.00")
    record_review(task, group.id, "确认", "演示复核员", "确认付款单位名称不同")
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
    assert len(_matched(task)) == 6
    confirmed = confirm_all_matched(task, "演示复核员")
    assert confirmed == 6
    assert all(review_status(task, g.id) == "已确认" for g in _matched(task))
    assert all(review_status(task, g.id) == "待复核" for g in task.groups if g.status != "已匹配")
    # 再点一次不会重复写入
    assert confirm_all_matched(task, "演示复核员") == 0
    assert sum(item["action"] == "确认" for item in task.reviews) == 6
    # 备注统一写清楚是批量确认，导出时能区分逐组确认
    assert {item["note"] for item in task.reviews} == {"一键确认全部已匹配组（未逐组填写备注）"}
    assert all(item["batch"] for item in task.reviews)


def test_batch_confirm_keeps_rejected_groups(task):
    """已驳回的已匹配组不会被批量确认覆盖。"""
    rejected = _matched(task)[0]
    record_review(task, rejected.id, "驳回", "复核员", "付款单位口径待财务确认")
    assert confirm_all_matched(task, "复核员") == 5
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


def test_candidate_manual_link_from_either_side(task):
    bank = next(r for r in task.records if r.source == "bank" and r.name == "云帆物流有限公司")
    ledger = next(r for r in task.records if r.source == "ledger" and r.name == "明德物业管理有限公司")
    assert ledger.id in {r.id for _, r in candidate_records(task, bank.id)}
    assert bank.id in {r.id for _, r in candidate_records(task, ledger.id)}
    accept_candidate(task, bank.id, ledger.id, "人", "核对原始单据")
    group = next(g for g in task.groups if bank.id in g.record_ids)
    assert group.status == "异常差异"  # amount differs, so the mismatch stays visible
    assert_coverage(task.records, task.pairs, task.groups)
    with pytest.raises(ValueError, match="已被分配"):
        accept_candidate(task, bank.id, ledger.id, "人", "重复")


def test_manual_link_can_confirm_a_true_match(task):
    bank = next(r for r in task.records if r.source == "bank" and r.name == "云帆物流有限公司")
    ledger = next(r for r in task.records if r.source == "ledger" and r.name == "明德物业管理有限公司")
    ledger.name = bank.name
    ledger.amount_cents = bank.amount_cents
    accept_candidate(task, bank.id, ledger.id, "人", "人工确认同一笔")
    pair = next(p for p in task.pairs if p.manual)
    assert pair.status == "已匹配" and pair.delta_cents == 0
    assert next(g for g in task.groups if bank.id in g.record_ids).status == "已匹配"


def test_identical_amounts_alone_do_not_match(task):
    # 同额但付款单位不同：只列为异常差异，不自动认定一致。
    assert next(g.status for g in task.groups if g.label == "远山教育咨询有限公司 · 3200.00") == "异常差异"
    # 付款单位缺失：同额也不自动配对。
    assert sum(g.label == "付款单位缺失 · 700.00" for g in task.groups) == 2


def test_export_roundtrip_and_formula_safety(task):
    task.records[0].name = '=HYPERLINK("https://example.com")'
    task.records[0].raw["付款单位"] = task.records[0].name
    task.reviews.append({"id":"note","group_id":"","action":"备注","actor":"+1+1","note":"=2+2","at":"now"})
    book = load_workbook(io.BytesIO(workbook_bytes(task)), data_only=False)
    assert {"汇总","已匹配","未匹配","异常差异","数据质量问题","复核记录","AI使用记录","标准化数据","原始数据"} <= set(book.sheetnames)
    assert book["标准化数据"].max_row == len(task.records)+1
    assert book["已匹配"].max_row == 7
    for ws in book:
        for row in ws:
            assert all(c.data_type != "f" for c in row)
    assert any(c.value == "=2+2" for row in book["复核记录"] for c in row)


def test_group_rows_have_two_party_columns(task):
    row = group_rows(task)[0]
    assert {"付款单位", "金额(元)", "差额(元)", "自动分类"} <= set(row)
    assert "银行-收费差额(元)" not in row


def test_export_long_text_preserved_in_segments(task):
    large = "长内容" * 20000
    task.records[0].raw["附注"] = large
    book = load_workbook(io.BytesIO(workbook_bytes(task)))
    segments = list(book["长文本"].values)
    content_index = segments[0].index("内容")
    combined = "".join(row[content_index] for row in segments[1:])
    assert large in combined
    assert all(len(c.value) <= 32767 for ws in book for row in ws for c in row if isinstance(c.value,str))
