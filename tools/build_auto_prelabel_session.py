#!/usr/bin/env python3
"""Build a CVAT-ready capture session from predicted YOLO-seg labels."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.seg_cvat_pipeline import draw_prelabel_preview, read_image, session_relative, write_jpeg, write_manifest_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True, type=Path)
    parser.add_argument("--stems-file", required=True, type=Path)
    parser.add_argument("--pred-labels", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_stems(path: Path) -> list[str]:
    stems = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for stem in stems:
        if stem not in seen:
            unique.append(stem)
            seen.add(stem)
    return unique


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        stem = Path(row.get("image", "")).stem
        if stem:
            result[stem] = row
    return result


def count_label_objects(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_session(args: argparse.Namespace) -> None:
    source = args.source_session.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        if not args.overwrite:
            raise FileExistsError(f"{output} exists; use --overwrite")
        shutil.rmtree(output)
    for name in ("images", "labels", "images_full", "previews", "meta"):
        (output / name).mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(source / "manifest.csv")
    stems = read_stems(args.stems_file)
    saved = 0
    missing: list[str] = []
    for stem in stems:
        image_src = source / "images" / f"{stem}.jpg"
        label_src = args.pred_labels / f"{stem}.txt"
        full_src = source / "images_full" / f"{stem}.jpg"
        meta_src = source / "meta" / f"{stem}.json"
        if not image_src.exists() or not label_src.exists():
            missing.append(stem)
            continue

        image_dst = output / "images" / image_src.name
        label_dst = output / "labels" / label_src.name
        full_dst = output / "images_full" / full_src.name
        preview_dst = output / "previews" / image_src.name
        meta_dst = output / "meta" / f"{stem}.json"

        shutil.copy2(image_src, image_dst)
        shutil.copy2(label_src, label_dst)
        if full_src.exists():
            shutil.copy2(full_src, full_dst)
        else:
            shutil.copy2(image_src, full_dst)

        image = read_image(image_dst)
        height, width = image.shape[:2]
        label_lines = label_dst.read_text(encoding="utf-8").splitlines()
        write_jpeg(preview_dst, draw_prelabel_preview(image, label_lines), args.jpeg_quality)

        source_meta = load_meta(meta_src)
        source_meta["auto_prelabel"] = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "pred_label": str(label_src),
            "source_session": str(source),
        }
        source_meta["objects"] = count_label_objects(label_dst)
        source_meta["crop_width"] = width
        source_meta["crop_height"] = height
        meta_dst.write_text(json.dumps(source_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        src_row = manifest.get(stem, {})
        row = {
            "image": session_relative(image_dst, output),
            "label": session_relative(label_dst, output),
            "full_image": session_relative(full_dst, output),
            "preview": session_relative(preview_dst, output),
            "meta": session_relative(meta_dst, output),
            "status": "auto-prelabeled" if count_label_objects(label_dst) else "empty",
            "frame_index": src_row.get("frame_index", source_meta.get("frame_index", "")),
            "width": width,
            "height": height,
            "crop_x1": src_row.get("crop_x1", ""),
            "crop_y1": src_row.get("crop_y1", ""),
            "crop_x2": src_row.get("crop_x2", ""),
            "crop_y2": src_row.get("crop_y2", ""),
            "objects": count_label_objects(label_dst),
            "captured_at": src_row.get("captured_at", ""),
        }
        write_manifest_row(output / "manifest.csv", row)
        saved += 1

    report = {"saved": saved, "requested": len(stems), "missing": missing[:50], "missing_count": len(missing)}
    (output / "auto_prelabel_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    build_session(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
