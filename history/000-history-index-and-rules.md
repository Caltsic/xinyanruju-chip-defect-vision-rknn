# History Index And Rules

更新时间：2026-05-12

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
| `015-chip类定位数据集目录规划.md` | 需要确认 chip 类目录、样本量、标注规则、训练阶段和 generated/captures/review 放置约定时 | chip_roi、chip 类、数据集、伪标签、负样本、标注规则 |
| `016-chip类伪标签生成与复核GUI.md` | 需要运行 chip 伪标签生成、查看 manifest 输出、启动复核 GUI 或确认当前生成结果时 | build_chip_roi_dataset、review_chip_roi_labels、manifest、A/D/W/S、Delete |
| `017-chip_capture_gui一体化实拍标注.md` | 需要用 GUI 实拍、自动顺序命名、自动生成 chip 框、Accept/Negative 写标签时 | chip_capture_gui、Capture ROI、自动编号、绿色主题、manifest |
| `018-chip_roi_yolov8_cloud_training.md` | 需要确认 chip ROI 一类 YOLOv8 训练包、云端训练命令、INT8 RKNN 转换顺序和最终产物时 | chip_roi、YOLOv8、cloud_training、RTX5090、INT8、RKNN、rk3576 |
| `019-chip_roi_runtime_alignment_and_capture_defaults.md` | 需要确认 chip ROI 运行接入、芯片居中辅助、GUI 默认拍摄参数和 denoise 卡顿处理时 | chip_roi、chip-roi-maixcam、ImageAdjustSettings、Denoise、Light50、两阶段 |
| `020-chip_roi_realtime_deployment_and_next_stage.md` | 需要确认 chip ROI 实时部署状态、当前可用命令、FP/INT8 差异和下一阶段两阶段实时融合入口时 | chip_roi、实时部署、chip-roi-maixcam、FP RKNN、INT8、two-stage、MaixCAM |
| `021-int8_first_runtime_plan_correction.md` | 需要确认为什么后续优先 INT8、FP 的定位、二阶段融合前置条件和修正规划时 | INT8优先、RK3576、FP基线、chip ROI、二阶段 |
| `022-int8_split_output_and_two_stage_runtime.md` | 需要确认 INT8 无框根因、split-output RKNN 产物、二阶段板端实时命令和验证截图时 | INT8、split-output、chip-two-stage-maixcam、yolov8_scores、二阶段、MaixCAM |
| `023-two_stage_temporal_stabilization.md` | 需要确认二阶段实时框跳动、chip ROI 平滑、显示端平滑/过滤和推荐观察命令时 | 二阶段、抖动、平滑、display-max-defects、roi-smooth-alpha、defect_conf |
| `024-two_stage_fps_cadence_optimization.md` | 需要确认二阶段 FPS 优化、chip/defect 推理间隔、默认与速度优先命令时 | FPS、chip-interval、defect-interval、二阶段、节奏优化 |
| `025-two_stage_board_defect_temporal_filter.md` | 需要确认板端 defect 时序滤波、连续命中、消失保持和跨类别稳定匹配参数时 | defect-confirm、defect-hold、defect-match、类别投票、板端滤波 |
| `026-chip_capture_gui_two_stage_live_tuning.md` | 需要确认 GUI 内二阶段实时检测、调参采集、引脚/丝印/破损预设和验证结果时 | chip_capture_gui、Live Detect、Save adjusted、Pins、Text、Damage |
| `027-board_input_adjust_matches_display.md` | 需要确认 MaixCAM 二阶段实时的 NPU 输入是否与显示画面一致、板端 input-adjust 参数、性能代价和关闭锐化方式时 | input-adjust、RGB888、NPU输入、显示一致、Sharpness、FPS |
| `028-two_stage_threshold_display_tuning.md` | 需要确认二阶段 defect 置信度阈值、显示框数量限制来源、当前推荐显示命令时 | defect-conf、defect-confirm、display-max-defects、阈值扫描、top-k |
| `029-chip_capture_gui_dual_backend_opencv_board_ui.md` | 需要确认 chip_capture_gui 的 ADB/本地双后端、板端 HDMI OpenCV 界面、启动命令和快捷键时 | chip_capture_gui、OpenCV、backend、local、HDMI、PyQt fallback、/userdata/chipcheck_vision |
| `030-imx678_usb_uvc_realtime_profile.md` | 需要确认 IMX678 USB UVC 识别结果、`/dev/video73` 格式、正式 imx678 profile 和烟测截图时 | IMX678、UVC、DECXIN、1bcf:2cd1、chip-two-stage-imx678、/dev/video73 |

## Recent Additions

| File | When To Read | Keywords |
| --- | --- | --- |
| `031-yolov8_seg_board_smoke.md` | Confirm YOLOv8-Seg board deployment, two-stage seg smoke results, contour screenshots, or the rebuilt stream binary state. | YOLOv8-Seg, RKNN, chip-two-stage-seg-imx678, contour, mask_coeffs, protos |
| `032-seg_mask_temporal_filter_and_contour_stabilization.md` | Find the seg mask stability fix, contour false-fill repair, PC mask-fill auto behavior, or seg no-hold display defaults. | seg mask, temporal filter, contour, closed loop, false fill, mask-fill auto, no-hold |
| `033-seg_mask_only_display_and_cvat_capture_pipeline.md` | Find the mask-only display change, overlay-mode behavior, CVAT capture/package/merge pipeline, and first real-shot segmentation annotation plan. | overlay-mode, mask-contour, mask-only, CVAT, seg_cvat_pipeline, capture, package-cvat, merge-coco, real-shot annotation |
| `034-seg_cvat_usage_review_and_pipeline_fixes.md` | Find the concrete CVAT usage flow, the review findings, and the fixes for CVAT zip layout, RLE mask merge, capture lighting, stop conditions, manifests, ROI clipping, and no-chip fallback. | CVAT usage, COCO zip, images/default, RLE, mask decode, merge_report, WS2812, timeout, max-frames, manifest, ROI clip, keep-no-chip |
| `035-seg_mask_labels_restored_without_boxes.md` | Find the fix for restoring segmentation mask class labels while still hiding defect rectangle boxes in mask-contour mode. | seg labels, mask-contour, no boxes, overlay_draws_labels, overlay_draws_boxes, scratch label, live view |
| `036-gui_manual_seg_sample_and_local_cvat_start.md` | Find the manual GUI segmentation sample saving workflow and local CVAT startup result. | GUI, Save Seg Sample, SegSampleWriter, manual sample change, CVAT local, Docker Desktop, v2.64.0, localhost:8080 |
| `037-gui_session_20260506_163553_cvat_packaging_150.md` | Find the CVAT packaging result for GUI session 20260506_163553 with 150 images per package. | gui_session_20260506_163553, package-cvat, chunk-size 150, CVAT, COCO, part_001, part_006, 791 images |
| `038-new_seg_samples_0792_1761_cvat_packaging_150.md` | Find the CVAT packaging result for newly captured samples seg_0792 through seg_1761, packaged 150 images per zip. | gui_session_20260506_163553, new samples, seg_0792, seg_1761, package-cvat, chunk-size 150, CVAT, COCO, part_001, part_007, 970 images |
| `039-人工CVAT分割训练与未标定自动预标注.md` | Find the manual CVAT segmentation training run, cloud YOLOv8s-Seg result, and auto-prelabel CVAT packages for the 1025 unlabeled images. | CVAT, YOLOv8s-Seg, manual_20260506, chipCheck_1, chipCheck_12, auto-prelabel, part_001, part_007, 1025 images |
| `040-阿里云CVAT服务器资源评估.md` | Find the Alibaba Cloud CVAT deployment feasibility check, server resource limits, DNS mismatch, and recommended CVAT host sizing/subdomain. | Aliyun, CVAT, aiourstory.cn, cvat.aiourstory.cn, 8.137.71.118, 2C1.6G, no swap, data disk, nginx |
| `041-hdmi_lcd_800x600_fallback_confirmed.md` | Find the TaishanPi HDMI LCD fallback mode confirmation and persistent 800x600 RGB force_dvi configuration. | HDMI, LCD, TaishanPi, 800x600, force_dvi, RGB, xrandr |
| `042-腾讯云CVAT服务器资源评估.md` | Find the Tencent Cloud CVAT deployment feasibility check, disk/memory limits, COS storage warning, DNS mismatch, and recommended CBS/data-disk plan. | Tencent Cloud, CVAT, 62.234.222.63, cvat.aiourstory.cn, COS, CBS, Docker Compose, nginx, /data |
| `043-完整人工分割训练与RKNN_INT8转换.md` | Find the full manual CVAT segmentation training run, complete task15-21 merge, RTX5090 training result, and RKNN INT8 conversion artifacts. | CVAT, full manual, task15-task21, YOLOv8s-Seg, RTX5090, RKNN, INT8, split_int8, rk3576 |
| `044-完整人工分割模型板端部署_GUI兼容.md` | Find the full manual YOLOv8s-Seg INT8 RKNN board deployment, GUI-compatible model path, board backup paths, smoke-test command, FPS, and live-view command. | GUI, board deployment, YOLOv8s-Seg, INT8, RKNN, chip-two-stage-seg-imx678, chipcheck_yolov8_seg_split_int8.rknn, smoke test |
| `045-taishanpi_qt_board_gui.md` | Find the board-local PyQt GUI launcher, 800x600 HDMI layout, local backend command, deployed desktop paths, and Qt smoke verification. | TaishanPi, Qt, PyQt5, board GUI, local backend, chipcheck-qt-gui, 800x600, HDMI |
| `046-chip_OBB旋转ROI全链路实现.md` | Find the chip OBB dataset/training/RKNN scripts, board C++ OBB postprocess and rotated crop path, PC/GUI OBB profile, OBB crop sample saving, verification results, and remaining board smoke work. | OBB, rotated ROI, YOLOv8-OBB, RKNN, chip-two-stage-obb-seg-imx678, DETECTION_OBB_FLAG, crop_mode obb, affine crop |
| `047-OBB实时窗口0帧与板端二进制部署.md` | Find the OBB real-time profile 0-frame diagnosis, stale board binary fix, rk3576 CMake rebuild/deployment, runtime preflight check, stable HBB+seg regression result, and remaining missing OBB RKNN model blocker. | OBB, 0 frames, --chip-model-kind, board binary, rk3576, rknn_chip_two_stage_maixcam_stream, chip_roi_yolov8_obb_split_int8.rknn, Missing board runtime file(s), chip-two-stage-obb-seg-imx678 |
| `048-chip_OBB人工标注CVAT分包准备.md` | Find the corrected chip OBB manual CVAT preparation scope, full-frame source collection, SHA1 dedupe, package output, validation counts, and CVAT annotation usage rules. | OBB, CVAT, manual annotation, chip, prepare_chip_obb_cvat_tasks.py, chip_obb_cvat_preparation_20260509.md, cvat_obb_tasks_20260509, SHA1, polygon, YOLO OBB |
| `049-chip_OBB_CVAT项目级导出检查.md` | Find the CVAT project-level COCO export check, image count mismatch against local OBB task packages, changed annotation counts, non-4-point polygons, and reuse decision for YOLO OBB conversion. | OBB, CVAT, project export, COCO 1.0, project_3_dataset_2026_05_09_10_15_32_coco, missing_images, 5 points, minAreaRect, YOLO OBB |
| `050-chip_OBB人工标注训练RKNN部署与通道顺序修正.md` | Find the CVAT project-export OBB training result, YOLOv8n-OBB metrics, dependency fixes, RKNN artifacts, channel-order bug fix, board deployment paths, and live verification result. | OBB, CVAT, YOLOv8n-OBB, RTX5090, RKNN, INT8, onnxscript, onnx_ir, onnx.mapping, channel order, xywh score angle, split ONNX, chip-two-stage-obb-seg-imx678 |
| `051-chip_OBB快速响应alpha_1参数校验修正.md` | Find the PC and board-side fix that allows smoothing alpha 1.0 for fast OBB response while keeping strict threshold parameters unchanged. | OBB, fast response, alpha=1.0, roi-smooth-alpha, defect-smooth-alpha, defect-class-decay, smoothing_alpha_float, parse_alpha_option, std::isfinite |
| `052-GUI_OBB折中参数四类缺陷标定采集.md` | Find the GUI OBB calibration capture preset, Qt/OpenCV output-dir and prefix support, SegSampleWriter outputs, recommended capture commands, and verification details for four defect classes. | GUI, OBB, calibration preset, chip-two-stage-obb-seg-imx678, chip-conf 0.45, chip-interval 1, roi-smooth-alpha 0.55, roi-hold 1, SegSampleWriter, ZF-scratch, scratch, broken, pinbreak |
| `053-chip_OBB重训确认与GUI默认路径及几何精修.md` | Find the verification that chip OBB was retrained and deployed, the GUI default profile/HBB fallback issue, board helper sync issue, GUI-side OBB geometry refinement, verification results, and remaining C++ crop follow-up. | OBB, retrain verification, chip-two-stage-obb-seg-imx678, CameraSettings, CHIP_ROI_OBB_REMOTE_MODEL, obb_refine, minAreaRect, refined angle, SegSampleWriter, board sync |

| `054-OBB角度精修采集593张分包CVAT_150.md` | Find the CVAT packaging record for `obb_angle_refine_20260509`, including source structure, counts, per-part annotations, and zip outputs for 150-image chunks. | OBB, angle refine, CVAT, package-cvat, obb_angle_refine_20260509, chunk-size 150, part_001, part_004, 593 images |

| `055-project4角度补强分割微调训练INT8板端部署.md` | Find the project4 angle-supplement segmentation fine-tune, RTX5090 training metrics, ONNX/split/INT8 RKNN conversion, board deployment hashes, and smoke-test limitation. | project4, angle supplement, YOLOv8s-Seg, INT8, RKNN, chipcheck_yolov8s_seg_full_manual_plus_project4_20260510_ft, a3de2a, board deployment |
| `056-实时命令默认chip与defect模型版本核对.md` | Find the verified default models used by the realtime OBB+seg command, including chip OBB and latest project4 defect segmentation SHA256. | realtime command, default model, chip ROI OBB, defect seg, SHA256, chip-two-stage-obb-seg-imx678 |
| `057-OBB实时窗口与GUI链路不一致导致chip框不跟芯片.md` | Find the root cause and fix for realtime chip OBB not following the chip: GUI minAreaRect refinement vs plain live-view path, OBB presets, and validation snapshot. | OBB, GUI mismatch, minAreaRect, chip frame, live-view, obb_refine, roi_smooth_alpha |
| `058-GUI缺陷模型显式切换最新版并新增原图显示.md` | Find the GUI change that explicitly binds latest project4 defect segmentation model and adds original-frame display in Qt/OpenCV/board GUI. | GUI, latest defect model, original frame, Show original frame, raw, OpenCV R, project4 |
| `059-工作区收尾清理与派生缓存移除.md` | Find the workspace cleanup record, removed temporary packages/caches, preserved artifacts, .gitignore generated-output rules, and verification results. | cleanup, tmp, cache, tar, .gitignore, generated outputs, workspace |
| `060-RK3576本地LLM能力评估.md` | Find the measured board memory/storage/FPS state and the practical local LLM size recommendation for running alongside or instead of the current vision stack. | RK3576, TaishanPi 3M, local LLM, llama.cpp, RKLLM, 0.5B, 1.5B, 3B, 7B, memory, NPU contention |

| `061-MiniMindO_CPU语音助手骨架部署.md` | Find the CPU-only MiniMind-O voice assistant skeleton deployment, non-interference boundary, audio arecord/aplay results, GUI integration, board paths, verification results, and remaining real-model risks. | MiniMind-O, CPU-only, voice assistant, arecord, aplay, GUI, OpenCV, PyQt, --voice-command, /userdata/chipcheck_vision/voice_assistant, non-interference |
| `062-yolov8_env改名隔离测试归档.md` | Find the rename-isolation record for the old board `/srv/rk3576-storage/yolov8_env` environment, including original purpose, reference checks, validation results, rollback command, and delete command. | yolov8_env, disabled_20260512, miniforge, Python 3.13, Python 3.11, torch, ultralytics, onnxruntime, rollback, delete, 5.3G |
| `063-minimind-o-eaget-deployment-smoke.md` | Find the MiniMind-O real deployment smoke on EAGET, deleted old yolov8_env, board storage layout, dependencies/weights, GUI runner integration, smoke timing, and CPU-only risks. | MiniMind-O, EAGET, /mnt/eaget, minimind_o_env, PYTORCH_JIT=0, torchaudio 2.6.0, SenseVoiceSmall, mimi, sft_omni_768, --voice-command, chipcheck-hdmi-gui, CPU slow |
| `064-voice_stream_overlay_ws2812_cascade.md` | Find the MiniMind-O green streaming reply overlay and WS2812 8/12/24 cascaded ring segmented brightness implementation, validation results, and usage risks. | MiniMind-O, stream-text, voice overlay, green text, TTL, Pillow, wqy-zenhei, WS2812, 44 lights, segment-counts, segment-brightness, 8,12,24, High Light, Low Light, chipcheck-hdmi-gui |
| `065-board_speaker_and_voice_text_visibility_fix.md` | Find the TaishanPi local speaker playback fix, PyQt voice text overlay fix, default MiniMind-O command fallback, and GUI restart state. | MiniMind-O, TaishanPi, speaker, rockchip-es8388, plughw:0,0, PyQt, voiceReplyOverlay, default_minimind_command, board-ui, OpenCV overlay |
| `066-qt_only_gui_minimind_failure_fix.md` | Find the Qt-only GUI transition record, OpenCV GUI removal, MiniMind failure overlay handling, 360s voice timeout, local verification, and ADB disconnected blocker. | Qt-only, OpenCV GUI removed, MiniMind failed overlay, voice timeout, ADB disconnected, board-ui, /usr/bin/python3, plughw:0,0 |
| `067-minimind_qt_illegal_instruction_eaget_mount_fix.md` | Find the board deployment after ADB recovery, MiniMind-O Illegal instruction root cause, torch.jit.script passthrough fix, EAGET automount launcher change, and final Qt/audio verification. | MiniMind-O, Qt, Illegal instruction, funasr, torch.jit.script, EAGET automount, audio_decoded, plughw:0,0 |
| `068-ws2812_256_backlight_gpio.md` | Find the independent WS2812-256 backlight GUI/runtime integration, default GPIO3_A2 pin 38 wiring, deploy script changes, verification commands, and remaining timing/power risks. | WS2812-256, backlight, GPIO3_A2, pin38, gpiochip3 line 2, Back Light, ws2812_gpio_mmio, GUI, runtime setup |
| `069-pc_gui_start_lights_no_frame_tmp_permission.md` | Find the PC Qt GUI Start issue where lights turned on but no video frame appeared, caused by `/tmp` protected_regular blocking shell redirection and polluting the binary stream, plus the runtime path fix and verification. | PC GUI, Qt, no frame, bad magic, RYL1, sh:, /tmp, protected_regular, chip_input_adjust.conf, rknn_yolo11_camera_stream.log |
| `070-qt_light_dock_rgb_presets.md` | Find the Qt light dock UI change that moved lighting controls to a translucent bottom preview drawer with per-light RGB, brightness, default RGB, saved presets, and real-time apply behavior. | Qt, light dock, RGB, presets, WS2812, backlight, segment-rgb, real-time |
| `071-qt_photo_pair_original_marked_save.md` | Find the Qt GUI Save Photo Pair function that saves paired original and marked full-frame snapshots plus a manifest and `P` shortcut. | Qt, photo, snapshot, original, marked, manifest, Save Photo Pair, P shortcut |
| `072-software_copyright_repo_publication_record.md` | Find the software copyright filing repository rename, public GitHub publication status, recommended software name, development completion date, and first publication date/method. | software copyright, soft著, GitHub, public, xinyanruju, chipCheck, publication, 2026-04-14, 2026-04-28 |

## Persistent Archiving Rule

- After each meaningful task phase, ask a sub-agent to review the chief engineer's visible current context, key file changes, commands, outcomes, and risks, then archive reusable facts into `history/`.
- When a new user-reported problem is solved, create or update a clearly named `history/NNN-*.md` entry with symptoms, root cause, fix, touched files/board paths, verification command, result, and residual risks.
- Archive engineering facts and decisions only; do not archive hidden reasoning.
