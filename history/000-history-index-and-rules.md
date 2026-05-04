# History Index And Rules

更新时间：2026-04-28

## 目的

本目录是项目级外部记忆库，用于把长对话历史拆成可检索的短文件。后续需要历史信息时，先看本文件和文件名，再只读取相关主题文件。

## 命名规则

- 文件名格式：`NNN-一句话概括该段内容.md`
- `NNN` 使用三位递增编号。
- 文件名必须能直接表达什么时候该读这个文件。
- 每个文件只保存一个主题，避免跨主题堆积。
- 内容只记录可见事实、命令结果、文件改动、工程判断和下一步。
- 不记录隐藏推理过程，不记录未汇报的子代理内部过程。

## 使用规则

1. 需要历史时，先读本文件。
2. 根据文件名和关键词定位主题文件。
3. 只读取当前任务相关文件。
4. 如果新任务产生关键事实，追加或新增历史文件。
5. 如果事实变更，更新相关文件并保留“已过期/已替代”的说明。

## 主题索引

| 文件 | 什么时候读 | 关键词 |
| --- | --- | --- |
| `001-项目基础约定与子代理调度规则.md` | 需要确认协作规则、资料优先级、子代理使用约束时 | 总工程师、中文、High、xhigh、AGENTS、README、Skills |
| `002-板端ADB连接与IMX415采集链路已打通.md` | 需要确认板端连接、系统信息、摄像头节点和正确采集入口时 | ADB、2e2609c37dc21c0a、IMX415、video42、media、v4l2 |
| `003-电脑端OpenCV预览与YOLO_ONNX识别脚本.md` | 需要运行电脑端实时预览或 YOLO ONNX demo 时 | OpenCV、onnxruntime、YOLO11、adb_imx415_yolo_preview.py |
| `004-调焦曝光颜色闪烁与rkaiq_3A诊断.md` | 需要处理画面模糊、曝光/颜色闪烁、3A/IQ 问题时 | focus、rkaiq_3A_server、IQ、exposure、gain、960x540 |
| `005-RKNN工具链与YOLO11迁移当前阻塞.md` | 需要继续 YOLO11 ONNX 转 RKNN、板端 NPU 迁移时 | RKNN、rk3576、rknn-toolkit2、rknn_work、WSL、torch |
| `006-YOLO11_RKNN已在RK3576_NPU单帧识别跑通.md` | 需要确认 RKNN 转换结果、板端 C++ demo 部署目录、NPU 单帧识别命令和输出图时 | YOLO11、RKNN、NPU、rknn_yolo11_demo、camera.jpg、bus.jpg |
| `007-电脑端实时显示RK3576_NPU_YOLO识别画面.md` | 需要运行实时 NPU YOLO 摄像头预览、确认协议和脚本命令时 | rknn_yolo11_camera_stream、adb_imx415_rknn_live_view.py、RYL1、实时显示 |
| `008-芯片缺陷YOLOv8_RKNN云训练包.md` | 需要训练半导体芯片缺陷检测模型、生成 ONNX/RKNN FP/INT8、确认云端包结构和板端适配风险时 | YOLOv8、chip defect、polygon转bbox、INT8、RK3576、cloud_training |
| `009-YOLOv8芯片缺陷RKNN板端实时流已适配.md` | 需要运行芯片缺陷 RKNN 实时检测、确认 YOLOv8 单输出后处理、板端部署文件和电脑端显示命令时 | YOLOv8、chip defect、rknn_chip_defect_camera_stream、1x8x8400、INT8、FP、adb_imx415_rknn_live_view.py |
| `010-实拍无框与IMX415紫屏诊断.md` | 需要确认实拍无框、紫屏/色偏、IMX415 采集异常诊断时 | 实拍、无框、紫屏、IMX415、色偏 |
| `011-新泰山派3M芯片缺陷RKNN部署记录.md` | 需要确认新泰山派3M上的芯片缺陷模型、二进制和 ADB 部署状态时 | 泰山派3M、芯片缺陷、RKNN、部署 |
| `012-WS2812环形补光SPI部署记录.md` | 需要确认 WS2812-8 环形补光接线、SPI1 overlay、控制命令时 | WS2812、SPI1、spidev1.0、19脚、补光 |
| `013-MaixCAM芯片ROI预处理最小闭环.md` | 需要运行 MaixCAM ROI 裁剪、轻量预处理、ONNX 最小闭环，或判断 chip 类训练路线时 | MaixCAM、ROI、预处理、chip、ONNX、light_gamma_clahe |
| `014-硬件视觉链路开发注意事项.md` | 需要快速确认补光色偏、UVC/MJPEG 坏帧、设备占用、ROI/预处理、GUI 关闭等后续开发注意事项时 | 注意事项、WS2812、偏紫、MJPG、坏帧、Device busy、ROI、预处理、GUI |
