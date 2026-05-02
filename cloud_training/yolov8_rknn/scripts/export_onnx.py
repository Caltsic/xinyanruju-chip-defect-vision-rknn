#!/usr/bin/env python3
"""Export trained YOLOv8 weights to a Rockchip-friendly ONNX model."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROCKCHIP_ULTRALYTICS = "https://github.com/airockchip/ultralytics_yolov8.git"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path, help="Trained YOLOv8 .pt file.")
    parser.add_argument("--output", required=True, type=Path, help="Output ONNX path.")
    parser.add_argument("--imgsz", type=int, default=640, help="Static ONNX input size.")
    parser.add_argument("--opset", type=int, default=12, help="ONNX opset.")
    parser.add_argument("--rockchip-ultralytics-dir", type=Path, default=Path("third_party/ultralytics_yolov8"))
    parser.add_argument("--auto-clone", action="store_true", help="Clone Rockchip ultralytics_yolov8 if missing.")
    parser.add_argument("--install-fork", action="store_true", help="Run pip install -e for the Rockchip fork before export.")
    parser.add_argument("--standard-fallback", action="store_true", help="Fallback to standard ultralytics export if Rockchip export fails.")
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def ensure_rockchip_repo(path: Path, auto_clone: bool) -> None:
    if path.exists():
        return
    if not auto_clone:
        raise FileNotFoundError(
            f"Rockchip ultralytics fork not found: {path}. "
            "Pass --auto-clone or clone https://github.com/airockchip/ultralytics_yolov8.git first."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth", "1", ROCKCHIP_ULTRALYTICS, str(path)])


def patch_default_yaml(repo: Path, weights: Path, imgsz: int, opset: int) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing dependency: install PyYAML before Rockchip ONNX export.") from exc

    cfg_path = repo / "ultralytics" / "cfg" / "default.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Rockchip default.yaml not found: {cfg_path}")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["task"] = "detect"
    cfg["mode"] = "export"
    cfg["model"] = str(weights.resolve())
    cfg["format"] = "onnx"
    cfg["imgsz"] = imgsz
    cfg["batch"] = 1
    cfg["opset"] = opset
    cfg["simplify"] = True
    cfg["dynamic"] = False
    cfg["nms"] = False
    cfg["half"] = False
    cfg["int8"] = False
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def export_with_rockchip(args: argparse.Namespace) -> Path:
    repo = args.rockchip_ultralytics_dir.resolve()
    ensure_rockchip_repo(repo, args.auto_clone)
    if args.install_fork:
        run([sys.executable, "-m", "pip", "install", "-e", str(repo)])
    patch_default_yaml(repo, args.weights.resolve(), args.imgsz, args.opset)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    exporter = repo / "ultralytics" / "engine" / "exporter.py"
    run([sys.executable, str(exporter)], cwd=repo, env=env)
    candidate = args.weights.with_suffix(".onnx")
    if not candidate.exists():
        generated = sorted(args.weights.parent.glob("*.onnx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not generated:
            raise RuntimeError("Rockchip export finished but no ONNX file was found next to weights.")
        candidate = generated[0]
    return candidate


def export_with_standard_ultralytics(args: argparse.Namespace) -> Path:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Missing dependency: install ultralytics before standard ONNX export.") from exc
    model = YOLO(str(args.weights.resolve()))
    exported = model.export(format="onnx", imgsz=args.imgsz, opset=args.opset, simplify=True, dynamic=False, nms=False)
    return Path(exported)


def main() -> None:
    args = parse_args()
    if not args.weights.exists():
        raise FileNotFoundError(f"Weights do not exist: {args.weights}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "weights": str(args.weights.resolve()),
        "output": str(args.output.resolve()),
        "imgsz": args.imgsz,
        "opset": args.opset,
        "exporter": "rockchip_ultralytics_yolov8",
    }

    try:
        exported = export_with_rockchip(args)
    except Exception as exc:
        if not args.standard_fallback:
            raise
        print(f"Rockchip export failed, falling back to standard ultralytics export: {exc}")
        exported = export_with_standard_ultralytics(args)
        report["exporter"] = "standard_ultralytics_fallback"
        report["rockchip_error"] = str(exc)

    if exported.resolve() != args.output.resolve():
        shutil.copy2(exported, args.output)
    report["source_onnx"] = str(exported.resolve())
    report_path = args.output.with_suffix(".export_report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ONNX: {args.output.resolve()}")


if __name__ == "__main__":
    main()
