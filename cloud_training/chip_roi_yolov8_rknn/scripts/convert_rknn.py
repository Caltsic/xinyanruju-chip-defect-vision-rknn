#!/usr/bin/env python3
"""Convert ONNX to FP and INT8 RKNN models for RK3576."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from importlib import metadata
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", required=True, type=Path, help="Input ONNX model.")
    parser.add_argument("--split-onnx", type=Path, help="Split ONNX to prefer for conversion.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for RKNN outputs.")
    parser.add_argument("--calib-dataset", required=True, type=Path, help="Calibration image list for INT8.")
    parser.add_argument("--target-platform", default="rk3576", help="RKNN target platform.")
    parser.add_argument("--name", default="chip_roi_yolov8_detect", help="Output model prefix.")
    parser.add_argument("--skip-fp", action="store_true", help="Do not export FP RKNN.")
    parser.add_argument("--skip-int8", action="store_true", help="Do not export INT8 RKNN.")
    parser.add_argument("--verbose", action="store_true", help="Enable RKNN verbose logs.")
    return parser.parse_args()


def choose_onnx(onnx: Path, split_onnx: Path | None) -> tuple[Path, bool]:
    candidates = [path for path in [split_onnx, onnx.with_name(f"{onnx.stem}_split.onnx")] if path]
    for path in candidates:
        if path.exists():
            return path, path != onnx
    if not onnx.exists():
        raise FileNotFoundError(f"ONNX model does not exist: {onnx}")
    return onnx, False


def validate_calib(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Calibration dataset list does not exist: {path}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Calibration dataset list is empty: {path}")
    missing = [line for line in lines[:20] if not Path(line).exists()]
    if missing:
        raise FileNotFoundError(f"Calibration dataset contains missing images, first missing: {missing[0]}")


def rknn_toolkit_version() -> str:
    try:
        return metadata.version("rknn-toolkit2")
    except metadata.PackageNotFoundError:
        return "unknown"


def convert_one(onnx_path: Path, output_path: Path, target_platform: str, quantize: bool, calib_dataset: Path, verbose: bool) -> None:
    try:
        from rknn.api import RKNN
    except ImportError as exc:
        raise SystemExit(
            "Missing rknn-toolkit2. Install the Rockchip RKNN-Toolkit2 wheel in a supported Linux/Python environment."
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rknn = RKNN(verbose=verbose)
    try:
        print(f"--> Config RKNN target={target_platform}, quantize={quantize}")
        ret = rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform=target_platform)
        if ret != 0:
            raise RuntimeError(f"rknn.config failed: {ret}")
        print("--> Load ONNX")
        ret = rknn.load_onnx(model=str(onnx_path.resolve()))
        if ret != 0:
            raise RuntimeError(f"rknn.load_onnx failed: {ret}")
        print("--> Build RKNN")
        if quantize:
            ret = rknn.build(do_quantization=True, dataset=str(calib_dataset.resolve()))
        else:
            ret = rknn.build(do_quantization=False)
        if ret != 0:
            raise RuntimeError(f"rknn.build failed: {ret}")
        print(f"--> Export RKNN: {output_path}")
        ret = rknn.export_rknn(str(output_path.resolve()))
        if ret != 0:
            raise RuntimeError(f"rknn.export_rknn failed: {ret}")
    finally:
        rknn.release()


def main() -> None:
    args = parse_args()
    onnx_path, using_split = choose_onnx(
        args.onnx.resolve(),
        args.split_onnx.resolve() if args.split_onnx else None,
    )
    validate_calib(args.calib_dataset)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str] = {}
    if not args.skip_fp:
        fp_path = args.output_dir / f"{args.name}_fp.rknn"
        convert_one(onnx_path, fp_path, args.target_platform, False, args.calib_dataset, args.verbose)
        outputs["fp"] = str(fp_path.resolve())
    if not args.skip_int8:
        int8_suffix = "_split_int8.rknn" if using_split else "_int8.rknn"
        int8_path = args.output_dir / f"{args.name}{int8_suffix}"
        convert_one(onnx_path, int8_path, args.target_platform, True, args.calib_dataset, args.verbose)
        outputs["int8"] = str(int8_path.resolve())

    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "rknn_toolkit2": rknn_toolkit_version(),
        "target_platform": args.target_platform,
        "onnx_requested": str(args.onnx.resolve()),
        "onnx_used": str(onnx_path.resolve()),
        "using_split_onnx": using_split,
        "calib_dataset": str(args.calib_dataset.resolve()),
        "outputs": outputs,
    }
    report_path = args.output_dir / "rknn_conversion_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"RKNN conversion report: {report_path.resolve()}")


if __name__ == "__main__":
    main()
