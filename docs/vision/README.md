# Cube/Cylinder 视觉模块

> 下表是视觉子系统的建议里程碑，不代表 Zynq-6DOF-RTCS 整体项目版本。

## 阶段进度

| 版本 | 阶段目标 | 当前状态 | 主要交付 | 后续依赖 |
|---|---|---|---|---|
| [V1.0](milestones/V1.0_视觉识别阶段总结.md) | 方块/圆柱体实时视觉识别及工程交付 | **阶段性交付完成** | YOLO A、USB Camera/视频/图片入口、多目标像素结果、16 项自动测试和复现文档 | 最终固定相机与传送带现场验收 |
| [V1.1](milestones/V1.1_场景锁定与工作空间定位计划.md) | 固定摄像头场景锁定与 Workspace 定位 | **待开发** | 计划交付**场景与相机工况锁定、平面实测点对与映射、独立点误差验证和有效性检查**（不做棋盘格与内参标定） | 最终摄像头安装、工作平面和实测点 |
| [V1.2](milestones/V1.2_控制端接口联调计划.md) | 视觉与 Zynq 控制端接口联调 | **待开发** | 计划交付版本化消息、时效/失效语义、通信与故障测试 | 双方确认协议、坐标责任和超时策略 |
| [V2.0](milestones/V2.0_视觉抓取闭环计划.md) | 视觉引导机械臂抓取闭环 | **待开发** | 计划交付真实系统闭环、安全失败处理与验收证据 | V1.1、V1.2、控制端运动与安全能力 |

V1.0 的“阶段性交付完成”仅表示检测模块已形成可复现工程交付，不表示真实标定、控制联调或视觉抓取系统全部验收完成。

本目录说明 `src/vision/` 的运行方式和对外接口。正式类别固定为 `0=cube`、`1=cylinder`。

视觉模块支持图片目录、本地视频和 USB Camera，每帧可返回零到多个目标。当前输出是原始图像像素坐标，不提供 `yaw`、Workspace 毫米坐标或 Robot Base 坐标。

## 环境

已验证的开发环境版本记录在仓库根目录 `requirements-vision.txt`。队友电脑若已有兼容环境可直接使用；缺少依赖时在运行视觉程序的 Python 环境执行：

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

## 场景约束（2026-10-14 定，不再变更）

抓取背景**只有两种工况**：**黄色桌面** 与 **绿色传送带**。本模块只对这两种背景保证检出；不为其它背景调参，换背景后的画面不作为验收对象。

**不使用棋盘格。** 2026-10-13 现场实测：棋盘格角点检出受遮挡、反光与广角畸变影响，未能稳定检出，且棋盘画面出现大量误检；同期同一相机在**绿色传送带**上对黑方块检出正常。因此不打印标定板、不跑角点检出、不单独求相机内参——原 `scripts/vision/check_chessboard.py` 已删除。像素→工作坐标改由[平面映射](../4.G4-static-vision-grasp.md)在工作平面上实测点对得到。

## 场景锁定与平面映射工具

- **`src/vision/camera_locking.py`**：枚举相机、尝试锁定曝光/白平衡/增益（**如实打印读回值**——
  写成功不等于锁住）、拍摄纯背景/含工件实拍图、把新画面与基线比对。
  用法见[命令执行清单 §3](命令执行清单-20261014.md)。
- **`src/vision/plane_mapping.py`**：`collect`（实拍图跑现有 YOLO 出点对）→ `calibrate`
  （独立验证点报误差，凸包外拒绝）→ `map`（运行时像素→毫米）。写法与现场步骤见
  [平面映射标定操作指南](平面映射标定操作指南.md)。

两个工具都**不产生未经标定的毫米坐标**，也不驱动机械臂。

**待决策中的设备/方案问题**（白方块、ROI 是否引入脆弱性、要不要换相机、要不要改用 opencv 模式）
统一记在[相机与场景选型决策](相机与场景选型决策-20261014.md)，避免反复推翻。

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

## 固定背景检出点检（`detection_audit`）

**一次运行只拍一种背景**（黄色桌面**或**绿色传送带），否则统计会把两个场景混在一起，数字没有意义。
录完之后，用现场**已知的放置数量**做逐帧数量一致性点检：

```powershell
python -m src.vision.detection_audit vision_runs\green_belt_001 `
  --expect 3 `
  --conf-min 0.5 `
  --frames-from vision_runs\green_belt_001\annotated.mp4 `
  --output audit_runs\green_belt_001
```

- `--expect` 是**现场实际放置的目标数量**（人工确认），不是模型输出。
- 逐帧检出数等于它记合规；少于它记 `fewer_than_expected`（漏检嫌疑），多于它记 `more_than_expected`（误检嫌疑）。
- 输出 `audit.json`（完整可疑帧清单）、`audit.txt`（人读版），并把可疑帧导出为 PNG 供人工裁定。
- **不输出 recall/precision**：真值必须人工逐帧裁定，程序不替人下结论；该字段固定为
  `not_computed_requires_manual_adjudication_on_suspect_frames`。
- Camera 运行没有逐帧原图，`--frames-from` 可指向该 run 的 `annotated.mp4`：抽出的帧已带框，
  便于区分"真漏检"与"真误检"。
- 输出目录必须不存在，避免覆盖历史证据。
- 两种历史 JSONL 结构都支持：`yolo_inference` 的扁平结构与 `cube_cylinder_live_test` 的
  `algorithms.yolo_a` 嵌套结构。

## 自动测试

```powershell
python -m unittest discover -s tests\vision -p "test_*.py" -v
```

预期为 90 项测试。它们验证接口、空检测、ROI 坐标恢复、合成几何逻辑，以及点检工具的
逐帧数量判定与抽帧行为，不代表最终传送带识别性能。

## 当前限制

- YOLO A 在公开 Robocats 数据上训练，在跨场景真实图像中存在红色 cube 误分类、低对比 cube 漏检及背景误检风险。**本模块只对黄色桌面与绿色传送带两种固定背景保证检出**（见上节场景约束）。
- USB Camera 曾运行，但最终固定俯视传送带场景尚未验收。
- 尚未完成**平面映射**标定，因此不得输出伪造毫米坐标。
- 当前不输出物体 `yaw`；如控制端需要姿态，必须另行定义、实现和验证。

完整操作见 [视觉模块复现指南](REPRODUCTION_GUIDE_ZH.md)，接口字段见 [interface.md](interface.md)，架构见 [architecture.md](architecture.md)。
