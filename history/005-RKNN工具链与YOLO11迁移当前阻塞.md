# RKNN 工具链与 YOLO11 迁移当前阻塞

更新时间：2026-04-28

状态更新：

- 本文件记录迁移前工具链恢复和阻塞状态。
- 2026-04-28 后续已完成 YOLO11 RKNN 转换、板端 C++ demo 部署和 RK3576 NPU 单帧识别验证。
- 完成状态见：`006-YOLO11_RKNN已在RK3576_NPU单帧识别跑通.md`。

## 目标

将本地 `YOLO11/yolo11n.onnx` 转换为 RK3576 平台 RKNN 模型，并迁移到泰山派3M-RK3576 的 NPU 上运行。

## 已确认目标平台

- `target_platform = rk3576`

官方来源已核实：

- `https://github.com/airockchip/rknn-toolkit2`
- `https://github.com/airockchip/rknn_model_zoo`

## 板端 RKNN Runtime 状态

板端架构：

- `aarch64`

板端已有：

- `/usr/lib64/librknnrt.so`
- `/usr/lib/librknnrt.so`
- `/usr/bin/rknn_server`
- `/usr/bin/rknn_common_test`
- `/usr/share/model/RK3576/mobilenet_v1.rknn`

板端没有：

- Python `rknn`
- Python `rknn.api`
- Python `rknnlite`

工程判断：

- 板端具备 runtime，不具备完整转换/开发环境。
- 最稳路线是 PC/WSL 用 `rknn-toolkit2` 转 RKNN，板端用 C/C++ runtime 链接 `librknnrt.so` 跑推理。

## 本地模型状态

推荐转换：

`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料\8.【立创·泰山派3】Ai应用\YOLO11\yolo11n.onnx`

模型信息：

- 大小：`10,527,859 bytes`
- 输入：`images: float32 [1, 3, 640, 640]`
- 输出：9 个 tensor，三尺度原始检测头：
  - `[1,64,80,80]`, `[1,80,80,80]`, `[1,1,80,80]`
  - `[1,64,40,40]`, `[1,80,40,40]`, `[1,1,40,40]`
  - `[1,64,20,20]`, `[1,80,20,20]`, `[1,1,20,20]`

暂不推荐：

- `YOLOv8\yolov8n.onnx`
- 原因：缺少 `yolov8n.onnx.data`，不是完整可加载模型。

注意：

- 当前 YOLO11 ONNX 是 9 输出原始检测头，不是简化的 `(1,84,8400)` 单输出。
- 后续 NPU demo 必须实现 YOLO11/DFL 后处理，不能直接沿用简化 ONNX 后处理。

## Windows/WSL 工具链状态

Windows 本机未发现：

- `rknn-toolkit2`
- `rknn-toolkit-lite2`
- `rknn_converter`

WSL：

- Ubuntu 22.04 可用。
- Python：`3.10.12`
- WSL 当前以 root 运行。
- 已安装 `python3.10-venv`。

RKNN 工作目录：

- `F:\WORKSPACE\泰山派\rknn_work`
- WSL 路径：`/mnt/f/WORKSPACE/泰山派/rknn_work`

已完成：

- `rknn_work/models/` 已创建。
- `rknn_work/rknn-toolkit2/` 已拉取。
- 当前 commit：`59a913d`
- 目录中有 `doc/*V2.3.2*` 和 `packages/`。
- `rknn_work/venv` 已创建。
- `rknn_work/rknn_model_zoo/` 已拉取。
- 当前 `rknn_model_zoo` commit：`bad6c73`
- `rknn_model_zoo/examples/yolo11/` 存在，包含 `README.md`、`python/convert.py`、`python/yolo11.py`、C++ demo 和示例图片。

venv 当前已安装并验证可导入：

- `numpy 1.26.4`
- `onnx 1.21.0`
- `onnxruntime 1.23.2`
- `cv2 4.11.0`
- `scipy 1.15.3`
- `protobuf 4.25.4`
- `torch 2.4.0+cpu`
- `rknn-toolkit2 2.3.2`

兼容性注意：

- `setuptools 82` 不提供 `pkg_resources`，RKNN Toolkit2 实例化会失败。
- 已降级到 `setuptools 69.5.1`，`from rknn.api import RKNN` 和 `RKNN(verbose=False)` 已验证成功。

当前仍未完成：

- 尚未执行 YOLO11 ONNX 到 RKNN 的转换。
- 尚未生成 `yolo11n_rk3576.rknn`。
- 尚未做 `load_rknn` 验证。
- 尚未部署到板端运行 NPU demo。

## 中断与阻塞记录

- 第一次 RKNN 转换子代理只拉取了 `rknn-toolkit2`，未完成 venv、model_zoo、转换。
- 后续主线程尝试安装 RKNN Toolkit2 依赖：
  - WSL 缺 `python3.10-venv`，已通过 apt 安装。
  - pip 到 PyPI 网络不稳，改用清华源。
  - 安装大依赖时耗时较长，曾被用户主动打断。
  - 后续已恢复：清理破损 torch，安装 `torch 2.4.0+cpu`，安装 `rknn-toolkit2 2.3.2`。

## 下一步最短路径

验证 WSL venv：

```bash
cd /mnt/f/WORKSPACE/泰山派/rknn_work
source venv/bin/activate
python - <<'PY'
from importlib.metadata import version
from rknn.api import RKNN
import torch
r = RKNN(verbose=False)
print(version("rknn-toolkit2"))
print(torch.__version__)
PY
```

再按 `rknn_model_zoo/examples/yolo11/README.md` 执行转换：

- 输入：本地 `yolo11n.onnx`
- 输出：`rknn_work/models/yolo11n_rk3576.rknn`
- 平台：`rk3576`

转换命令入口：

```bash
cd /mnt/f/WORKSPACE/泰山派/rknn_work/rknn_model_zoo/examples/yolo11/python
python convert.py <onnx_model> rk3576 fp /mnt/f/WORKSPACE/泰山派/rknn_work/models/yolo11n_rk3576.rknn
```

## 当前工程判断

- 不应继续在板端做模型转换。
- 不应使用不完整的 YOLOv8 ONNX。
- WSL Toolkit2 环境已修好，下一步可以转换 YOLO11。
- 板端 demo 优先走 C/C++ runtime；Python Lite2 只有拿到匹配 wheel 后再考虑。
