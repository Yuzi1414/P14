"""Download verified official Ollama artifacts using system curl's TLS/proxy stack.

Alternative when Ollama's own downloader cannot negotiate the configured proxy.
No TLS settings, trust stores, or proxy settings are changed.
"""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://registry.ollama.ai/v2/library/qwen3"


def download(url, target, resume=True):
    cmd = ["curl.exe", "--fail", "--location", "--retry", "1", "--connect-timeout", "20"]
    if resume and target.exists():
        cmd += ["--continue-at", "-"]
    subprocess.run(cmd + ["--output", str(target), url], check=True)


def main():
    models = ROOT / ".runtime/models"
    blobs = models / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / ".runtime/qwen3-manifest.json"
    if not manifest_path.exists():
        download(BASE + "/manifests/4b", manifest_path, resume=False)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    for layer in manifest["layers"] + [manifest["config"]]:
        digest = layer["digest"]
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("Unexpected official digest")
        target = blobs / digest.replace(":", "-")
        partial = target.with_name(target.name + ".download")
        if not target.exists():
            if not partial.exists() or partial.stat().st_size != layer["size"]:
                download(BASE + "/blobs/" + digest, partial)
            if partial.stat().st_size != layer["size"]:
                raise ValueError("Model artifact size mismatch")
            partial.replace(target)
        sha = hashlib.sha256()
        with target.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                sha.update(chunk)
        if sha.hexdigest() != digest[7:]:
            raise ValueError("Official SHA256 mismatch")
        print("Verified:", target.name, flush=True)
    dest = models / "manifests/registry.ollama.ai/library/qwen3/4b"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    print("qwen3:4b official artifacts installed; test the local service.", flush=True)


if __name__ == "__main__":
    main()
