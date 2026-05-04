#!/usr/bin/env python3
"""Build semi-automatic chip ROI pseudo labels.

Modes:
- existing: scan the existing chip-defect dataset and generate one-class chip
  pseudo labels with dark-region/edge segmentation.
- captures: scan saved real camera frames and generate chip boxes with the same
  ROI heuristic used by the MaixCAM closed-loop probe.

Outputs are intended to live under chip_roi/generated/, which is ignored by git.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

try:
    from tools.chip_roi_utils import (
        IMAGE_EXTS,
        draw_chip_box,
        locate_chip_dark_edge,
        load_yolo_box,
        make_contact_sheet,
        read_image,
        save_yolo_label,
    )
except ModuleNotFoundError:  # allow running as .\tools\build_chip_roi_dataset.py
    from chip_roi_utils import (
        IMAGE_EXTS,
        draw_chip_box,
        locate_chip_dark_edge,
        load_yolo_box,
        make_contact_sheet,
        read_image,
        save_yolo_label,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = (
    ROOT
    / "半导体芯片表面缺陷检测"
    / "半导体芯片表面缺陷检测-解压后可直接使用"
    / "半导体芯片表面缺陷检测"
)
DEFAULT_EXISTING_OUT = ROOT / "chip_roi" / "generated" / "existing_pseudo"
DEFAULT_CAPTURES_OUT = ROOT / "chip_roi" / "generated" / "captures_pseudo"


def resolve_manifest_path(value: str, manifest_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        Path.cwd() / path,
        ROOT / path,
        manifest_path.parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return ROOT / path


def image_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTS)


def gather_existing(dataset_root: Path, splits: list[str], limit: int) -> list[tuple[Path, str, str]]:
    items: list[tuple[Path, str, str]] = []
    for split in splits:
        images_dir = dataset_root / split / "images"
        for path in image_files(images_dir):
            items.append((path, split, "existing"))
            if limit and len(items) >= limit:
                return items
    return items


def gather_captures(
    inputs: list[Path],
    limit: int,
    include_parts: list[str],
    exclude_parts: list[str],
) -> list[tuple[Path, str, str]]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(
                path
                for path in item.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_EXTS and "chip_roi" not in path.parts
            )
        elif item.is_file() and item.suffix.lower() in IMAGE_EXTS:
            paths.append(item)
    filtered: list[Path] = []
    for path in paths:
        lowered = str(path).lower()
        name = path.name.lower()
        if include_parts and not any(part in lowered for part in include_parts):
            continue
        if exclude_parts and any(part in name or part in lowered for part in exclude_parts):
            continue
        filtered.append(path)
    unique = sorted(dict.fromkeys(path.resolve() for path in filtered))
    if limit:
        unique = unique[:limit]
    return [(path, "captures", "capture") for path in unique]


def safe_stem(path: Path, split: str, used: set[str]) -> str:
    base = f"{split}_{path.stem}".replace(" ", "_")
    stem = base
    index = 1
    while stem in used:
        index += 1
        stem = f"{base}_{index}"
    used.add(stem)
    return stem


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "image",
        "label",
        "split",
        "source",
        "status",
        "width",
        "height",
        "x1",
        "y1",
        "x2",
        "y2",
        "score",
        "method",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def box_from_manifest_row(row: dict[str, str], width: int, height: int) -> tuple[int, int, int, int] | None:
    try:
        values = [row.get(name, "") for name in ("x1", "y1", "x2", "y2")]
        if not all(value != "" for value in values):
            return None
        x1, y1, x2, y2 = [int(float(value)) for value in values]
    except ValueError:
        return None
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width, x2))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def rebuild_previews(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    with manifest_path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if args.preview_limit:
        rows = rows[: args.preview_limit]
    preview_dir = args.output or manifest_path.parent / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for old in preview_dir.glob("contact_*.jpg"):
        old.unlink()

    previews = []
    for index, row in enumerate(rows, start=1):
        image_path = resolve_manifest_path(row["image"], manifest_path)
        try:
            image = read_image(image_path)
        except RuntimeError as exc:
            print(f"[skip] {exc}")
            continue
        height, width = image.shape[:2]
        label_path = resolve_manifest_path(row.get("label", ""), manifest_path) if row.get("label") else Path()
        box = load_yolo_box(label_path, width, height) if label_path else None
        if box is None:
            box = box_from_manifest_row(row, width, height)
        status = row.get("status", "")
        method = row.get("method", "")
        preview_text = f"{index:04d}_{image_path.stem} {status} {method}".strip()
        previews.append((f"{index:04d}_{image_path.stem}", draw_chip_box(image, box, preview_text)))

    chunk_size = 40
    for offset in range(0, len(previews), chunk_size):
        make_contact_sheet(previews[offset : offset + chunk_size], preview_dir / f"contact_{offset // chunk_size + 1:03d}.jpg")
    print(f"previews={len(previews)} output={preview_dir}")
    return 0


def build_labels(args: argparse.Namespace, items: list[tuple[Path, str, str]], square: bool) -> tuple[int, int]:
    rows: list[dict[str, str]] = []
    previews: list[tuple[str, object]] = []
    used: set[str] = set()
    accepted = 0
    needs_review = 0

    for index, (image_path, split, source) in enumerate(items, start=1):
        try:
            image = read_image(image_path)
        except RuntimeError as exc:
            print(f"[skip] {exc}")
            continue
        height, width = image.shape[:2]
        candidate = locate_chip_dark_edge(
            image,
            margin=args.margin,
            min_side=args.min_side,
            square=square,
            allow_fallback=args.allow_fallback,
            min_area_ratio=args.min_area_ratio,
            max_area_ratio=args.max_area_ratio,
            center_bias=args.center_bias,
        )
        stem = safe_stem(image_path, split, used)
        label_path = args.output / "labels" / split / f"{stem}.txt"

        if candidate is None:
            box = None
            status = "needs_review"
            score = ""
            method = "none"
            needs_review += 1
        else:
            box = candidate.box
            status = "candidate"
            score = f"{candidate.score:.6f}"
            method = candidate.method
            accepted += 1
        save_yolo_label(label_path, box, width, height)

        row = {
            "image": str(image_path.resolve()),
            "label": str(label_path.resolve()),
            "split": split,
            "source": source,
            "status": status,
            "width": str(width),
            "height": str(height),
            "x1": "" if box is None else str(box[0]),
            "y1": "" if box is None else str(box[1]),
            "x2": "" if box is None else str(box[2]),
            "y2": "" if box is None else str(box[3]),
            "score": score,
            "method": method,
        }
        rows.append(row)

        if args.preview_limit and len(previews) < args.preview_limit:
            preview_text = f"{split}/{image_path.name} {status} {method} {score}".strip()
            previews.append((f"{index:04d}_{image_path.stem}", draw_chip_box(image, box, preview_text)))

        if args.progress_every and index % args.progress_every == 0:
            print(f"processed {index}/{len(items)}")

    write_manifest(args.output / "manifest.csv", rows)
    if previews:
        args.output.joinpath("previews").mkdir(parents=True, exist_ok=True)
        chunk_size = 40
        for offset in range(0, len(previews), chunk_size):
            make_contact_sheet(previews[offset : offset + chunk_size], args.output / "previews" / f"contact_{offset // chunk_size + 1:03d}.jpg")
    return accepted, needs_review


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    existing = subparsers.add_parser("existing", help="Generate chip labels from the existing training dataset")
    existing.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    existing.add_argument("--splits", default="train,valid,test")
    existing.add_argument("--output", type=Path, default=DEFAULT_EXISTING_OUT)
    existing.add_argument("--limit", type=int, default=0)
    existing.add_argument("--margin", type=float, default=0.10)
    existing.add_argument("--min-side", type=int, default=0)
    existing.add_argument("--min-area-ratio", type=float, default=0.0015)
    existing.add_argument("--max-area-ratio", type=float, default=0.92)
    existing.add_argument("--center-bias", type=float, default=5.0)
    existing.add_argument("--allow-fallback", action="store_true", default=True)
    existing.add_argument("--preview-limit", type=int, default=120)
    existing.add_argument("--progress-every", type=int, default=250)

    captures = subparsers.add_parser("captures", help="Generate chip labels from saved real camera frames")
    captures.add_argument("inputs", nargs="*", type=Path, help="Image files or directories; defaults to captures/")
    captures.add_argument("--output", type=Path, default=DEFAULT_CAPTURES_OUT)
    captures.add_argument("--limit", type=int, default=0)
    captures.add_argument("--margin", type=float, default=0.35)
    captures.add_argument("--min-side", type=int, default=220)
    captures.add_argument("--min-area-ratio", type=float, default=0.0015)
    captures.add_argument("--max-area-ratio", type=float, default=0.35)
    captures.add_argument("--center-bias", type=float, default=12.0)
    captures.add_argument("--allow-fallback", action="store_true", default=True)
    captures.add_argument("--include", default="", help="Comma-separated substrings; keep only matching capture paths")
    captures.add_argument(
        "--exclude",
        default="annotated,variants,crop,onnx_diag,contact,preview,smoke,out,top2,confidence,roi_closed_loop",
        help="Comma-separated filename substrings to skip",
    )
    captures.add_argument("--preview-limit", type=int, default=120)
    captures.add_argument("--progress-every", type=int, default=50)

    previews = subparsers.add_parser("previews", help="Rebuild contact-sheet previews from an existing manifest")
    previews.add_argument("--manifest", type=Path, required=True)
    previews.add_argument("--output", type=Path, help="Preview output directory; defaults to manifest parent/previews")
    previews.add_argument("--preview-limit", type=int, default=160)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.mode == "existing":
        args.output.mkdir(parents=True, exist_ok=True)
        splits = split_csv(args.splits)
        items = gather_existing(args.dataset_root, splits, args.limit)
        square = False
    elif args.mode == "previews":
        return rebuild_previews(args)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        inputs = args.inputs or [ROOT / "captures"]
        items = gather_captures(inputs, args.limit, split_csv(args.include.lower()), split_csv(args.exclude.lower()))
        square = True

    if not items:
        raise SystemExit("no input images found")

    print(f"mode={args.mode} images={len(items)} output={args.output}")
    accepted, needs_review = build_labels(args, items, square)
    print(f"candidate={accepted} needs_review={needs_review}")
    print(f"manifest={args.output / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
