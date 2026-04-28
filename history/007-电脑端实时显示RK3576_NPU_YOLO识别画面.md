# 电脑端实时显示 RK3576 NPU YOLO 识别画面

更新时间：2026-04-28

## 目标

让 IMX415 摄像头画面在板端使用 RK3576 NPU 跑 YOLO11 RKNN 推理，并在电脑端实时显示带检测框的画面。

## 实现架构

板端：

- 程序：`/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream`
- 采集：`/dev/video42`
- 格式：`NV12`
- 默认：`960x540 @ 8fps`
- 模型：`/userdata/rknn_yolo11_demo/model/yolo11n_rk3576.rknn`
- 推理：RKNN Runtime + RK3576 NPU

电脑端：

- 脚本：`tools/adb_imx415_rknn_live_view.py`
- 通过 `adb exec-out` 启动板端程序。
- 读取板端二进制流。
- 使用 OpenCV 将 NV12 转 BGR。
- 在电脑端绘制 COCO 类别、置信度和边框。

## 新增/修改文件

板端源码：

- `rknn_work/board_yolo11_src/examples/yolo11/cpp/live_camera_yolo.cc`
- `rknn_work/board_yolo11_src/examples/yolo11/cpp/CMakeLists.txt`

电脑端脚本：

- `tools/adb_imx415_rknn_live_view.py`

文档：

- `README.md`

## 流协议

板端 stdout 只输出二进制协议，日志重定向到 stderr。

每帧：

- magic：`RYL1`
- little-endian `uint32`：`width`
- little-endian `uint32`：`height`
- little-endian `uint32`：`frame_index`
- little-endian `uint32`：`det_count`
- little-endian `uint32`：`payload_size`
- 检测框数组：`uint32 class_id + float score + float x1 + float y1 + float x2 + float y2`
- payload：连续 NV12 frame，大小为 `width * height * 3 / 2`

## 板端构建部署

本地源码包：

- `F:\WORKSPACE\泰山派\rknn_work\board_yolo11_src.tar.gz`

已推送并在板端原生编译安装。

板端目标文件：

- `/userdata/rknn_yolo11_demo/rknn_yolo11_camera_stream`

文件大小：

- 约 `972K`

构建命令核心：

```bash
cd /tmp/rknn_yolo11_build
cmake /tmp/rknn_yolo11_src/examples/yolo11/cpp \
  -DTARGET_SOC=rk3576 \
  -DCMAKE_SYSTEM_NAME=Linux \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_ASAN=OFF \
  -DDISABLE_RGA=OFF \
  -DDISABLE_LIBJPEG=OFF \
  -DCMAKE_INSTALL_PREFIX=/userdata/rknn_yolo11_demo
make -j2 rknn_yolo11_camera_stream
make install
```

## 电脑端运行命令

实时显示：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py
```

无窗口冒烟测试：

```powershell
F:\anaconda\python.exe .\tools\adb_imx415_rknn_live_view.py --frames 3 --headless --save-snapshot .\captures\rknn_live_smoke.jpg
```

已验证结果：

- 命令退出码：`0`
- 输出：`Processed frames: 3`
- 快照：`F:\WORKSPACE\泰山派\captures\rknn_live_smoke.jpg`
- 快照叠加信息显示：`FPS 11.4 | 960x540 | det 0 | frame 2`

当前画面未检测到 COCO 目标，因此 `det 0` 是合理结果。

## 注意事项

- 必须用 `adb exec-out`，不要用 `adb shell` 拉二进制流。
- 板端程序 stdout 是协议数据，不能混入日志。
- 板端日志默认在 `/tmp/rknn_yolo11_camera_stream.log`。
- 退出窗口按 `q` 或 `Esc`。
- 默认分辨率保持 `960x540`，宽度 16 对齐，可保证 RKNN demo 内部 RGA 转换路径稳定。

