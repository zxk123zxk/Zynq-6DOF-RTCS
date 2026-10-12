# Cube/Cylinder 视觉模块

本目录说明 `src/vision/` 的运行方式和对外接口。正式类别固定为 `0=cube`、`1=cylinder`。

视觉模块支持图片目录、本地视频和 USB Camera，每帧可返回零到多个目标。当前输出是原始图像像素坐标，不提供 `yaw`、Workspace 毫米坐标或 Robot Base 坐标。

## 环境

已验证的开发环境版本记录在仓库根目录 `requirements-vision.txt`。依赖安装属于环境变更，应先由团队确认；若已有兼容环境，优先直接使用。

```powershell
python -m pip install -r requirements-vision.txt
```

## 模型

YOLO A 权重位于 `models/vision/yolo_a_cube_cylinder_best.pt`。预期大小和 SHA-256 见 `models/vision/SHA256SUMS`。视觉源码、模型和文档按 `LICENSE_SCOPE.md` 中说明的 AGPL-3.0 范围交付；不要把权重脱离对应源码和许可证单独再分发。

## USB Camera

从仓库根目录运行：

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

`--output-dir` 必须是尚不存在的新目录。按 `Q` 或 `Esc` 退出，按 `S` 保存当前带框画面。若无 CUDA GPU，可显式使用 `--device cpu`；不要把开发机 GPU 性能外推到 Zynq PS。

## 本地视频或图片目录

```powershell
python -m src.vision.cube_cylinder_live_test `
  --source video `
  --input C:\path\to\input.mp4 `
  --mode yolo `
  --weights C:\path\to\best.pt `
  --output-dir vision_runs\video_001 `
  --no-display
```

将 `--source video` 改为 `--source images`，并让 `--input` 指向图片目录，即可批量处理图片。

隔离式图片/视频推理入口：

```powershell
python -m src.vision.yolo_inference `
  C:\path\to\images `
  --weights C:\path\to\best.pt `
  --output-visual vision_runs\offline_001\visual `
  --output-records vision_runs\offline_001\detections.jsonl `
  --conf 0.25 --imgsz 640 --device 0
```

## OpenCV 辅助实验

`--mode opencv` 和 `--mode compare` 只适合固定近俯视、稳定光照、独立空背景和受控姿态。必须通过 `--background` 提供不含物体的背景图片；程序不会把当前含物体画面自动当作背景。OpenCV `geometry score` 与 YOLO `confidence` 不是同一概率，不能直接比较。

## 自动测试

```powershell
python -m unittest discover -s tests\vision -p "test_*.py" -v
```

测试使用 fake result 和合成图验证接口、几何基础逻辑、ROI 坐标恢复及空检测语义，不等于最终传送带验收。

## 当前限制

- YOLO A 在公开 Robocats 数据上训练，在跨场景真实图像中存在红色 cube 误分类、低对比 cube 漏检及背景误检风险。
- USB Camera 曾运行，但最终固定俯视传送带场景尚未验收。
- 尚未完成真实 Homography 标定，因此不得输出伪造毫米坐标。
- 当前不输出物体 `yaw`；如控制端需要姿态，必须另行定义、实现和验证。

完整操作见 [视觉模块复现指南](REPRODUCTION_GUIDE_ZH.md)，接口字段见 [interface.md](interface.md)，架构见 [architecture.md](architecture.md)。
