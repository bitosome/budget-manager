"""Build a reproducible code-only release; never include local budget records."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
version = json.loads((ROOT / "custom_components/budget_manager/manifest.json").read_text())["version"]
ref = os.environ.get("GITHUB_REF", "")
if ref.startswith("refs/tags/") and ref != f"refs/tags/v{version}":
    raise SystemExit("Release tag and integration version do not match")
files = subprocess.check_output(["git", "ls-files", "-z", "custom_components/budget_manager"], cwd=ROOT).decode().split("\0")
with ZipFile(ROOT / "budget_manager.zip", "w") as archive:
    for filename in sorted(filter(None, files)):
        info = ZipInfo(filename, (1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (ROOT / filename).read_bytes())
archive_hash = sha256((ROOT / "budget_manager.zip").read_bytes()).hexdigest()
(ROOT / "SHA256SUMS").write_text(f"{archive_hash}  budget_manager.zip\n")
notes = (ROOT / "CHANGELOG.md").read_text().split(f"## {version}", 1)[1].split("\n## ", 1)[0].strip()
(ROOT / "RELEASE_NOTES.md").write_text(notes + "\n")
print(f"Built Budget Manager {version}: {archive_hash}")
