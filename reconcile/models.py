from dataclasses import asdict, dataclass, field
from typing import Literal

Source = Literal["bank", "ledger"]
SOURCES = {"bank": "银行流水", "ledger": "财务往来账"}
FIELDS = {"name": "付款单位", "amount": "金额", "date": "业务日期"}
RULE_VERSION = "demo-2.0"
RULE_SNAPSHOT = {
    "version": RULE_VERSION, "business_approved": False,
    "relations": ["bank-ledger"],
    "basis": ["payer_name", "amount"], "tolerance_cents": 0,
    "fuzzy": "human-review-only",
    "required_sources": ["bank", "ledger"],
}


@dataclass
class Record:
    id: str
    source: str
    file: str
    sheet: str
    row: int
    file_hash: str
    business_id: str = ""
    batch_id: str = ""
    object_id: str = ""
    name: str = ""
    date: str = ""
    currency: str = "CNY"
    direction: str = "IN"
    amount_cents: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def signed_cents(self):
        if self.amount_cents is None or self.direction not in ("IN", "OUT"):
            return None
        return self.amount_cents * (1 if self.direction == "IN" else -1)


@dataclass
class PairResult:
    id: str
    relation: str
    left_ids: list[str]
    right_ids: list[str]
    status: str
    reasons: list[str]
    delta_cents: int | None
    key: str
    manual: bool = False


@dataclass
class GroupResult:
    id: str
    record_ids: list[str]
    pair_ids: list[str]
    status: str
    reasons: list[str]
    label: str


@dataclass
class Task:
    id: str
    name: str
    records: list[Record]
    pairs: list[PairResult] = field(default_factory=list)
    groups: list[GroupResult] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    ai_logs: list[dict] = field(default_factory=list)
    mappings: list[dict] = field(default_factory=list)
    rules: dict = field(default_factory=lambda: dict(RULE_SNAPSHOT))
    created_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "records": [Record(**r) for r in data["records"]],
                      "pairs": [PairResult(**p) for p in data["pairs"]],
                      "groups": [GroupResult(**g) for g in data["groups"]]})
