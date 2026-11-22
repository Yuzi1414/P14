import uuid

from . import engine
from .importer import mark_duplicates
from .models import Task
from .storage import review_status, timestamp


def create_task(records, name="合成演示任务", mappings=None):
    if not records:
        raise ValueError("请先导入数据")
    sources = {r.source for r in records}
    if sources != {"bank", "fees", "ledger"}:
        raise ValueError("请分别导入银行、收费、往来账三类数据")
    file_sources = {}
    for record in records:
        key = (record.file_hash, record.sheet)
        if key in file_sources and file_sources[key] != record.source:
            raise ValueError("同一文件的同一工作表不能重复充当不同数据来源")
        file_sources[key] = record.source
    mark_duplicates(records)
    pairs, groups = engine.run(records)
    return Task(uuid.uuid4().hex, name, records, pairs, groups,
                mappings=mappings or [], created_at=timestamp())


def record_review(task, group_id, action, actor, note):
    if group_id not in {g.id for g in task.groups}:
        raise ValueError("结果组不存在")
    if action not in ("确认", "驳回") or not actor.strip():
        raise ValueError("请选择结论并填写复核人")
    if action == "驳回" and not note.strip():
        raise ValueError("驳回时必须填写原因")
    task.reviews.append({"id": uuid.uuid4().hex, "group_id": group_id, "action": action,
                         "actor": actor.strip(), "note": note.strip(), "at": timestamp()})


def confirm_all_matched(task, actor, note="一键确认全部已匹配组（未逐组填写备注）"):
    """把所有「自动分类 = 已匹配」且还没复核的组，一次性记为人工确认。

    只动已匹配：异常差异和未匹配仍须逐组判断；已确认 / 已驳回的组不会被改写。
    每条记录仍按组写入 reviews，导出和「人工复核状态」列都能看到是谁、什么时候确认的。
    返回本次确认的组数。
    """
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("请先填写复核人")
    pending = [g for g in task.groups
               if g.status == "已匹配" and review_status(task, g.id) == "待复核"]
    for group in pending:
        task.reviews.append({"id": uuid.uuid4().hex, "group_id": group.id, "action": "确认",
                             "actor": actor, "note": note, "at": timestamp(), "batch": True})
    return len(pending)


def accept_candidate(task, bank_id, candidate_id, relation, actor, note):
    if not actor.strip() or not note.strip():
        raise ValueError("人工建立关联须填写复核人和依据")
    if relation not in ("bank-fees", "bank-ledger"):
        raise ValueError("未知核对关系")
    a = next((p for p in task.pairs if p.relation == relation and p.left_ids == [bank_id] and not p.right_ids), None)
    b = next((p for p in task.pairs if p.relation == relation and not p.left_ids and p.right_ids == [candidate_id]), None)
    if a is None or b is None:
        raise ValueError("候选已被分配或关系不再孤立，请刷新结果；不会覆盖已有匹配")
    records = {r.id: r for r in task.records}
    if records[bank_id].source != "bank" or records[candidate_id].source != relation.split("-")[1]:
        raise ValueError("候选来源与关系不符")
    old_groups = {g.id for g in task.groups if bank_id in g.record_ids or candidate_id in g.record_ids}
    new_pair = engine.evaluate([records[bank_id]], [records[candidate_id]], relation, "人工关联", manual=True)
    new_pairs = [p for p in task.pairs if p.id not in (a.id, b.id)] + [new_pair]
    new_groups = engine.assemble_groups(task.records, new_pairs)
    engine.assert_coverage(task.records, new_pairs, new_groups)
    task.pairs, task.groups = new_pairs, new_groups
    # Group IDs change with membership. Existing reviews remain audit history, not approvals of new groups.
    task.reviews.append({"id": uuid.uuid4().hex, "group_id": "", "action": "建立关联",
                         "actor": actor.strip(), "note": note.strip(), "at": timestamp(),
                         "bank_id": bank_id, "candidate_id": candidate_id, "relation": relation,
                         "invalidated_groups": sorted(old_groups)})

