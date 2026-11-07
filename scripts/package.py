"""Package only source, documents and explicitly named synthetic evidence."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def package():
    files = [ROOT / name for name in ("app.py", "README.md", "start.cmd", "requirements.txt",
             "requirements-dev.txt", "requirements-lock.txt", "pytest.ini", ".gitignore", ".streamlit/config.toml")]
    for folder, pattern in (("reconcile", "*.py"), ("scripts", "*.py"), ("scripts", "*.ps1"),
                            ("tests", "*.py"), ("docs", "*.md"), ("docs", "*.json"), ("samples", "*.xlsx"), ("samples", "*.json")):
        files.extend((ROOT / folder).glob(pattern))
    # No glob for arbitrary output files: only artifacts from synthetic verification.
    for name in ("output/合成演示-核对与复核.xlsx", "output/浏览器导出-核对结果.xlsx",
                 "output/playwright/overview.png", "output/playwright/review.png", "output/playwright/import.png",
                 "output/playwright/ai-candidate.png"):
        path = ROOT / name
        if path.exists():
            files.append(path)
    manifest = [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(set(files))]
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    target = out / "P14-账务核对平台-原型成果包.zip"
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for item in manifest:
            archive.write(ROOT / item["path"], item["path"])
        archive.write(out / "manifest.json", "manifest.json")
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert not any(name.startswith((".runtime/", ".venv/", "runtime/", "restricted_data/")) for name in archive.namelist())
    print(target, target.stat().st_size, "bytes", len(files), "files")


if __name__ == "__main__":
    package()
