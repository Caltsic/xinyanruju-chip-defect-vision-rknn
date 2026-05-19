#!/usr/bin/env python3
"""Run the chip ROI YOLOv8 OBB prepare -> train -> ONNX -> RKNN pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset_raw/chip_roi_yolo"))
    parser.add_argument("--work-dir", type=Path, default=Path("outputs_obb"))
    parser.add_argument("--model", default="yolov8n-obb.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch", default="64")
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--patience", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calib-count", type=int, default=300)
    parser.add_argument("--target-platform", default="rk3576")
    parser.add_argument("--class-count", type=int, help="Class count for ONNX split; inferred when omitted.")
    parser.add_argument("--opset", type=int, default=12)
    parser.add_argument("--weights", type=Path, help="Use an existing OBB best.pt and skip training.")
    parser.add_argument("--overwrite-dataset", action="store_true", help="Overwrite converted OBB dataset.")
    parser.add_argument("--preview-count", type=int, default=8, help="Write this many OBB preview images per split.")
    parser.add_argument("--padding-ratio", type=float, default=0.18, help="Extra crop padding around each HBB.")
    parser.add_argument("--min-contour-area-ratio", type=float, default=0.18, help="Reject tiny contour candidates.")
    parser.add_argument("--skip-rknn", action="store_true", help="Stop after ONNX split export.")
    parser.add_argument("--skip-split", action="store_true", help="Do not create split ONNX.")
    parser.add_argument("--rknn-verbose", action="store_true", help="Enable RKNN verbose conversion logs.")
    return parser.parse_args()


def run(cmd: list[object]) -> None:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def copy_required(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Required artifact missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def export_onnx(weights: Path, output: Path, imgsz: int, opset: int) -> Path:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Missing dependency: install ultralytics before OBB ONNX export.") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(weights.resolve()))
    exported = Path(model.export(format="onnx", imgsz=imgsz, opset=opset, simplify=True, dynamic=False, nms=False))
    if exported.resolve() != output.resolve():
        shutil.copy2(exported, output)
    report = {
        "weights": str(weights.resolve()),
        "output": str(output.resolve()),
        "source_onnx": str(exported.resolve()),
        "task": "obb",
        "imgsz": imgsz,
        "opset": opset,
        "exporter": "standard_ultralytics",
    }
    output.with_suffix(".export_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    repo_root = root.parents[1]
    scripts = root / "scripts"
    work = args.work_dir.resolve()
    dataset_out = work / "dataset_yolov8_chip_roi_obb"
    final = work / "final"
    final.mkdir(parents=True, exist_ok=True)

    calib_path = work / "calib_dataset.txt"
    labels_path = work / "chip_roi_labels.txt"
    run(
        [
            sys.executable,
            scripts / "prepare_obb_dataset.py",
            "--raw-dataset",
            args.raw_dataset,
            "--output-dir",
            dataset_out,
            "--calib-output",
            calib_path,
            "--labels-output",
            labels_path,
            "--calib-count",
            args.calib_count,
            "--seed",
            args.seed,
            "--padding-ratio",
            args.padding_ratio,
            "--min-contour-area-ratio",
            args.min_contour_area_ratio,
            "--preview-count",
            args.preview_count,
            "--self-check",
            "--image-mode",
            "hardlink",
            *(["--overwrite"] if args.overwrite_dataset else []),
        ]
    )

    stable_best = final / "chip_roi_yolov8_obb.pt"
    if args.weights:
        copy_required(args.weights.resolve(), stable_best)
    else:
        run(
            [
                sys.executable,
                scripts / "train_yolov8_obb.py",
                "--data",
                dataset_out / "data.yaml",
                "--output-dir",
                work / "train",
                "--model",
                args.model,
                "--name",
                "chip_roi_yolov8_obb",
                "--imgsz",
                args.imgsz,
                "--epochs",
                args.epochs,
                "--batch",
                args.batch,
                "--device",
                args.device,
                "--workers",
                args.workers,
                "--patience",
                args.patience,
                "--seed",
                args.seed,
                "--copy-best-to",
                stable_best,
            ]
        )

    onnx_path = final / "chip_roi_yolov8_obb.onnx"
    export_onnx(stable_best, onnx_path, args.imgsz, args.opset)

    split_onnx_path = final / "chip_roi_yolov8_obb_split.onnx"
    if not args.skip_split:
        split_cmd: list[object] = [
            sys.executable,
            repo_root / "tools" / "split_yolov8_obb_onnx_outputs.py",
            "--input",
            onnx_path,
            "--output",
            split_onnx_path,
        ]
        if args.class_count is not None:
            split_cmd.extend(["--class-count", args.class_count])
        run(split_cmd)

    copy_required(labels_path, final / "chip_roi_labels.txt")
    copy_required(calib_path, final / "calib_dataset.txt")
    copy_required(dataset_out / "dataset_report.json", final / "dataset_report.json")

    if not args.skip_rknn:
        rknn_dir = final / "rknn"
        convert_cmd: list[object] = [
            sys.executable,
            scripts / "convert_rknn.py",
            "--onnx",
            onnx_path,
            *(["--split-onnx", split_onnx_path] if split_onnx_path.exists() else []),
            "--output-dir",
            rknn_dir,
            "--calib-dataset",
            calib_path,
            "--target-platform",
            args.target_platform,
            "--name",
            "chip_roi_yolov8_obb",
        ]
        if args.rknn_verbose:
            convert_cmd.append("--verbose")
        run(convert_cmd)
        copy_required(rknn_dir / "chip_roi_yolov8_obb_fp.rknn", final / "chip_roi_yolov8_obb_fp.rknn")
        int8_name = "chip_roi_yolov8_obb_split_int8.rknn" if split_onnx_path.exists() else "chip_roi_yolov8_obb_int8.rknn"
        copy_required(rknn_dir / int8_name, final / int8_name)

    print(f"Final artifacts directory: {final}")


if __name__ == "__main__":
    main()
