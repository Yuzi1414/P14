"""Deterministic pairwise matching, then bank-connected three-way groups."""
import hashlib
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .models import GroupResult, PairResult

MATCHED, UNMATCHED, EXCEPTION = "已匹配", "未匹配", "异常差异"


def _id(prefix, values):
    return prefix + hashlib.sha256("|".join(sorted(values)).encode()).hexdigest()[:16]


def evaluate(left, right, relation, key, manual=False):
    reasons = []
    if not left or not right:
        reasons.append("缺少银行记录" if not left else "缺少对应来源记录")
    errors = sorted({e for r in left + right for e in r.errors})
    reasons.extend(errors)
    valid_amounts = left and right and all(r.signed_cents is not None for r in left + right)
    delta = sum(r.signed_cents for r in left) - sum(r.signed_cents for r in right) if valid_amounts else None
    if left and right:
        if len(left) > 1 and len(right) > 1:
            reasons.append("多对多关系超出演示规则，需业务确认")
        for members in (left, right):
            counts = Counter(r.business_id for r in members if r.business_id)
            if any(n > 1 for n in counts.values()):
                reasons.append("同一来源业务编号不唯一")
        if len(left) == len(right) == 1:
            a, b = left[0], right[0]
            if a.object_id and b.object_id and a.object_id != b.object_id:
                reasons.append("对象标识冲突")
            if a.batch_id and b.batch_id and a.batch_id != b.batch_id:
                reasons.append("结算批次号冲突")
        dates = {r.date for r in left + right if r.date}
        if any(not r.date for r in left + right):
            reasons.append("业务日期缺失")
        elif len(dates) > 1:
            reasons.append("跨日记录需确认结算规则")
        if len({r.currency for r in left + right}) > 1:
            reasons.append("币种冲突")
        if len({r.direction for r in left + right}) > 1:
            reasons.append("收支方向冲突，不自动抵销退款")
    # An ambiguous association must never be presented as an established discrepancy.
    if reasons:
        status = UNMATCHED
    elif delta != 0:
        status = EXCEPTION
        reasons = ["关联明确但金额不一致；手续费等原因未获业务确认"]
    else:
        status = MATCHED
        reasons = ["明确关联、同日、同币种与方向，金额精确一致"]
    if manual:
        reasons = ["人工建立关联，金额与约束由规则重新计算"] + reasons
    return PairResult(_id("p_", [relation] + [r.id for r in left + right]), relation,
                      [r.id for r in left], [r.id for r in right], status,
                      list(dict.fromkeys(reasons)), delta, key, manual)


def match_relation(records, source):
    relation = f"bank-{source}"
    left = [r for r in records if r.source == "bank"]
    right = [r for r in records if r.source == source]
    used = set()
    results = []
    # Explicit common batch takes precedence, and is never inferred by a sum search.
    for field, prefix in (("batch_id", "批次:"), ("business_id", "编号:")):
        li, ri = defaultdict(list), defaultdict(list)
        for r in left:
            if r.id not in used and getattr(r, field):
                li[getattr(r, field)].append(r)
        for r in right:
            if r.id not in used and getattr(r, field):
                ri[getattr(r, field)].append(r)
        for key in sorted(li.keys() & ri.keys()):
            a, b = li[key], ri[key]
            result = evaluate(a, b, relation, prefix + key)
            # Repeated business IDs cannot establish 1:N; a batch ID is required.
            if field == "business_id" and (len(a) != 1 or len(b) != 1):
                result.status = UNMATCHED
                result.reasons = list(dict.fromkeys(["业务编号重复，无法唯一关联"] + result.reasons))
            results.append(result)
            used.update(r.id for r in a + b)
    for r in left + right:
        if r.id not in used:
            results.append(evaluate([r] if r.source == "bank" else [],
                                    [] if r.source == "bank" else [r], relation,
                                    "孤立:" + (r.business_id or r.batch_id or r.id)))
    return results


def assemble_groups(records, pairs):
    # Union-find over pair memberships; bank records connect the two relations.
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
        elif present == {"bank", "fees", "ledger"} and all(p.status == MATCHED for p in ps):
            status = MATCHED
        else:
            status = UNMATCHED
        labels = sorted({r.batch_id or r.business_id for r in members if r.batch_id or r.business_id})
        groups.append(GroupResult(_id("g_", [r.id for r in members]), sorted(r.id for r in members),
                                  sorted(p.id for p in ps), status, reasons, " / ".join(labels) or members[0].id))
    return sorted(groups, key=lambda g: (g.label, g.id))


def assert_coverage(records, pairs, groups):
    ids = {r.id for r in records}
    if len(ids) != len(records):
        raise ValueError("记录标识重复，疑似重复导入")
    for source in ("fees", "ledger"):
        relation_pairs = [p for p in pairs if p.relation == f"bank-{source}"]
        actual = [rid for p in relation_pairs for rid in p.left_ids + p.right_ids]
        expected = {r.id for r in records if r.source in ("bank", source)}
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise AssertionError(f"bank-{source} 记录遗漏或重复分配")
    actual = [rid for g in groups for rid in g.record_ids]
    if set(actual) != ids or len(actual) != len(ids):
        raise AssertionError("三方汇总存在记录遗漏或重复")


def run(records):
    pairs = match_relation(records, "fees") + match_relation(records, "ledger")
    groups = assemble_groups(records, pairs)
    assert_coverage(records, pairs, groups)
    return pairs, groups


def candidate_records(task, bank_id, relation, limit=5):
    record_map = {r.id: r for r in task.records}
    bank = record_map[bank_id]
    eligible = {p.right_ids[0] for p in task.pairs
                if p.relation == relation and not p.left_ids and len(p.right_ids) == 1}
    candidates = []
    for rid in eligible:
        r = record_map[rid]
        score = 0
        if bank.amount_cents is not None and bank.amount_cents == r.amount_cents:
            score += 40
        if bank.object_id and bank.object_id == r.object_id:
            score += 35
        if bank.date and bank.date == r.date:
            score += 10
        if bank.name and r.name:
            score += round(15 * SequenceMatcher(None, bank.name, r.name).ratio())
        if score:
            candidates.append((score, r))
    return sorted(candidates, key=lambda item: (-item[0], item[1].id))[:min(limit, 5)]

