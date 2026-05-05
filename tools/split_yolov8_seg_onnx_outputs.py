#!/usr/bin/env python3
"""Split common YOLOv8-seg ONNX outputs for RKNN quantization.

Standard YOLOv8 segmentation exports usually contain a prediction tensor shaped
like (1, 4 + classes + masks, anchors) or (1, anchors, 4 + classes + masks),
plus a prototype tensor shaped like (1, masks, h, w). This script rewrites the
graph outputs to stable tensors:

  boxes, scores, mask_coeffs, protos
"""

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


def all_value_shapes(model: onnx.ModelProto) -> dict[str, list[int | None]]:
    inferred = shape_inference.infer_shapes(model)
    values = list(inferred.graph.output) + list(inferred.graph.value_info)
    shapes: dict[str, list[int | None]] = {}
    for value in values:
        tensor_type = value.type.tensor_type
        shapes[value.name] = [dim_value(dim) for dim in tensor_type.shape.dim]
    return shapes


def make_i64(name: str, values: list[int]) -> onnx.TensorProto:
    return numpy_helper.from_array(np.asarray(values, dtype=np.int64), name=name)


def make_slice(output_name: str, input_name: str, start: int, end: int, axis: int) -> onnx.NodeProto:
    prefix = output_name.replace("/", "_")
    return helper.make_node(
        "Slice",
        inputs=[f"{input_name}", f"{prefix}_starts", f"{prefix}_ends", f"{prefix}_axes", f"{prefix}_steps"],
        outputs=[output_name],
        name=f"SplitYolov8Seg{prefix}",
    )


def infer_pred_axis(shape: list[int | None], class_count: int | None, mask_count: int | None) -> tuple[int, int, int]:
    if len(shape) != 3:
        raise RuntimeError(f"prediction output must be 3D, got {shape}")
    candidates: list[tuple[int, int, int]] = []
    for axis in (1, 2):
        channel_count = shape[axis]
        anchor_count = shape[2 if axis == 1 else 1]
        if channel_count is None:
            continue
        if anchor_count is not None and channel_count > anchor_count:
            continue
        if class_count is not None and mask_count is not None:
            if channel_count == 4 + class_count + mask_count:
                candidates.append((axis, class_count, mask_count))
            continue
        if class_count is not None:
            inferred_mask = channel_count - 4 - class_count
            if inferred_mask > 0:
                candidates.append((axis, class_count, inferred_mask))
            continue
        if mask_count is not None:
            inferred_classes = channel_count - 4 - mask_count
            if inferred_classes > 0:
                candidates.append((axis, inferred_classes, mask_count))
            continue
        if channel_count > 5 and channel_count <= 512:
            inferred_mask = 32 if channel_count > 36 else max(1, channel_count - 5)
            inferred_classes = channel_count - 4 - inferred_mask
            if inferred_classes > 0:
                candidates.append((axis, inferred_classes, inferred_mask))
    if not candidates:
        raise RuntimeError(f"cannot infer channel axis/classes/masks from shape {shape}; pass --class-count/--mask-count")
    candidates.sort(key=lambda item: (item[2] != 32, item[0]))
    return candidates[0]


def infer_outputs(
    graph_outputs: list[str],
    shapes: dict[str, list[int | None]],
    source_output: str | None,
    proto_output: str | None,
    class_count: int | None,
    mask_count: int | None,
) -> tuple[str, list[int | None], int, int, int, str, list[int | None]]:
    if source_output:
        pred_name = source_output
        pred_shape = shapes.get(pred_name)
        if pred_shape is None:
            raise RuntimeError(f"cannot infer shape for source output: {pred_name}")
        axis, classes, masks = infer_pred_axis(pred_shape, class_count, mask_count)
    else:
        found = []
        for name in graph_outputs:
            shape = shapes.get(name)
            if shape and len(shape) == 3:
                try:
                    axis, classes, masks = infer_pred_axis(shape, class_count, mask_count)
                except RuntimeError:
                    continue
                found.append((name, shape, axis, classes, masks))
        if not found:
            raise RuntimeError("cannot find YOLOv8-seg prediction output")
        pred_name, pred_shape, axis, classes, masks = found[0]

    if proto_output:
        proto_name = proto_output
        proto_shape = shapes.get(proto_name)
        if proto_shape is None:
            raise RuntimeError(f"cannot infer shape for proto output: {proto_name}")
    else:
        proto_candidates = []
        for name in graph_outputs:
            shape = shapes.get(name)
            if name != pred_name and shape and len(shape) == 4:
                proto_candidates.append((name, shape))
        if not proto_candidates:
            raise RuntimeError("cannot find YOLOv8-seg proto output; pass --source-proto-output")
        proto_candidates.sort(key=lambda item: item[1][1] != masks if item[1][1] is not None else True)
        proto_name, proto_shape = proto_candidates[0]
    return pred_name, pred_shape, axis, classes, masks, proto_name, proto_shape


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input YOLOv8-seg ONNX")
    parser.add_argument("--output", required=True, type=Path, help="Output split ONNX")
    parser.add_argument("--class-count", type=int, help="Class count; inferred from channel count when omitted")
    parser.add_argument("--mask-count", type=int, help="Mask coefficient count; inferred when omitted")
    parser.add_argument("--source-output", help="Original prediction output name; defaults to inferred 3D output")
    parser.add_argument("--source-proto-output", help="Original proto output name; defaults to inferred 4D output")
    parser.add_argument("--boxes-output", default="boxes", help="Box output tensor name")
    parser.add_argument("--scores-output", default="scores", help="Score output tensor name")
    parser.add_argument("--mask-coeffs-output", default="mask_coeffs", help="Mask coefficient output tensor name")
    parser.add_argument("--protos-output", default="protos", help="Prototype output tensor name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = onnx.load(str(args.input))
    if not model.graph.output:
        raise RuntimeError("ONNX graph has no outputs")

    graph_output_names = [output.name for output in model.graph.output]
    shapes = all_value_shapes(model)
    pred_name, pred_shape, axis, class_count, mask_count, proto_name, proto_shape = infer_outputs(
        graph_output_names,
        shapes,
        args.source_output,
        args.source_proto_output,
        args.class_count,
        args.mask_count,
    )

    boxes_shape = list(pred_shape)
    scores_shape = list(pred_shape)
    mask_shape = list(pred_shape)
    boxes_shape[axis] = 4
    scores_shape[axis] = class_count
    mask_shape[axis] = mask_count

    slices = [
        (args.boxes_output, 0, 4),
        (args.scores_output, 4, 4 + class_count),
        (args.mask_coeffs_output, 4 + class_count, 4 + class_count + mask_count),
    ]
    for output_name, start, end in slices:
        model.graph.node.append(make_slice(output_name, pred_name, start, end, axis))
        prefix = output_name.replace("/", "_")
        model.graph.initializer.extend(
            [
                make_i64(f"{prefix}_starts", [start]),
                make_i64(f"{prefix}_ends", [end]),
                make_i64(f"{prefix}_axes", [axis]),
                make_i64(f"{prefix}_steps", [1]),
            ]
        )

    if args.protos_output != proto_name:
        model.graph.node.append(
            helper.make_node("Identity", inputs=[proto_name], outputs=[args.protos_output], name="SplitYolov8SegProtos")
        )

    del model.graph.output[:]
    model.graph.output.extend(
        [
            helper.make_tensor_value_info(args.boxes_output, TensorProto.FLOAT, boxes_shape),
            helper.make_tensor_value_info(args.scores_output, TensorProto.FLOAT, scores_shape),
            helper.make_tensor_value_info(args.mask_coeffs_output, TensorProto.FLOAT, mask_shape),
            helper.make_tensor_value_info(args.protos_output, TensorProto.FLOAT, proto_shape),
        ]
    )

    onnx.checker.check_model(model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    print(
        f"wrote {args.output}: boxes={boxes_shape}, scores={scores_shape}, "
        f"mask_coeffs={mask_shape}, protos={proto_shape}, class_count={class_count}, mask_count={mask_count}, axis={axis}"
    )


if __name__ == "__main__":
    main()
