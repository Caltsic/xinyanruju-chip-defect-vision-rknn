#!/usr/bin/env python3
"""Write YOLO segmentation label files from an Ultralytics segmentation model."""

from __future__ import annotations

import argparse
from pathlib import Path


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-labels", required=True, type=Path)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.20)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--max-det", type=int, default=20)
    parser.add_argument("--device", default="0")
    parser.add_argument("--chunk-size", type=int, default=64, help="number of images to predict per Ultralytics call")
    return parser.parse_args()


def iter_images(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(path for path in source.rglob("*") if path.suffix.lower() in IMAGE_EXTS)


def chunks(items: list[Path], size: int) -> list[list[Path]]:
    if size <= 0:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


def write_prediction_labels(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    images = iter_images(args.source)
    if not images:
        raise RuntimeError(f"no images found: {args.source}")
    args.output_labels.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(args.weights))
    total = 0
    objects = 0
    for image_chunk in chunks(images, args.chunk_size):
        results = model.predict(
            source=[str(path) for path in image_chunk],
            task="segment",
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            max_det=args.max_det,
            device=args.device,
            stream=True,
            verbose=False,
        )
        for result in results:
            image_path = Path(result.path)
            lines: list[str] = []
            if result.masks is not None and result.boxes is not None:
                classes = result.boxes.cls.cpu().numpy().astype(int).tolist()
                for class_id, polygon in zip(classes, result.masks.xyn):
                    if len(polygon) < 3:
                        continue
                    coords: list[str] = []
                    for x, y in polygon:
                        coords.append(f"{max(0.0, min(1.0, float(x))):.8f}")
                        coords.append(f"{max(0.0, min(1.0, float(y))):.8f}")
                    if len(coords) >= 6:
                        lines.append(f"{class_id} " + " ".join(coords))
            label_path = args.output_labels / f"{image_path.stem}.txt"
            label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            total += 1
            objects += len(lines)
            if total % 100 == 0:
                print(f"predicted {total}/{len(images)} images objects={objects}", flush=True)
    print(f"prediction complete: images={total} objects={objects} labels={args.output_labels}", flush=True)


def main() -> int:
    write_prediction_labels(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
