# MaixCAM 芯片 ROI 预处理最小闭环

更新时间：2026-05-04

## 背景

MaixCAM 当前画面已经能拍到较清晰芯片，但整颗芯片在 `1280x720` 全幅中占比仍偏小。当前 4 类缺陷模型没有 `chip` 类，直接全图检测时不会框整颗芯片，且破损处在全图中的模型响应接近 0。

## 关键判断

- 当前模型类别：

```text
ZF-scratch
scratch
broken
pinbreak
```

- 全图直接检测不是合适入口；应先定位芯片 ROI，再在 ROI 上运行缺陷模型。
- 轻量预处理有价值，但不应替代 ROI/尺度处理。
- 默认保留 `raw` 分支用于破损类，增加 `light_gamma_clahe` 分支辅助划痕/引脚类。
- 强白平衡会让当前破损样本更倾向 `ZF-scratch`，不作为默认唯一预处理。

## 已实现工具

新增：

```text
tools/roi_defect_closed_loop.py
```

流程：

```text
MaixCAM 全图
 -> 自动定位 chip ROI
 -> ROI 加 margin 裁剪
 -> raw + light_gamma_clahe 两路 ONNX 推理
 -> 合并/NMS
 -> 检测框映射回原图
```

## 使用命令

从当前 MaixCAM 抓帧并跑闭环：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py --capture-maixcam --save-dir .\captures\roi_defect_closed_loop_capture
```

对已保存清洁帧跑闭环：

```powershell
F:\anaconda\python.exe .\tools\roi_defect_closed_loop.py .\captures\maixcam_broken_current_clean.jpg --save-dir .\captures\roi_defect_closed_loop_final
```

## 当前验证结果

上一张破损芯片实拍图：

```text
raw: broken 0.359
light_gamma_clahe: broken 0.191, ZF-scratch 0.126, pinbreak 0.114
merged: broken 0.359/raw
```

输出：

```text
captures/roi_defect_closed_loop_final/maixcam_broken_current_clean_roi_closed_loop.jpg
captures/roi_defect_closed_loop_final/maixcam_broken_current_clean_variants.jpg
```

当前 MaixCAM 抓帧闭环也已跑通，输出：

```text
captures/roi_defect_closed_loop_capture/maixcam_current_clean_roi_closed_loop.jpg
captures/roi_defect_closed_loop_capture/maixcam_current_clean_variants.jpg
```

## 训练集对 chip 类的帮助

现有训练集虽然没有 `chip` 标签，但图像中芯片通常与背景分离明显，可以用暗区域/边缘分割生成 `chip` 伪标签。已生成预览：

```text
captures/chip_pseudo_probe/chip_pseudo_preview.jpg
```

该伪标签质量足以启动 `chip` 定位模型训练，但正式训练前应抽检修正。

## 下一步

- 将 PC 端 ROI/preprocess 最小闭环下沉到板端 C++/RKNN。
- 或先训练 1 类 `chip` 定位模型，替代传统视觉 ROI。
- 缺陷模型后续训练应加入部署侧 ROI、轻量 gamma/CLAHE 增强和真实 MaixCAM 样本。
