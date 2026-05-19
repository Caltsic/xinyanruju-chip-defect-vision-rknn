#!/usr/bin/env python3
"""Split a YOLOv8-OBB ONNX output into box, angle, and score tensors."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper, shape_inference


def dim_value(dim) -> int | None:
    if dim.HasField("dim_value"):
        return int(dim.dim_value)
    return None


def output_shape(model: onnx.ModelProto, output_name: str) -> list[int | None]:
    inferred = shape_inference.infer_shapes(model)
    for value in list(inferred.graph.output) + list(inferred.graph.value_info):
        if value.name != output_name:
            continue
        tensor_type = value.type.tensor_type
        return [dim_value(dim) for dim in tensor_type.shape.dim]
    raise RuntimeError(f"cannot infer shape for output: {output_name}")


def make_i64(name: str, values: list[int]) -> onnx.TensorProto:
    return numpy_helper.from_array(np.asarray(values, dtype=np.int64), name=name)


def make_slice(output_name: str, input_name: str, start: int, end: int, axis: int) -> onnx.NodeProto:
    prefix = output_name.replace("/", "_")
    return helper.make_node(
        "Slice",
        inputs=[
            input_name,
            f"{prefix}_starts",
            f"{prefix}_ends",
            f"{prefix}_axes",
            f"{prefix}_steps",
        ],
        outputs=[output_name],
        name=f"SplitYolov8Obb{prefix}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input YOLOv8-OBB ONNX")
    parser.add_argument("--output", required=True, type=Path, help="Output split ONNX")
    parser.add_argument("--class-count", type=int, help="Class count; inferred from channel count when omitted")
    parser.add_argument("--source-output", help="Original output name; defaults to the first graph output")
    parser.add_argument("--box-output", default="yolov8_obb_boxes", help="Box output tensor name")
    parser.add_argument("--angle-output", default="yolov8_obb_angle", help="Angle output tensor name")
    parser.add_argument("--score-output", default="yolov8_obb_scores", help="Score output tensor name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = onnx.load(str(args.input))
    if not model.graph.output:
        raise RuntimeError("ONNX graph has no outputs")

    source_output = args.source_output or model.graph.output[0].name
    shape = output_shape(model, source_output)
    if len(shape) != 3:
        raise RuntimeError(f"expected 3D YOLOv8-OBB output, got shape {shape}")

    if shape[1] is not None and shape[1] >= 6:
        channel_axis = 1
        channel_count = shape[1]
    elif shape[2] is not None and shape[2] >= 6:
        channel_axis = 2
        channel_count = shape[2]
    else:
        raise RuntimeError(f"cannot infer channel axis from shape {shape}")

    class_count = args.class_count if args.class_count is not None else channel_count - 5
    if class_count <= 0 or channel_count != class_count + 5:
        raise RuntimeError(f"invalid class count {class_count} for output shape {shape}")

    box_shape = list(shape)
    angle_shape = list(shape)
    score_shape = list(shape)
    box_shape[channel_axis] = 4
    angle_shape[channel_axis] = 1
    score_shape[channel_axis] = class_count

    # Ultralytics YOLOv8-OBB export concatenates decoded xywh, class scores,
    # then angle: [x, y, w, h, cls..., theta].
    split_specs = [
        (args.box_output, 0, 4, box_shape),
        (args.angle_output, 4 + class_count, 5 + class_count, angle_shape),
        (args.score_output, 4, 4 + class_count, score_shape),
    ]
    model.graph.node.extend(
        [make_slice(output_name, source_output, start, end, channel_axis) for output_name, start, end, _ in split_specs]
    )

    for output_name, start, end, _ in split_specs:
        prefix = output_name.replace("/", "_")
        model.graph.initializer.extend(
            [
                make_i64(f"{prefix}_starts", [start]),
                make_i64(f"{prefix}_ends", [end]),
                make_i64(f"{prefix}_axes", [channel_axis]),
                make_i64(f"{prefix}_steps", [1]),
            ]
        )

    del model.graph.output[:]
    model.graph.output.extend(
        [
            helper.make_tensor_value_info(args.box_output, TensorProto.FLOAT, box_shape),
            helper.make_tensor_value_info(args.angle_output, TensorProto.FLOAT, angle_shape),
            helper.make_tensor_value_info(args.score_output, TensorProto.FLOAT, score_shape),
        ]
    )

    onnx.checker.check_model(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    print(
        f"wrote {args.output}: boxes={box_shape}, angle={angle_shape}, "
        f"scores={score_shape}, class_count={class_count}, axis={channel_axis}"
    )


if __name__ == "__main__":
    main()
