# New Seg Samples 0792 1761 CVAT Packaging 150

## User Request

用户要求：“数据采集完了，新拍的也分包，150张一个包”。

## Source Session

检查发现原采集目录已从之前归档时的 791 张增加到 1761 张：

```text
chip_seg/captures/gui_session_20260506_163553
```

之前已经分包过 `seg_0001` 到 `seg_0791`，因此本次只提取新增样本：

```text
seg_0792 到 seg_1761
```

新增样本数量：

```text
970
```

## New Subset

创建新增样本子集目录：

```text
chip_seg/captures/gui_session_20260506_163553_new_0792_1761
```

子集内容检查结果：

```text
images      970
labels      970
images_full 970
previews    970
meta        970
manifest    970
```

## Packaging Command

执行分包命令：

```powershell
F:\anaconda\python.exe .\tools\seg_cvat_pipeline.py package-cvat --input-dir .\chip_seg\captures\gui_session_20260506_163553_new_0792_1761 --output-dir .\chip_seg\cvat_tasks\gui_session_20260506_163553_new_0792_1761_150 --chunk-size 150 --zip
```

## Output Packages

输出目录：

```text
chip_seg/cvat_tasks/gui_session_20260506_163553_new_0792_1761_150
```

生成 7 个 CVAT 分包：

| Package | Images | Annotations | Size |
| --- | ---: | ---: | ---: |
| `part_001.zip` | 150 | 152 | 3.14 MB |
| `part_002.zip` | 150 | 221 | 5.31 MB |
| `part_003.zip` | 150 | 157 | 4.57 MB |
| `part_004.zip` | 150 | 114 | 9.43 MB |
| `part_005.zip` | 150 | 152 | 6.12 MB |
| `part_006.zip` | 150 | 70 | 1.43 MB |
| `part_007.zip` | 70 | 20 | 0.68 MB |

合计：

```text
images=970
annotations=886
packages=7
```

## Validation

zip 内部结构均已检查，均包含：

```text
images/default/*
annotations/instances_default.json
```

这些包可作为 CVAT COCO 任务包导入，或在创建任务后用于上传 COCO 预标注。
