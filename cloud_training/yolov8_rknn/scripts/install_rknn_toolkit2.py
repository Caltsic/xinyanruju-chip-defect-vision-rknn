#!/usr/bin/env python3
"""Install RKNN-Toolkit2 from Rockchip's official GitHub repository.

Run this in the cloud Linux Python environment before scripts/convert_rknn.py.
The script discovers the wheel matching the current CPython version.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


RKNN_TOOLKIT2_REPO = "https://github.com/airockchip/rknn-toolkit2.git"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--third-party-dir", type=Path, default=Path("third_party"))
    parser.add_argument("--repo-dir", type=Path, help="Existing or target rknn-toolkit2 directory.")
    parser.add_argument("--force-clone", action="store_true", help="Delete and clone repo again.")
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def main() -> None:
    args = parse_args()
    repo = args.repo_dir or args.third_party_dir / "rknn-toolkit2"
    if args.force_clone and repo.exists():
        import shutil

        shutil.rmtree(repo)
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", RKNN_TOOLKIT2_REPO, str(repo)])

    py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    package_root = repo / "packages"
    requirement_files = sorted(package_root.rglob(f"requirements*{py_tag}*.txt"))
    for req in requirement_files:
        run([sys.executable, "-m", "pip", "install", "-r", str(req)])

    wheels = sorted(package_root.rglob(f"*{py_tag}*.whl"))
    if not wheels:
        raise SystemExit(f"No RKNN-Toolkit2 wheel found for {py_tag} under {package_root}")
    wheel = wheels[-1]
    run([sys.executable, "-m", "pip", "install", str(wheel)])
    print(f"Installed RKNN-Toolkit2 wheel: {wheel}")


if __name__ == "__main__":
    main()
