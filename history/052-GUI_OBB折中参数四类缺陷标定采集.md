# GUI OBB 折中参数四类缺陷标定采集

Updated: 2026-05-09

## Summary

本归档记录 GUI 配合 OBB 折中参数进行四类缺陷/分割样本采集的目标、代码改动、写出数据结构、验证结果和推荐使用命令。

不记录 SSH、密码、token、云服务器凭据或其他敏感凭据。

## User Goal

用户目标是使用 GUI 配合折中版 OBB 参数做四类缺陷/分割样本采集，先让 GUI 自动完成 chip OBB ROI 和 defect segmentation 的预标注，再由人工对特定角度样本做精修。

采集重点：

- 覆盖特定旋转角度下的 chip ROI。
- 保存完整可追溯的分割样本包，便于后续人工检查和 CVAT/训练流水线使用。
- 四类缺陷标签继续沿用现有类别，不在本次改名或重排。

## Settings Changes

涉及文件：

```text
tools/chip_capture_gui/settings.py
```

新增/使用 OBB 标定采集 profile 和 preset：

```text
OBB_CALIBRATION_PROFILE = chip-two-stage-obb-seg-imx678
OBB_CALIBRATION_PRESET
apply_obb_calibration_preset()
```

折中参数为：

```text
chip_conf = 0.45
chip_interval = 1
roi_smooth_alpha = 0.55
roi_hold = 1
```

该 preset 的定位是采集用折中值：比快速响应 `alpha=1.0` 更稳，比过强平滑更容易跟随角度变化，适合 GUI 采集时先稳定画面再保存样本。

## Qt GUI Changes

涉及文件：

```text
tools/chip_capture_gui/app.py
```

本次改动点：

- Qt GUI 支持 `--output-dir` 和 `--prefix`。
- `--output-dir` 和 `--prefix` 会传给 `SegSampleWriter`，用于控制 GUI 采集样本输出目录和文件名前缀。
- profile 切换到 OBB profile 时，会自动套用折中参数。
- CLI 构造运行命令时，对 OBB profile 自动包含折中参数。
- 新增/确认 CLI override 参数：
  - `--roi-margin`
  - `--roi-smooth-alpha`
  - `--roi-hold`
  - `--chip-interval`
  - `--chip-conf`

OBB profile 自动构造命令时已确认包含：

```text
--chip-model-kind obb
--defect-model-kind seg
--chip-conf 0.45
--chip-interval 1
--roi-smooth-alpha 0.55
--roi-hold 1
```

## OpenCV GUI Changes

涉及文件：

```text
tools/chip_capture_gui/opencv_app.py
```

本次改动点：

- OpenCV GUI 修复/确认 `--output-dir` 和 `--prefix` 真正用于 `SegSampleWriter`。
- OpenCV fallback 与 Qt GUI 保持一致，对 OBB profile 自动套用折中参数。
- OpenCV fallback 同样支持以下覆盖参数：
  - `--roi-margin`
  - `--roi-smooth-alpha`
  - `--roi-hold`
  - `--chip-interval`
  - `--chip-conf`

## Seg Sample Output

GUI 采集写出由 `SegSampleWriter` 完成。

输出结构包括：

```text
images/
labels/
images_full/
previews/
meta/
manifest.csv
```

四类缺陷标签沿用：

```text
ZF-scratch
scratch
broken
pinbreak
```

`meta/` 中已包含 OBB crop 追溯所需字段：

```text
crop_obb_points
crop_to_full_affine
full_to_crop_affine
```

当前 meta 未显式保存角度字段，但角度可由 OBB 点和仿射信息重建。后续如果训练/复核流程需要直接按角度筛选，可追加：

```text
obb_angle
```

## Verification

已完成的验证：

- 已运行 `py_compile`。
- Qt help 显示新增参数。
- OpenCV help 显示新增参数。
- 构造命令验证 OBB profile 自动包含 OBB chip 模型、seg defect 模型和折中参数。

已确认构造命令包含：

```text
--chip-model-kind obb
--defect-model-kind seg
--chip-conf 0.45
--chip-interval 1
--roi-smooth-alpha 0.55
--roi-hold 1
```

## Recommended Commands

Qt GUI 推荐命令：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --profile chip-two-stage-obb-seg-imx678 --output-dir .\chip_seg\captures\obb_angle_refine_20260509
```

OpenCV fallback 推荐命令：

```powershell
F:\anaconda\python.exe -m tools.chip_capture_gui --opencv --profile chip-two-stage-obb-seg-imx678 --output-dir .\chip_seg\captures\obb_angle_refine_20260509
```

如需自定义文件名前缀，可追加：

```powershell
--prefix seg
```

如需临场覆盖折中参数，可追加对应 CLI override，例如：

```powershell
--chip-conf 0.45 --chip-interval 1 --roi-smooth-alpha 0.55 --roi-hold 1
```

## Capture Workflow

使用方式：

1. 启动 GUI 后点击 `Start` 开流。
2. 确认 chip ROI 稳定，且 mask/contour 预标注合理。
3. Qt GUI 中点击 `Save Seg Sample` 或按 `S` 保存。
4. OpenCV GUI 中按 `S` 或 `V` 保存。
5. 每次换样本或调整角度后，先等待画面和 ROI 稳定，再保存样本。

采集时建议保留 `images_full/`、`previews/` 和 `meta/`，不要只拷贝裁剪图和 labels。后续人工精修、角度回溯、crop/full 坐标映射和问题样本排查都会依赖这些伴随文件。

## Follow-Up Notes

- 本次目标是采集标定样本，不是最终确定生产实时参数。
- 折中参数适合 GUI 采集时人工观察和保存，不排除后续针对板端实时检测继续使用更快或更稳的参数组。
- 如果后续需要按角度统计采集覆盖率，优先从 `crop_obb_points` 或 affine 信息重建；若频繁使用，再在 meta 中追加显式 `obb_angle` 字段。
