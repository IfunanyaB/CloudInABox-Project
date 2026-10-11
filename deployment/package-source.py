"""Build a minimal source archive for the private Azure Files runtime share."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cloudinabox-package-") as temp_dir:
        template = Path(temp_dir) / "main.json"
        subprocess.run(
            ["az", "bicep", "build", "--file", str(ROOT / "infrastructure" / "main.bicep"), "--outfile", str(template)],
            check=True,
        )
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sorted((ROOT / "automation").glob("*.py")):
                archive.write(source, source.relative_to(ROOT))
            archive.write(ROOT / "index.html", "index.html")
            archive.write(template, "infrastructure/main.json")
            archive.write(ROOT / "requirements-portal.txt", "requirements.txt")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(package(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
