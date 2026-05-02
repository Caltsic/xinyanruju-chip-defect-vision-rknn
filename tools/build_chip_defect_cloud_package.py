#!/usr/bin/env python3
"""Build the uploadable cloud package zip for chip defect YOLOv8 RKNN training."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


DEFAULT_DATASET = (
    Path("半导体芯片表面缺陷检测")
    / "半导体芯片表面缺陷检测-解压后可直接使用"
    / "半导体芯片表面缺陷检测"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--package-dir", type=Path, default=Path("cloud_training/yolov8_rknn"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=Path("cloud_training/chipcheck_yolov8_rknn_cloud_package.zip"))
    parser.add_argument("--root-name", default="chipcheck_yolov8_rknn")
    return parser.parse_args()


def should_skip_package_file(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {"outputs", "dataset_raw", "third_party", "__pycache__"}) or path.suffix == ".pyc"


def add_tree(zipf: zipfile.ZipFile, src_root: Path, arc_root: str, skip_package_rules: bool) -> tuple[int, int]:
    count = 0
    total = 0
    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_root)
        if skip_package_rules and should_skip_package_file(rel):
            continue
        arcname = str(Path(arc_root) / rel).replace("\\", "/")
        zipf.write(path, arcname)
        count += 1
        total += path.stat().st_size
    return count, total


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    package_dir = (project_root / args.package_dir).resolve()
    dataset_dir = (project_root / args.dataset).resolve()
    output = (project_root / args.output).resolve()
    if not package_dir.exists():
        raise FileNotFoundError(f"Package dir not found: {package_dir}")
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset dir not found: {dataset_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    total_count = 0
    total_bytes = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zipf:
        count, size = add_tree(zipf, package_dir, args.root_name, skip_package_rules=True)
        total_count += count
        total_bytes += size
        count, size = add_tree(zipf, dataset_dir, f"{args.root_name}/dataset_raw/chip_defect_raw", skip_package_rules=False)
        total_count += count
        total_bytes += size

    print(f"Created: {output}")
    print(f"Files: {total_count}")
    print(f"Uncompressed bytes: {total_bytes}")
    print(f"Zip bytes: {output.stat().st_size}")


if __name__ == "__main__":
    main()
