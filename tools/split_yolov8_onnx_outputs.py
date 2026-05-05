#!/usr/bin/env python3
"""Split a YOLOv8 detect ONNX output into box and score tensors.

Rockchip INT8 conversion quantizes each output tensor with one scale. A
single YOLOv8 output shaped like (1, 4 + classes, anchors) mixes 0..640 box
coordinates with 0..1 class scores, which can zero out scores after INT8
quantization. Splitting the graph output lets RKNN quantize boxes and scores
with separate scales without retraining.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import onnx
from onnx import TensorProto, helper, numpy_helper, shape_inference
import numpy as np


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
        name=f"SplitYolov8{prefix}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input YOLOv8 ONNX")
    parser.add_argument("--output", required=True, type=Path, help="Output split ONNX")
    parser.add_argument("--class-count", type=int, help="Class count; inferred from channel count when omitted")
    parser.add_argument("--source-output", help="Original output name; defaults to the first graph output")
    parser.add_argument("--box-output", default="yolov8_boxes", help="Box output tensor name")
    parser.add_argument("--score-output", default="yolov8_scores", help="Score output tensor name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = onnx.load(str(args.input))
    if not model.graph.output:
        raise RuntimeError("ONNX graph has no outputs")

    source_output = args.source_output or model.graph.output[0].name
    shape = output_shape(model, source_output)
    if len(shape) != 3:
        raise RuntimeError(f"expected 3D YOLOv8 output, got shape {shape}")

    if shape[1] is not None and shape[1] >= 5:
        channel_axis = 1
        channel_count = shape[1]
    elif shape[2] is not None and shape[2] >= 5:
        channel_axis = 2
        channel_count = shape[2]
    else:
        raise RuntimeError(f"cannot infer channel axis from shape {shape}")

    class_count = args.class_count if args.class_count is not None else channel_count - 4
    if class_count <= 0 or channel_count != class_count + 4:
        raise RuntimeError(f"invalid class count {class_count} for output shape {shape}")

    box_shape = list(shape)
    score_shape = list(shape)
    box_shape[channel_axis] = 4
    score_shape[channel_axis] = class_count

    box_node = make_slice(args.box_output, source_output, 0, 4, channel_axis)
    score_node = make_slice(args.score_output, source_output, 4, 4 + class_count, channel_axis)
    model.graph.node.extend([box_node, score_node])

    for output_name, start, end in (
        (args.box_output, 0, 4),
        (args.score_output, 4, 4 + class_count),
    ):
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
            helper.make_tensor_value_info(args.score_output, TensorProto.FLOAT, score_shape),
        ]
    )

    onnx.checker.check_model(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    print(f"wrote {args.output} with outputs {args.box_output} {box_shape}, {args.score_output} {score_shape}")


if __name__ == "__main__":
    main()
