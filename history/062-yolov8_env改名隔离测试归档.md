# yolov8_env 改名隔离测试归档

日期：2026-05-12

## 用户目标

用户询问板端旧环境 `/srv/rk3576-storage/yolov8_env` 是否可以删除。为避免直接删除导致检测链路回退困难，本轮先执行改名隔离测试，验证当前 GUI、实时检测和语音占位链路是否仍能正常运行。

## 原环境用途和状态

`/srv/rk3576-storage/yolov8_env` 是早期 YOLOv8 / Python 实验环境，用于板端或近板端的 YOLO、ONNX Runtime、PyTorch/Ultralytics 相关验证，不是当前芯片检测 GUI 的运行环境。

已记录环境特征：

```text
Path: /srv/rk3576-storage/yolov8_env
Size: about 5.3G
Python: 3.11
Typical packages: torch, ultralytics, onnxruntime
```

当前检测 GUI 使用的是 miniforge 环境：

```text
/srv/rk3576-storage/miniforge/bin/python3
Python 3.13.12
```

因此 `yolov8_env` 与当前 GUI 的 Python 运行时已经分离。

## 引用检查结果

本轮隔离前检查结论：

- 板端当前运行进程没有引用 `/srv/rk3576-storage/yolov8_env`。
- 本地仓库没有引用 `yolov8_env`。
- 板端旧快捷命令 `/usr/local/bin/ycuda` 和 `/usr/local/bin/condaactivate` 仍引用原路径。
- 上述旧快捷命令在隔离后会失效，但它们不属于当前 GUI 检测链路，不影响当前芯片检测、GUI 启动和语音占位验证。

## 改名隔离

已执行的隔离路径变更：

```text
/srv/rk3576-storage/yolov8_env
-> /srv/rk3576-storage/yolov8_env.disabled_20260512
```

该操作只是改名保留目录，不释放磁盘空间。

## 验证结果

隔离后验证通过：

- `miniforge` 下 GUI 相关 Python 文件 `compile(...)` 检查通过。
- `python3 -m tools.chip_capture_gui --opencv --backend local --help` 可正常显示，并包含 `--voice-*` 参数。
- 当前实时检测 50 帧通过，输出 `Processed frames: 50`，实时流未中断。
- 语音占位链路通过，状态流为 `voice recording -> voice thinking -> voice done`。

结论：当前板端 GUI、实时检测和语音占位链路不依赖 `/srv/rk3576-storage/yolov8_env`。

## 当前状态

- 旧环境已隔离为 `/srv/rk3576-storage/yolov8_env.disabled_20260512`。
- 当前没有释放磁盘空间。
- 如后续发现旧脚本仍需要该环境，可直接回滚目录名。
- 如果确认不再需要旧 YOLO/ONNX/PyTorch 实验环境，删除 disabled 目录后预计释放约 `5.3G`。

## 回滚命令

如需恢复旧环境路径：

```bash
mv /srv/rk3576-storage/yolov8_env.disabled_20260512 /srv/rk3576-storage/yolov8_env
```

恢复后，旧快捷命令 `/usr/local/bin/ycuda`、`/usr/local/bin/condaactivate` 的原路径引用也会重新有效。

## 删除命令

确认不需要回滚后，可删除隔离目录释放空间：

```bash
rm -rf /srv/rk3576-storage/yolov8_env.disabled_20260512
```

删除后预计释放约 `5.3G`。删除前应再次确认没有新进程或脚本引用该 disabled 目录。
