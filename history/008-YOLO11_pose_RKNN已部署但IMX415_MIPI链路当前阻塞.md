# YOLO11 Pose RKNN 已部署但 IMX415 MIPI 链路当前阻塞

更新日期：2026-04-28

## 当前目标

在 `yolo` 分支上运行 YOLO11n-pose 姿态模型，让泰山派3M-RK3576 通过 IMX415 实时识别人体姿态骨骼，并在电脑端实时显示。

## 已完成

- 本地 YOLO11n-pose ONNX 来源：`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料\8.【立创·泰山派3】Ai应用\YOLO11\yolo11n-pose.onnx`。
- 已确认 YOLO11n-pose 与 RKNN Model Zoo 的 YOLOv8-pose 输出结构兼容：输入 `1x3x640x640`，输出为 3 个尺度特征和 1 个 `17x3x8400` 关键点输出。
- 已使用 RKNN Toolkit2 转换为 RK3576 FP 模型：`rknn_work/models/yolo11n_pose_rk3576_fp.rknn`。
- 已新增板端示例源码：`rknn_work/board_yolo11_src/examples/yolo11_pose/`。
- 已在板端编译并安装：`/userdata/rknn_yolo11_demo/rknn_yolo11_pose_camera_stream`。
- 已部署模型：`/userdata/rknn_yolo11_demo/model/yolo11n_pose_rk3576_fp.rknn`。
- Windows 端实时显示脚本 `tools/adb_imx415_rknn_live_view.py` 已支持 `--mode pose`，协议 magic 为 `RYP1`，会绘制 COCO 17 点骨骼。

## 运行命令

实时窗口：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --mode pose
```

无窗口冒烟测试：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --mode pose --frames 3 --headless --save-snapshot .\captures\rknn_pose_live_smoke.jpg
```

姿态模式默认使用 `640x360 @ 5fps`，用于控制 NPU 姿态推理、CPU 后处理和 ADB 回传压力。

## 当前阻塞

板端 YOLO11-pose 程序已能加载 RKNN 模型，但当前 `/dev/video42` 无法输出帧。即使不运行 YOLO，直接使用 `v4l2-ctl` 从 `/dev/video42` 采集 `960x540 NV12` 单帧也会超时，输出文件大小为 `0 bytes`。

已尝试：

- 清理残留 `rknn_yolo11` 和 `v4l2-ctl` 进程。
- 重启 `rkaiq_3A.service`，服务重启成功并保持 `active/running`。
- 直接采集 `/dev/video42`，仍然 `timeout`。

关键错误：

```text
MIPI_CSI2 ERR2:0x10000000
rockchip-mipi-csi2 mipi1-csi2: stream OFF
imx415 5-0037: s_stream: 0. 3864x2192, hdr: 0, bpp: 10
```

## 判断

当前阻塞位于 IMX415 到 RK3576 的 MIPI/CSI/ISP 采集链路，不在 YOLO11-pose RKNN 模型、NPU 加载或电脑端显示脚本。下一步应优先检查 IMX415 排线方向、接口接触、供电和摄像头模组状态；恢复 `/dev/video42` 单帧采集后，再运行 `--mode pose` 实时骨骼显示。
