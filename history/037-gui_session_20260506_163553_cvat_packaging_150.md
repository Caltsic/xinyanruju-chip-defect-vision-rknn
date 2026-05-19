# GUI Session 20260506 163553 CVAT Packaging 150

## User Request

用户要求：“当前已捕捉到620张，分包，每个包150张”。

## Actual Source Session

实际检查最新采集目录：

```text
chip_seg/captures/gui_session_20260506_163553
```

检查结果显示该目录中的以下内容均为 791 条：

```text
images
labels
images_full
previews
meta
manifest
```

因此本次按当前目录全部 791 张进行分包，而不是只按用户口头提到的 620 张分包。

## Packaging Command

执行命令：

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py package-cvat --input-dir .\chip_seg\captures\gui_session_20260506_163553 --output-dir .\chip_seg\cvat_tasks\gui_session_20260506_163553_150 --chunk-size 150 --zip
```

## Output Packages

输出目录：

```text
chip_seg/cvat_tasks/gui_session_20260506_163553_150
```

生成 6 个 CVAT 分包：

| Package | Images | Annotations | Size |
| --- | ---: | ---: | ---: |
| `part_001.zip` | 150 | 311 | 9.9 MB |
| `part_002.zip` | 150 | 151 | 4.45 MB |
| `part_003.zip` | 150 | 324 | 7.55 MB |
| `part_004.zip` | 150 | 292 | 7.91 MB |
| `part_005.zip` | 150 | 354 | 5.72 MB |
| `part_006.zip` | 55 | 33 | 1.3 MB |

合计：

```text
images=791
annotations=1465
packages=6
```

## Validation

zip 内部结构均已校验通过，均包含：

```text
images/default/*
annotations/instances_default.json
```

这些包可以作为 CVAT COCO 任务包导入，或在创建任务后用于上传 COCO 预标注。
