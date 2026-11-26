from pathlib import Path

from .importer import fingerprint, normalize, read_sheet, suggest_mapping
from .service import create_task


def load_demo():
    root = Path(__file__).resolve().parents[1] / "samples"
    records, mappings = [], []
    for source, name in (("bank", "银行流水"), ("ledger", "财务往来账")):
        path = root / f"{name}.xlsx"
        data = path.read_bytes()
        frame = read_sheet(data, path.name, "演示明细")
        mapping = suggest_mapping(frame.columns)
        records.extend(normalize(frame, source, path.name, "演示明细", 1, mapping, fingerprint(data)))
        mappings.append({"来源": source, "文件": path.name, "工作表": "演示明细", "表头行": 1,
                         "映射": mapping, "确认人": "合成样例预设映射", "AI建议": False})
    return create_task(records, mappings=mappings)
