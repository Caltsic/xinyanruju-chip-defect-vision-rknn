# Agent Instructions

## 项目基础说明

当前工作区是嘉立创立创·泰山派3M-RK3576开发项目。项目目标是围绕泰山派3M-RK3576进行全面开发，当前主线是通过 IMX415 摄像头模组进行视觉识别开发。

## 固定上下文

- 本地资料目录：`F:\WORKSPACE\泰山派\立创·泰山派3开发板资料`
- 官方资料网址记录：`F:\WORKSPACE\泰山派\泰山派资料网址.txt`
- 官方资料入口：<https://wiki.lckfb.com/zh-hans/tspi-3-rk3576/download-center.html>
- 泰山派开发板已完成基础系统配置。
- Hermes 已配置完成，可作为辅助开发工具参与板端调试、自动化操作和开发协作。
- 已安装用户级辅助 Skills，位置为 `C:\Users\Kaltsit\.agents\skills`。

## 可用辅助 Skills

- `embedded-systems`：嵌入式系统开发通用辅助。
- `linux-kernel-modules`：Linux 内核模块、驱动和低层接口相关辅助。
- `cross-gcc`：交叉编译和工具链相关辅助。
- `embedded-iot`：嵌入式/IoT 应用开发辅助。
- `wsl-embedded-debugging`：Windows/WSL 连板调试辅助。
- `computer-vision-opencv`：OpenCV 视觉处理辅助。
- `senior-computer-vision`：高级计算机视觉算法辅助。
- `ml-inference-optimization`：机器学习推理优化辅助。

## 工作约定

- 默认使用中文与用户沟通。
- 遇到泰山派硬件、系统镜像、SDK、内核驱动、AI应用、模块移植相关问题时，优先检索本地资料目录，其次使用官方资料网址。
- 当前开发优先级围绕 IMX678/IMX415 摄像头视觉识别链路展开，包括 UVC/ISP 采集链路、图像处理、模型推理与板端验证。
- 当前模型主线是 `chip ROI detect -> 四类缺陷 detect/seg` 二阶段实时检测；缺陷分割首版优先走 YOLOv8-seg + RKNN INT8，并保持既有 detect profile 可回退。
- 需要板端交互、环境检查、自动化执行或重复验证时，优先评估是否可使用 Hermes 辅助。
- 每完成一个相对独立的任务阶段后，应派子代理浏览当前总工程师可见上下文、关键文件变更和命令结果，并将有效信息归档到 `history/`；归档标题宁可信息稍多，也要能让后续通过文件名判断是否相关。
- 每当用户提出一个新问题且已成功解决，应新增或更新一个 `history/NNN-*.md` 文件，记录症状、根因、处理过程、涉及文件/板端路径、验证命令、结果和残留风险；不归档隐藏推理过程，只归档可复用的工程事实。
- 若项目方向、资料位置、板端环境或开发主线发生变化，应同步更新 `README.md` 与本文件。

## Git 约定

- 当前开发分支：`chipCheck`。
- 远端仓库：`git@github.com:Caltsic/-IMX415_Vision.git`。
- 本仓库本地提交身份：
  - `user.name=Caltsic`
  - `user.email=2769003879@qq.com`
- Windows 本机 GitHub SSH key 路径：`C:\Users\Kaltsit\.ssh\id_ed25519_github`。
- 只记录 SSH key 路径，不提交私钥文件。
