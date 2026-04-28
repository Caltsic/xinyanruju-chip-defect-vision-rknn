# YOLO11 RKNN 已在 RK3576 NPU 单帧识别跑通

更新时间：2026-04-28

## 模型功能

当前部署模型是 `YOLO11n` 通用目标检测模型，默认 COCO 80 类。

功能输出：

- 图像中目标类别。
- 目标置信度。
- 目标边界框。

当前模型不是专用工业/人脸/车牌模型，默认识别范围是 COCO 常见物体，例如 `person`、`bus`、`car`、`chair`、`bottle` 等。

## RKNN 转换结果

输入 ONNX：

`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料\8.【立创·泰山派3】Ai应用\YOLO11\yolo11n.onnx`

输出 RKNN：

`F:\WORKSPACE\泰山派\rknn_work\models\yolo11n_rk3576.rknn`

文件大小：

- 约 `9.4M`

转换配置：

- `target_platform = rk3576`
- `dtype = fp`
- 未做 int8 量化校准。

## 板端部署方式

采用 C++ demo 直接链接 RKNN Runtime，不依赖板端 Python `rknnlite`。

原因：

- 板端默认 Python 是 `3.13.12`，没有匹配的 RKNN Lite2 `cp313` wheel。
- `/usr/bin/python3` 是 `3.11.2`，可匹配本地 Lite2 `cp311` wheel，但当前先走 C++ runtime 更稳。
- 板端已有 `librknnrt.so` 和 `rknn_server`。

板端已部署目录：

`/userdata/rknn_yolo11_demo`

核心文件：

- `/userdata/rknn_yolo11_demo/rknn_yolo11_demo`
- `/userdata/rknn_yolo11_demo/rknn_yolo11_demo_zero_copy`
- `/userdata/rknn_yolo11_demo/model/yolo11n_rk3576.rknn`
- `/userdata/rknn_yolo11_demo/model/coco_80_labels_list.txt`
- `/userdata/rknn_yolo11_demo/model/bus.jpg`
- `/userdata/rknn_yolo11_demo/lib/librknnrt.so`
- `/userdata/rknn_yolo11_demo/lib/librga.so`

## 板端构建记录

WSL 缺少 `cmake` 和 `aarch64-linux-gnu-g++`，未继续补交叉编译器。

板端已确认具备：

- `/usr/bin/gcc`
- `/usr/bin/g++`
- `/usr/bin/cmake`
- `/usr/bin/make`
- `/usr/bin/pkg-config`

因此使用板端原生编译。

本地最小源码包：

- `F:\WORKSPACE\泰山派\rknn_work\board_yolo11_src`
- `F:\WORKSPACE\泰山派\rknn_work\board_yolo11_src.tar.gz`

源码包只包含：

- `examples/yolo11/cpp`
- `examples/yolo11/model/bus.jpg`
- `examples/yolo11/model/coco_80_labels_list.txt`
- `examples/yolo11/model/yolo11n_rk3576.rknn`
- `utils`
- RK3576/aarch64 必需的 `3rdparty` 子集。

板端 CMake 构建参数：

```bash
cmake /tmp/rknn_yolo11_src/examples/yolo11/cpp \
  -DTARGET_SOC=rk3576 \
  -DCMAKE_SYSTEM_NAME=Linux \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_ASAN=OFF \
  -DDISABLE_RGA=OFF \
  -DDISABLE_LIBJPEG=OFF \
  -DCMAKE_INSTALL_PREFIX=/userdata/rknn_yolo11_demo
make -j2
make install
```

## 已验证运行命令

基准图片：

```bash
cd /userdata/rknn_yolo11_demo
export LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH
./rknn_yolo11_demo model/yolo11n_rk3576.rknn model/bus.jpg
```

基准识别结果：

- `bus @ (90 135 552 435) 0.939`
- `person @ (108 236 223 535) 0.897`
- `person @ (212 240 284 509) 0.847`
- `person @ (477 230 559 521) 0.837`
- `person @ (79 358 116 516) 0.485`

这证明 RKNN 模型、RKNN Runtime、RGA 预处理、YOLO11 后处理和 NPU 推理链路已跑通。

## 摄像头单帧识别

`ffmpeg` 不能直接把 `/dev/video42` 当普通 V4L2 capture device 打开，因为该节点是 `Video Capture Multiplanar`。

可用抓图方式：

```bash
cd /userdata/rknn_yolo11_demo
v4l2-ctl -d /dev/video42 \
  --set-fmt-video width=960,height=540,pixelformat=NV12 \
  --stream-mmap 3 \
  --stream-count 3 \
  --stream-skip 2 \
  --stream-to /tmp/camera_960x540.nv12

ffmpeg -hide_banner -loglevel error -y \
  -f rawvideo -pix_fmt nv12 -s 960x540 \
  -i /tmp/camera_960x540.nv12 \
  -frames:v 1 model/camera.jpg
```

摄像头图片推理：

```bash
cd /userdata/rknn_yolo11_demo
export LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH
./rknn_yolo11_demo model/yolo11n_rk3576.rknn model/camera.jpg
```

结果：

- 推理执行成功，日志出现 `rknn_run`。
- 当前摄像头画面未检测到超过阈值的 COCO 目标，因此没有类别框输出。
- 已生成输出图。

本地回收文件：

- `F:\WORKSPACE\泰山派\captures\rknn_yolo11_camera_input.jpg`
- `F:\WORKSPACE\泰山派\captures\rknn_yolo11_camera_out.png`
- `F:\WORKSPACE\泰山派\captures\rknn_yolo11_bus_out.png`

## 后续建议

下一步要做实时识别时，不建议继续用“抓一帧 raw -> ffmpeg 转 jpg -> demo 读 jpg”的链路。

推荐路线：

1. 基于 C++ demo 增加 V4L2 multiplanar NV12 采集。
2. 直接把 `/dev/video42` 的 NV12 frame 转为 demo 所需输入。
3. 保留 RKNN Runtime、RGA resize、YOLO11 后处理。
4. 增加循环推理、FPS 统计和可选保存/推流输出。

