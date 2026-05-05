#!/usr/bin/env python3
"""Train a YOLOv8 segmentation model."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="YOLO segmentation data.yaml.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Training output directory.")
    parser.add_argument("--model", default="yolov8n-seg.pt", help="Initial YOLOv8 segmentation weights or yaml.")
    parser.add_argument("--name", default="chipcheck_yolov8_seg", help="Ultralytics run name.")
    parser.add_argument("--imgsz", type=int, default=640, help="Training and export image size.")
    parser.add_argument("--epochs", type=int, default=150, help="Training epochs.")
    parser.add_argument("--batch", default="-1", help="Batch size. Use -1 for Ultralytics auto batch.")
    parser.add_argument("--device", default="0", help="CUDA device, cpu, or comma-separated devices.")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader workers.")
    parser.add_argument("--patience", type=int, default=30, help="Early-stopping patience.")
    parser.add_argument("--seed", type=int, default=42, help="Training seed.")
    parser.add_argument("--cache", action="store_true", help="Enable Ultralytics dataset cache.")
    parser.add_argument("--copy-best-to", type=Path, help="Optional stable best.pt destination.")
    return parser.parse_args()


def parse_batch(value: str) -> int | float:
    if value.strip() == "-1":
        return -1
    if "." in value:
        return float(value)
    return int(value)


def main() -> None:
    args = parse_args()
    if not args.data.exists():
        raise FileNotFoundError(f"data.yaml does not exist: {args.data}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
        import ultralytics
    except ImportError as exc:
        raise SystemExit("Missing dependency: install ultralytics before training.") from exc

    model = YOLO(args.model)
    run = model.train(
        task="segment",
        data=str(args.data.resolve()),
        project=str(args.output_dir.resolve()),
        name=args.name,
        exist_ok=True,
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=parse_batch(args.batch),
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        seed=args.seed,
        cache=args.cache,
    )

    trainer = getattr(model, "trainer", None)
    save_dir = Path(getattr(trainer, "save_dir", getattr(run, "save_dir", args.output_dir / args.name)))
    best_pt = save_dir / "weights" / "best.pt"
    if not best_pt.exists():
        raise RuntimeError(f"Training finished but best.pt was not found: {best_pt}")
    if args.copy_best_to:
        args.copy_best_to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best_pt, args.copy_best_to)

    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "ultralytics_version": getattr(ultralytics, "__version__", "unknown"),
        "task": "segment",
        "data": str(args.data.resolve()),
        "model": args.model,
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "best_pt": str(best_pt.resolve()),
        "save_dir": str(save_dir.resolve()),
    }
    report_path = args.output_dir / "train_results.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"best.pt: {best_pt.resolve()}")


if __name__ == "__main__":
    main()
