#!/usr/bin/env python3
"""Run the full chip defect YOLOv8 -> ONNX -> RKNN pipeline."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset_raw/chip_defect_raw"))
    parser.add_argument("--work-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch", default="-1")
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calib-count", type=int, default=300)
    parser.add_argument("--target-platform", default="rk3576")
    parser.add_argument("--weights", type=Path, help="Use an existing best.pt and skip training.")
    parser.add_argument("--skip-rknn", action="store_true", help="Stop after ONNX export.")
    parser.add_argument("--overwrite-dataset", action="store_true", help="Overwrite converted detection dataset.")
    parser.add_argument(
        "--no-auto-clone-rockchip-exporter",
        dest="auto_clone_rockchip_exporter",
        action="store_false",
        default=True,
        help="Do not clone Rockchip ultralytics exporter automatically.",
    )
    parser.add_argument(
        "--no-install-rockchip-exporter",
        dest="install_rockchip_exporter",
        action="store_false",
        default=True,
        help="Do not run pip install -e for the Rockchip exporter fork.",
    )
    parser.add_argument("--standard-export-fallback", action="store_true", help="Fallback to standard Ultralytics export.")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    subprocess.run([str(part) for part in cmd], check=True)


def copy_required(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Required artifact missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts"
    work = args.work_dir.resolve()
    dataset_out = work / "dataset_yolov8_det"
    final = work / "final"
    final.mkdir(parents=True, exist_ok=True)

    calib_path = work / "calib_dataset.txt"
    labels_path = work / "chip_defect_labels.txt"
    run(
        [
            sys.executable,
            scripts / "prepare_dataset.py",
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
            "--image-mode",
            "hardlink",
            *(["--overwrite"] if args.overwrite_dataset else []),
        ]
    )

    stable_best = final / "chipcheck_yolov8_detect.pt"
    if args.weights:
        copy_required(args.weights.resolve(), stable_best)
    else:
        run(
            [
                sys.executable,
                scripts / "train_yolov8.py",
                "--data",
                dataset_out / "data.yaml",
                "--output-dir",
                work / "train",
                "--model",
                args.model,
                "--name",
                "chipcheck_yolov8_detect",
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

    onnx_path = final / "chipcheck_yolov8_detect.onnx"
    export_cmd = [
        sys.executable,
        scripts / "export_onnx.py",
        "--weights",
        stable_best,
        "--output",
        onnx_path,
        "--imgsz",
        args.imgsz,
        "--opset",
        "12",
        "--rockchip-ultralytics-dir",
        work / "third_party" / "ultralytics_yolov8",
    ]
    if args.auto_clone_rockchip_exporter:
        export_cmd.append("--auto-clone")
    if args.install_rockchip_exporter:
        export_cmd.append("--install-fork")
    if args.standard_export_fallback:
        export_cmd.append("--standard-fallback")
    run(export_cmd)

    copy_required(labels_path, final / "chip_defect_labels.txt")
    copy_required(calib_path, final / "calib_dataset.txt")
    copy_required(dataset_out / "dataset_report.json", final / "dataset_report.json")

    if not args.skip_rknn:
        rknn_dir = final / "rknn"
        run(
            [
                sys.executable,
                scripts / "convert_rknn.py",
                "--onnx",
                onnx_path,
                "--output-dir",
                rknn_dir,
                "--calib-dataset",
                calib_path,
                "--target-platform",
                args.target_platform,
                "--name",
                "chipcheck_yolov8_detect",
            ]
        )
        copy_required(rknn_dir / "chipcheck_yolov8_detect_fp.rknn", final / "chipcheck_yolov8_detect_fp.rknn")
        copy_required(rknn_dir / "chipcheck_yolov8_detect_int8.rknn", final / "chipcheck_yolov8_detect_int8.rknn")

    print(f"Final artifacts directory: {final}")


if __name__ == "__main__":
    main()
