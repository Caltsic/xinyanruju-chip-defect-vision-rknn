#!/usr/bin/env python3
"""Print YOLOv8-seg ONNX input/output shapes and split-readiness hints."""

from __future__ import annotations

import argparse
from pathlib import Path

import onnx
from onnx import shape_inference


def dim_value(dim) -> int | str | None:
    if dim.HasField("dim_value"):
        return int(dim.dim_value)
    if dim.HasField("dim_param"):
        return str(dim.dim_param)
    return None


def value_shape(value) -> list[int | str | None]:
    return [dim_value(dim) for dim in value.type.tensor_type.shape.dim]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="YOLOv8-seg ONNX path")
    parser.add_argument("--class-count", type=int, help="Expected class count")
    parser.add_argument("--mask-count", type=int, default=32, help="Expected mask coefficient count")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = onnx.load(str(args.model))
    inferred = shape_inference.infer_shapes(model)

    print(f"model={args.model.resolve()}")
    print("inputs:")
    for item in inferred.graph.input:
        print(f"  {item.name}: {value_shape(item)}")
    print("outputs:")
    for item in inferred.graph.output:
        shape = value_shape(item)
        hint = ""
        if len(shape) == 3:
            numeric = [dim if isinstance(dim, int) else None for dim in shape]
            channel_axes = []
            for axis in (1, 2):
                channels = numeric[axis]
                if channels is None:
                    continue
                if args.class_count is not None and channels == 4 + args.class_count + args.mask_count:
                    channel_axes.append(axis)
                elif args.class_count is None and channels > 36:
                    channel_axes.append(axis)
            if channel_axes:
                hint = f" pred_candidate channel_axis={channel_axes[0]}"
        elif len(shape) == 4:
            hint = " proto_candidate"
        print(f"  {item.name}: {shape}{hint}")

    print("split command:")
    cmd = [
        "python",
        "tools/split_yolov8_seg_onnx_outputs.py",
        "--input",
        str(args.model),
        "--output",
        str(args.model.with_name(f"{args.model.stem}_split.onnx")),
    ]
    if args.class_count is not None:
        cmd.extend(["--class-count", str(args.class_count)])
    if args.mask_count is not None:
        cmd.extend(["--mask-count", str(args.mask_count)])
    print("  " + " ".join(cmd))


if __name__ == "__main__":
    main()
