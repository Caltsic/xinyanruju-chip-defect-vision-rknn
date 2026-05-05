#!/usr/bin/env python3
"""Build the uploadable cloud package for one-class chip ROI training."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
VALID_STATUSES = {"accepted", "negative"}


@dataclass(slots=True)
class Sample:
    image_path: Path
    label_path: Path
    status: str
    source: str
    group_key: str
    label_text: str
    manifest: Path

    @property
    def is_positive(self) -> bool:
        return self.status == "accepted" and bool(self.label_text.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--review-root", type=Path, default=Path("chip_roi/review_tasks/existing_pseudo_800"))
    parser.add_argument("--gui-manifest", type=Path, default=Path("chip_roi/generated/gui_capture/manifest.csv"))
    parser.add_argument("--dataset-output", type=Path, default=Path("chip_roi/generated/cloud_chip_roi_yolo"))
    parser.add_argument("--package-dir", type=Path, default=Path("cloud_training/chip_roi_yolov8_rknn"))
    parser.add_argument("--output", type=Path, default=Path("cloud_training/chip_roi_yolov8_rknn_cloud_package.zip"))
    parser.add_argument("--root-name", default="chip_roi_yolov8_rknn")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--calib-count", type=int, default=300)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite dataset output if it exists.")
    return parser.parse_args()


def resolve_path(raw: str, manifest_path: Path, project_root: Path) -> Path:
    value = (raw or "").strip()
    if not value:
        return Path()
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        project_root / path,
        manifest_path.parent / path,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return project_root / path


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return [row for row in csv.DictReader(stream) if (row.get("image") or "").strip()]


def normalize_yolo_label(text: str, label_path: Path) -> str:
    lines: list[str] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{label_path}:{line_no}: expected 5 YOLO columns, got {len(parts)}")
        try:
            cls_float = float(parts[0])
            values = [float(part) for part in parts[1:]]
        except ValueError as exc:
            raise ValueError(f"{label_path}:{line_no}: non-numeric YOLO label") from exc
        cls_id = int(cls_float)
        if cls_id != cls_float or cls_id != 0:
            raise ValueError(f"{label_path}:{line_no}: class id must be 0, got {parts[0]}")
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError(f"{label_path}:{line_no}: coordinate outside [0, 1]")
        cx, cy, width, height = values
        if width <= 0.0 or height <= 0.0:
            raise ValueError(f"{label_path}:{line_no}: non-positive bbox size")
        lines.append(f"0 {cx:.8f} {cy:.8f} {width:.8f} {height:.8f}")
    return "\n".join(lines) + ("\n" if lines else "")


def yolo_from_row(row: dict[str, str], label_path: Path) -> str:
    try:
        width = float(row["width"])
        height = float(row["height"])
        x1 = float(row["x1"])
        y1 = float(row["y1"])
        x2 = float(row["x2"])
        y2 = float(row["y2"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{label_path}: missing label file and row box is incomplete") from exc
    if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
        raise ValueError(f"{label_path}: invalid row box")
    cx = ((x1 + x2) * 0.5) / width
    cy = ((y1 + y2) * 0.5) / height
    bw = (x2 - x1) / width
    bh = (y2 - y1) / height
    return normalize_yolo_label(f"0 {cx} {cy} {bw} {bh}\n", label_path)


def source_group_key(source: str, image_path: Path) -> str:
    stem = re.sub(r"_aug_\d+$", "", image_path.stem)
    return f"{source}:{stem}"


def collect_from_manifest(path: Path, project_root: Path, source: str, warnings: list[str]) -> list[Sample]:
    samples: list[Sample] = []
    for row_index, row in enumerate(read_manifest(path), start=2):
        status = (row.get("status") or "").strip()
        if status not in VALID_STATUSES:
            continue
        image_path = resolve_path(row.get("image", ""), path, project_root)
        label_path = resolve_path(row.get("label", ""), path, project_root)
        if not image_path.exists():
            warnings.append(f"{path}:{row_index}: missing image {image_path}")
            continue
        if image_path.suffix.lower() not in IMAGE_EXTS:
            warnings.append(f"{path}:{row_index}: unsupported image extension {image_path}")
            continue

        if status == "negative":
            label_text = ""
        else:
            if label_path.exists():
                raw_label = label_path.read_text(encoding="utf-8")
                label_text = normalize_yolo_label(raw_label, label_path)
            else:
                label_text = yolo_from_row(row, label_path)
            if not label_text.strip():
                warnings.append(f"{path}:{row_index}: accepted sample has empty label {label_path}")
                continue

        samples.append(
            Sample(
                image_path=image_path,
                label_path=label_path,
                status=status,
                source=source,
                group_key=source_group_key(source, image_path),
                label_text=label_text,
                manifest=path,
            )
        )
    return samples


def collect_samples(project_root: Path, review_root: Path, gui_manifest: Path) -> tuple[list[Sample], list[str]]:
    warnings: list[str] = []
    samples: list[Sample] = []
    review_root = (project_root / review_root).resolve()
    for manifest in sorted(review_root.glob("part_*/manifest.csv")):
        samples.extend(collect_from_manifest(manifest, project_root, "review", warnings))
    gui_manifest = (project_root / gui_manifest).resolve()
    if gui_manifest.exists():
        samples.extend(collect_from_manifest(gui_manifest, project_root, "gui", warnings))
    else:
        warnings.append(f"GUI manifest not found: {gui_manifest}")
    return samples, warnings


def group_samples(samples: list[Sample]) -> dict[str, list[Sample]]:
    groups: dict[str, list[Sample]] = {}
    for sample in samples:
        groups.setdefault(sample.group_key, []).append(sample)
    return groups


def split_group_keys(groups: dict[str, list[Sample]], seed: int, ratios: tuple[float, float, float]) -> dict[str, str]:
    rng = random.Random(seed)
    by_kind: dict[str, list[str]] = {"positive": [], "negative": [], "mixed": []}
    for key, group_samples_ in groups.items():
        statuses = {sample.status for sample in group_samples_}
        if statuses == {"negative"}:
            by_kind["negative"].append(key)
        elif statuses == {"accepted"}:
            by_kind["positive"].append(key)
        else:
            by_kind["mixed"].append(key)

    assignments: dict[str, str] = {}
    train_ratio, val_ratio, test_ratio = ratios
    _ = train_ratio
    for kind, keys in by_kind.items():
        keys = sorted(keys)
        rng.shuffle(keys)
        if kind == "mixed" or len(keys) < 10:
            for key in keys:
                assignments[key] = "train"
            continue
        val_count = max(1, int(round(len(keys) * val_ratio)))
        test_count = max(1, int(round(len(keys) * test_ratio)))
        for key in keys[:val_count]:
            assignments[key] = "valid"
        for key in keys[val_count : val_count + test_count]:
            assignments[key] = "test"
        for key in keys[val_count + test_count :]:
            assignments[key] = "train"
    return assignments


def safe_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe[:80] or "sample"


def ensure_clean_output(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists: {path}. Pass --overwrite to rebuild it.")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_dataset(
    samples: list[Sample],
    assignments: dict[str, str],
    output_dir: Path,
    calib_count: int,
    seed: int,
) -> dict[str, object]:
    counters = {
        "train": {"images": 0, "positives": 0, "negatives": 0, "objects": 0},
        "valid": {"images": 0, "positives": 0, "negatives": 0, "objects": 0},
        "test": {"images": 0, "positives": 0, "negatives": 0, "objects": 0},
    }
    source_counts: dict[str, dict[str, int]] = {}
    sample_rows: list[dict[str, str]] = []

    ordered = sorted(samples, key=lambda sample: (assignments[sample.group_key], sample.source, sample.image_path.name))
    for index, sample in enumerate(ordered, start=1):
        split = assignments[sample.group_key]
        stem = f"{sample.source}_{index:05d}_{safe_stem(sample.image_path.stem)}"
        image_dst = output_dir / split / "images" / f"{stem}{sample.image_path.suffix.lower()}"
        label_dst = output_dir / split / "labels" / f"{stem}.txt"
        image_dst.parent.mkdir(parents=True, exist_ok=True)
        label_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sample.image_path, image_dst)
        label_dst.write_text(sample.label_text, encoding="utf-8")

        object_count = len([line for line in sample.label_text.splitlines() if line.strip()])
        counters[split]["images"] += 1
        counters[split]["objects"] += object_count
        if object_count:
            counters[split]["positives"] += 1
        else:
            counters[split]["negatives"] += 1
        source_counts.setdefault(sample.source, {}).setdefault(sample.status, 0)
        source_counts[sample.source][sample.status] += 1
        sample_rows.append(
            {
                "split": split,
                "source": sample.source,
                "status": sample.status,
                "image": str(image_dst),
                "label": str(label_dst),
                "source_image": str(sample.image_path),
                "source_label": str(sample.label_path),
                "manifest": str(sample.manifest),
            }
        )

    data_yaml = output_dir / "data.yaml"
    data_yaml.write_text(
        "\n".join(
            [
                f"path: {output_dir.resolve().as_posix()}",
                "train: train/images",
                "val: valid/images",
                "test: test/images",
                "nc: 1",
                "names:",
                "  0: chip",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "chip_roi_labels.txt").write_text("chip\n", encoding="utf-8")

    train_images = sorted((output_dir / "train" / "images").glob("*"))
    rng = random.Random(seed)
    selected = sorted(rng.sample(train_images, min(calib_count, len(train_images)))) if train_images else []
    (output_dir / "calib_dataset.txt").write_text(
        "\n".join(path.resolve().as_posix() for path in selected) + ("\n" if selected else ""),
        encoding="utf-8",
    )

    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        fieldnames = ["split", "source", "status", "image", "label", "source_image", "source_label", "manifest"]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sample_rows)

    report = {
        "dataset": str(output_dir.resolve()),
        "total_images": sum(value["images"] for value in counters.values()),
        "total_objects": sum(value["objects"] for value in counters.values()),
        "splits": counters,
        "sources": source_counts,
        "data_yaml": str(data_yaml.resolve()),
        "calib_dataset": str((output_dir / "calib_dataset.txt").resolve()),
        "labels": str((output_dir / "chip_roi_labels.txt").resolve()),
    }
    (output_dir / "dataset_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


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


def build_zip(package_dir: Path, dataset_dir: Path, output: Path, root_name: str) -> dict[str, int | str]:
    if output.exists():
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    total_count = 0
    total_bytes = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zipf:
        count, size = add_tree(zipf, package_dir, root_name, skip_package_rules=True)
        total_count += count
        total_bytes += size
        count, size = add_tree(zipf, dataset_dir, f"{root_name}/dataset_raw/chip_roi_yolo", skip_package_rules=False)
        total_count += count
        total_bytes += size
    return {
        "zip": str(output.resolve()),
        "files": total_count,
        "uncompressed_bytes": total_bytes,
        "zip_bytes": output.stat().st_size,
    }


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    package_dir = (project_root / args.package_dir).resolve()
    dataset_output = (project_root / args.dataset_output).resolve()
    output_zip = (project_root / args.output).resolve()
    if not package_dir.exists():
        raise FileNotFoundError(f"Package dir not found: {package_dir}")
    if abs(args.train_ratio + args.val_ratio + args.test_ratio - 1.0) > 1e-6:
        raise ValueError("train/val/test ratios must sum to 1.0")

    ensure_clean_output(dataset_output, args.overwrite)
    samples, warnings = collect_samples(project_root, args.review_root, args.gui_manifest)
    if not samples:
        raise RuntimeError("No accepted/negative samples collected.")
    groups = group_samples(samples)
    assignments = split_group_keys(groups, args.seed, (args.train_ratio, args.val_ratio, args.test_ratio))
    dataset_report = write_dataset(samples, assignments, dataset_output, args.calib_count, args.seed)
    zip_report = build_zip(package_dir, dataset_output, output_zip, args.root_name)

    report = {
        "dataset": dataset_report,
        "zip": zip_report,
        "warnings": warnings,
        "groups": {
            "total": len(groups),
            "train": sum(1 for split in assignments.values() if split == "train"),
            "valid": sum(1 for split in assignments.values() if split == "valid"),
            "test": sum(1 for split in assignments.values() if split == "test"),
        },
    }
    report_path = dataset_output / "cloud_package_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Dataset: {dataset_output}")
    print(f"Images: {dataset_report['total_images']}, objects: {dataset_report['total_objects']}")
    print(f"Splits: {dataset_report['splits']}")
    print(f"Sources: {dataset_report['sources']}")
    print(f"Zip: {output_zip}")
    print(f"Zip files: {zip_report['files']}, zip bytes: {zip_report['zip_bytes']}")
    print(f"Warnings: {len(warnings)}")
    if warnings:
        print(f"First warning: {warnings[0]}")


if __name__ == "__main__":
    main()
