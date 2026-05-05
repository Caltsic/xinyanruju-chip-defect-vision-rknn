# INT8 优先的二阶段规划修正

更新日期：2026-05-04

## 修正原因

- 当前主硬件是泰山派 3M / RK3576 NPU，板端部署的合理目标是 INT8，而不是长期依赖 FP RKNN。
- 缺陷检测链路已经验证过 INT8 RKNN 可在板端运行，说明 INT8 本身不是不可用路线。
- chip ROI INT8 当前“能加载但无框”是一个明确工程问题，应优先诊断输出量化、反量化、阈值和校准集，而不是直接绕到 FP 施工。
- FP RKNN 在 MaixCAM 当前画面可出框，价值是证明训练数据、摄像头画面分布、板端取流和基础后处理大体成立；它不能证明最终部署形态已经正确。

## 修正后的优先级

1. chip ROI INT8 诊断。
   - 在板端增加可开关统计：raw output min/max、top score、xywh 范围、反量化 scale/zero point、NMS 前候选数量。
   - 用同一张 clean frame 对照 ONNX、FP RKNN、INT8 RKNN。
   - 先判断是 C++ 后处理反量化/阈值问题，还是 RKNN 量化校准问题。

2. chip ROI INT8 修复。
   - 若是后处理问题，修 C++ 并保留现有 INT8 模型。
   - 若是量化问题，重新生成校准集并重转 `chip_roi_yolov8_detect_int8.rknn`。
   - 通过 MaixCAM 当前画面 `conf=0.25` 出稳定 chip 框后，再进入二阶段主线。

3. INT8 二阶段实时融合。
   - 一个板端进程内串联：全图 chip ROI INT8 -> ROI crop -> defect INT8。
   - 后处理改为运行时 class count，避免一类 chip 模型和四类缺陷模型共享编译期 `OBJ_CLASS_NUM` 时互相污染。
   - 输出类别映射：`chip` 为 class id `0`，缺陷类别整体 `+1`。

4. FP 的定位。
   - FP 仅作为诊断基线、临时回退或二阶段架构问题隔离工具。
   - 不把 FP chip ROI 作为当前硬件上的默认最终路线。

## 成功标准

- `chip_roi_yolov8_detect_int8.rknn` 在板端 MaixCAM 当前画面稳定输出 chip 框。
- INT8 chip ROI 与 ONNX/FP 在同帧上的框位置接近，置信度差异可解释。
- 二阶段实时 profile 默认使用 chip ROI INT8 + defect INT8。
- FP profile 保留为显式诊断选项，而不是主命令隐式依赖。

## 后续入口

- 施工计划：`plans/chip_roi_two_stage_runtime_plan.md`
- 当前任务表：`task_plan.md`
- 运行部署归档：`history/020-chip_roi_realtime_deployment_and_next_stage.md`
