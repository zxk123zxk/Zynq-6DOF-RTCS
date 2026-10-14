# 视觉模块复现指南

## 1. 能力和边界

本模块在 PC 上使用 YOLO A 检测真实三维 `cube` 和 `cylinder`，支持同一帧多个目标，输出类别、置信度、原图检测框和像素中心。

**只对两种固定背景负责：黄色桌面、绿色传送带**（2026-10-14 定）。其它背景的画面不作为验收对象。不使用棋盘格，也不单独求相机内参。

当前尚未完成真实平面映射标定，不输出 Workspace 毫米坐标、Robot Base 坐标或 `yaw`，也没有完成机械臂抓取闭环验证。

## 2. 环境准备

建议使用 Python 3.12。从仓库根目录执行：

```powershell
python -m pip install -r requirements-vision.txt
```

已验证依赖为 NumPy 1.26.4、OpenCV 4.10.0.84、Ultralytics 8.4.43。本模块只用 YOLO 检测与 OpenCV 坐标变换，**不需要棋盘格标定板**。

确认环境：

```powershell
python -c "import cv2, numpy, ultralytics; print(cv2.__version__, numpy.__version__, ultralytics.__version__)"
```

检查 PyTorch 是否能使用 NVIDIA GPU：

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

`requirements-vision.txt` 通过 Ultralytics 安装其基础依赖，但不能保证自动匹配每台电脑的 CUDA 驱动。若需要 GPU 且上述结果为 `False`，应按 PyTorch 官方安装页为本机 CUDA 环境选择命令；不要盲目覆盖队友已有 PyTorch。

## 3. 检查模型

正式模型位置：

```text
models/vision/yolo_a_cube_cylinder_best.pt
```

校验：

```powershell
Get-FileHash models\vision\yolo_a_cube_cylinder_best.pt -Algorithm SHA256
```

预期 SHA-256：

```text
2874DF121E6BC780261A27E62C87A14F835E11F60857A2FD4778739398B0BF50
```

## 4. 选择 Camera 编号

通常内置或第一个 USB Camera 是 `0`，第二个可能是 `1`。先尝试 `--camera-index 0`；若提示无法打开，关闭占用 Camera 的会议、浏览器或厂商软件，再依次尝试 1、2。

## 5. 实时识别

GPU：

```powershell
python -m src.vision.cube_cylinder_live_test `
  --source camera `
  --camera-index 0 `
  --mode yolo `
  --weights models\vision\yolo_a_cube_cylinder_best.pt `
  --conf 0.25 `
  --imgsz 640 `
  --device 0 `
  --output-dir vision_runs\camera_001
```

CPU：将 `--device 0` 改为 `--device cpu`。CPU 速度不能代表 Zynq PS 性能。

按 `Q` 或 `Esc` 退出，按 `S` 保存当前画面。每次使用新的 `--output-dir`，程序会拒绝覆盖历史结果。

## 6. 输出解释

- `class_id=0`：cube；`class_id=1`：cylinder。
- `confidence`：YOLO 模型置信度，不等于最终现场正确率。
- `bbox_xyxy_px=(x1,y1,x2,y2)`：原始完整图像像素框。
- `center_px=(u,v)`：原始完整图像像素中心；左上角为原点，u 向右、v 向下。
- 无检测时输出空列表，不沿用上一帧坐标。

Camera/视频运行目录通常包含 `annotated.mp4`、`detections.jsonl`、`run.log` 和 `summary.json`。这些仍是像素结果，不能直接作为机械臂毫米坐标。

## 7. 视频和图片

```powershell
python -m src.vision.cube_cylinder_live_test `
  --source video `
  --input C:\path\to\input.mp4 `
  --mode yolo `
  --weights models\vision\yolo_a_cube_cylinder_best.pt `
  --device 0 `
  --output-dir vision_runs\video_001 `
  --no-display
```

图片目录使用 `--source images` 并让 `--input` 指向目录。

## 7.1 固定背景检出点检

一次运行只拍一种背景（黄色桌面或绿色传送带）。录完后用现场已知放置数量做逐帧一致性点检：

```powershell
python -m src.vision.detection_audit vision_runs\green_belt_001 `
  --expect 3 `
  --frames-from vision_runs\green_belt_001\annotated.mp4 `
  --output audit_runs\green_belt_001
```

它会输出 `audit.json` / `audit.txt` 与可疑帧 PNG。`--expect` 必须是**现场实际放置数量**；
工具**不输出 recall/precision**，漏检与误检由人工在导出的帧上裁定。详见
[视觉模块 README](README.md) 与[当日验收细则](验收细则-20261014.md)。

## 8. 自动测试

```powershell
python -m unittest discover -s tests\vision -p "test_*.py" -v
```

预期为 90 项测试。它们验证接口、空检测、ROI 坐标恢复、合成几何逻辑、点检工具的
逐帧数量判定与抽帧行为，以及平面映射求解与相机控制判定，不代表最终传送带识别性能。

## 9. 常见问题

- `No module named ultralytics`：当前 Python 环境未安装 `requirements-vision.txt` 中依赖。
- `cannot open camera`：Camera 编号错误、设备被占用或 Windows 权限未允许。
- CUDA 错误：先确认 PyTorch/CUDA 环境；临时验证可用 `--device cpu`。
- 找不到权重：确认模型位于 `models/vision/`，或用 `--weights` 显式指定。
- 输出目录已存在：换一个新目录，不要删除或覆盖旧证据。
- 有框但类别错误：保留原视频、JSONL、Camera 参数和现场条件；当前模型已知存在跨场景误检与漏检。
- 广角边缘位置偏差：不做独立内参/畸变标定；像素→毫米只在**工作平面上实测点对求得的映射的有效边界内**成立，越界必须拒绝，不要外推。

## 10. 许可证

视觉模块和模型的许可证范围、第三方署名及比赛交付注意事项见 `LICENSE_SCOPE.md` 和 `NOTICE.md`。不要把权重脱离源码和许可证单独再分发。
