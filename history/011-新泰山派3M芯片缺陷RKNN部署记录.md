# 新泰山派3M芯片缺陷 RKNN 部署记录

更新时间：2026-05-03

## 新板信息

- ADB serial：`23f3c08e840ba991`
- 系统：Debian GNU/Linux 12 bookworm
- 内核：`Linux TaishanPi-3M 6.1.99 #2 SMP Mon Mar 30 16:03:20 CST 2026 aarch64`
- 编译工具：`cmake`、`make`、`gcc`、`g++` 均存在
- 摄像头节点：`/dev/video42`、`/dev/v4l-subdev7` 存在
- 原始状态：`/userdata/rknn_yolo11_demo` 不存在

## 已部署内容

使用本地包：

```text
rknn_work/board_yolo11_src_chip_defect.tar.gz
```

推送到板端：

```text
/tmp/board_yolo11_src_chip_defect.tar.gz
```

板端原生编译并安装到：

```text
/userdata/rknn_yolo11_demo
```

关键文件：

```text
/userdata/rknn_yolo11_demo/rknn_chip_defect_camera_stream
/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream
/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_int8.rknn
/userdata/rknn_yolo11_demo/model/chipcheck_yolov8_detect_fp.rknn
/userdata/rknn_yolo11_demo/model/chip_defect_labels.txt
/userdata/rknn_yolo11_demo/lib/librknnrt.so
/userdata/rknn_yolo11_demo/lib/librga.so
```

本地 PC 端默认 ADB serial 已改为：

```text
23f3c08e840ba991
```

## 验证结果

模型加载成功，板端日志显示：

```text
model input num: 1, output num: 1
input:  images, dims=[1, 640, 640, 3], type=INT8
output: output0, dims=[1, 8, 8400], type=INT8
camera /dev/video42 configured: 960x540 NV12
```

但短帧实时冒烟未收到画面：

```text
Processed frames: 0
camera dequeue timeout
```

独立 `v4l2-ctl` 在 `/dev/video42` 上以 `3840x2160` 和 `960x540` 取流均无法输出帧，生成文件为 0 字节。

内核日志显示：

```text
MIPI_CSI2 ERR2:0x10000000
rockchip-mipi-csi2 mipi1-csi2: stream OFF
imx415 5-0037: s_stream: 0. 3864x2192, hdr: 0, bpp: 10
```

## 结论

新泰山派3M上的 RKNN 模型、二进制和运行库已经部署完成；当前未能实时显示的阻塞点不是 RKNN 部署，而是 IMX415 到 RK3576 的 MIPI/CSI 摄像头输入流没有正常出帧。

下一步优先检查：

1. IMX415 排线方向、压接、接口是否松动。
2. 摄像头供电与模组固定。
3. 重启板子后先用 `v4l2-ctl` 验证 `/dev/video42` 能否出帧。
4. 出帧后再运行：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py
```
