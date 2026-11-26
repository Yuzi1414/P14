"""Two-party matching: bank statement against the finance ledger.

The only matching evidence is the payer (付款单位) plus the signed amount.
Everything else (dates, IDs, export columns) is context for the reviewer and
never decides whether two records belong together.
"""
import hashlib
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from .models import GroupResult, PairResult

MATCHED, UNMATCHED, EXCEPTION = "已匹配", "未匹配", "异常差异"
RELATION = "bank-ledger"


def yuan(cents):
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def normalize_name(value):
    text = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", "", text)


def _id(prefix, values):
    return prefix + hashlib.sha256("|".join(sorted(values)).encode()).hexdigest()[:16]


def _delta(left, right):
    if not left or not right or any(r.signed_cents is None for r in left + right):
        return None
    return sum(r.signed_cents for r in left) - sum(r.signed_cents for r in right)


def _pair(left, right, status, reasons, key, manual=False):
    ids = [r.id for r in left + right]
    return PairResult(_id("p_", [RELATION] + ids), RELATION,
                      [r.id for r in left], [r.id for r in right], status,
                      list(dict.fromkeys(reasons)), _delta(left, right), key, manual)


def _key(record):
    """Exact join key: normalized payer + signed amount, or None when unusable."""
    name = normalize_name(record.name)
    if not name or record.signed_cents is None:
        return None
    return name, record.signed_cents


def evaluate(left, right, key="人工关联", manual=False):
    """Recompute one manual association with the same amount/payer rule."""
    reasons = []
    if not left:
        reasons.append("缺少银行流水记录")
    if not right:
        reasons.append("缺少财务往来账记录")
    if any(r.signed_cents is None for r in left + right):
        reasons.append("金额缺失或无效")
    if any(not normalize_name(r.name) for r in left + right):
        reasons.append("付款单位为空")
    status = UNMATCHED
    if not reasons:
        names = {normalize_name(r.name) for r in left + right}
        amounts = {r.signed_cents for r in left + right}
        if len(names) > 1:
            reasons.append("付款单位不一致：" + " / ".join(r.name for r in left + right))
        if len(amounts) > 1:
            reasons.append(f"金额不一致，差额 {yuan(_delta(left, right))} 元")
        if reasons:
            status = EXCEPTION
        else:
            status = MATCHED
            reasons = ["付款单位与金额一致"]
    if manual:
        reasons = ["人工建立关联"] + reasons
    return _pair(left, right, status, reasons, key, manual)


def match_records(records):
    """Pair bank and ledger records one-to-one on payer + amount."""
    bank = sorted((r for r in records if r.source == "bank"), key=lambda r: (r.row, r.id))
    ledger = sorted((r for r in records if r.source == "ledger"), key=lambda r: (r.row, r.id))
    buckets = defaultdict(lambda: {"bank": [], "ledger": []})
    for record in bank + ledger:
        key = _key(record)
        if key:
            buckets[key][record.source].append(record)

    pairs, used = [], set()
    for key in sorted(buckets, key=lambda item: (item[0], item[1])):
        left, right = buckets[key]["bank"], buckets[key]["ledger"]
        if not left or not right:
            continue
        label = f"{key[0]} · {yuan(key[1])}"
        if len(left) == len(right):
            note = (f"同付款单位同金额共 {len(left)} 笔，按导入顺序一一对应"
                    if len(left) > 1 else "")
            for a, b in zip(left, right):
                pairs.append(_pair([a], [b], MATCHED,
                                   ["付款单位与金额一致"] + ([note] if note else []), label))
                used.update((a.id, b.id))
        else:
            # Counts differ: no pairing is provable, so every record stays open.
            reason = (f"同付款单位同金额的记录数为银行 {len(left)} 条、"
                      f"往来 {len(right)} 条，无法唯一对应")
            for record in left + right:
                pairs.append(_pair([record] if record.source == "bank" else [],
                                   [record] if record.source == "ledger" else [],
                                   UNMATCHED, [reason], label))
                used.add(record.id)

    # Same amount but a different payer: a real discrepancy worth a reviewer's attention.
    left = [r for r in bank if r.id not in used]
    right = [r for r in ledger if r.id not in used]
    by_amount_left, by_amount_right = defaultdict(list), defaultdict(list)
    for record in left:
        if record.signed_cents is not None and normalize_name(record.name):
            by_amount_left[record.signed_cents].append(record)
    for record in right:
        if record.signed_cents is not None and normalize_name(record.name):
            by_amount_right[record.signed_cents].append(record)
    for amount in sorted(set(by_amount_left) & set(by_amount_right)):
        if len(by_amount_left[amount]) == 1 and len(by_amount_right[amount]) == 1:
            a, b = by_amount_left[amount][0], by_amount_right[amount][0]
            pairs.append(_pair(
                [a], [b], EXCEPTION,
                [f"金额一致（{yuan(amount)} 元），付款单位不一致：银行「{a.name}」/ "
                 f"往来「{b.name}」，需人工确认"],
                f"金额:{yuan(amount)}"))
            used.update((a.id, b.id))

    for record in bank + ledger:
        if record.id in used:
            continue
        if record.amount_cents is None:
            reason = "金额缺失或无效，无法参与对账"
        elif not normalize_name(record.name):
            reason = "付款单位为空，无法自动对账"
        elif record.source == "bank":
            reason = "缺少对应的财务往来账记录"
        else:
            reason = "缺少对应的银行流水记录"
        label = (f"{normalize_name(record.name) or '付款单位缺失'} · "
                 f"{yuan(record.signed_cents)}")
        pairs.append(_pair([record] if record.source == "bank" else [],
                           [record] if record.source == "ledger" else [],
                           UNMATCHED, [reason], label))
    return pairs


def assemble_groups(records, pairs):
    parent = {r.id: r.id for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        members = p.left_ids + p.right_ids
        for member in members[1:]:
            parent[find(member)] = find(members[0])
    components = defaultdict(list)
    for r in records:
        components[find(r.id)].append(r)
    component_pairs = defaultdict(list)
    for p in pairs:
        component_pairs[find((p.left_ids + p.right_ids)[0])].append(p)
    groups = []
    for root, members in components.items():
        ps = component_pairs[root]
        present = {r.source for r in members}
        reasons = sorted({reason for p in ps for reason in p.reasons})
        if any(p.status == EXCEPTION for p in ps):
            status = EXCEPTION
        elif present == {"bank", "ledger"} and all(p.status == MATCHED for p in ps):
            status = MATCHED
        else:
            status = UNMATCHED
        primary = next((r for r in members if r.source == "bank"), members[0])
        label = f"{primary.name or '付款单位缺失'} · {yuan(primary.signed_cents)}"
        groups.append(GroupResult(_id("g_", [r.id for r in members]), sorted(r.id for r in members),
                                  sorted(p.id for p in ps), status, reasons, label))
    return sorted(groups, key=lambda g: (g.label, g.id))


def assert_coverage(records, pairs, groups):
    ids = {r.id for r in records}
    if len(ids) != len(records):
        raise ValueError("记录标识重复，疑似重复导入")
    actual = [rid for p in pairs for rid in p.left_ids + p.right_ids]
    if len(actual) != len(set(actual)) or set(actual) != ids:
        raise AssertionError("核对关系存在记录遗漏或重复分配")
    actual = [rid for g in groups for rid in g.record_ids]
    if set(actual) != ids or len(actual) != len(ids):
        raise AssertionError("结果汇总存在记录遗漏或重复")


def run(records):
    pairs = match_records(records)
    groups = assemble_groups(records, pairs)
    assert_coverage(records, pairs, groups)
    return pairs, groups


def candidate_records(task, record_id, limit=5):
    """Unassigned opposite-source records, ranked by amount then payer similarity."""
    record = next((r for r in task.records if r.id == record_id), None)
    if record is None or record.source not in ("bank", "ledger"):
        return []
    record_map = {r.id: r for r in task.records}
    opposite = "ledger" if record.source == "bank" else "bank"
    eligible = []
    for pair in task.pairs:
        if pair.left_ids and pair.right_ids:
            continue
        ids = pair.left_ids + pair.right_ids
        if len(ids) == 1 and record_map[ids[0]].source == opposite:
            eligible.append(record_map[ids[0]])
    candidates = []
    for candidate in eligible:
        score = 0
        if record.signed_cents is not None and record.signed_cents == candidate.signed_cents:
            score += 60
        if record.name and candidate.name:
            score += round(40 * SequenceMatcher(
                None, normalize_name(record.name), normalize_name(candidate.name)).ratio())
        if score:
            candidates.append((score, candidate))
    return sorted(candidates, key=lambda item: (-item[0], item[1].id))[:min(limit, 5)]
