# 第三方来源与署名

## Ultralytics YOLO

- 软件/模型体系：Ultralytics YOLO11
- 使用版本：Ultralytics 8.4.43
- 官方源码：<https://github.com/ultralytics/ultralytics>
- 官方许可说明：<https://www.ultralytics.com/license>
- 本视觉交付采用：AGPL-3.0-only

YOLO A 由官方 `yolo11n.pt` 初始化并使用 Ultralytics 训练流程微调。完整 AGPL-3.0 文本见 `LICENSE-AGPL-3.0.txt`。

## Robocats Robot Arm Dataset

- 发布者：Robocats
- 项目：Robot Arm
- 工作区/项目/版本：`robocats/robot-arm-hxvrd/3`
- 来源：<https://universe.roboflow.com/robocats/robot-arm-hxvrd/dataset/3>
- 数据集声明许可证：CC BY 4.0
- CC BY 4.0：<https://creativecommons.org/licenses/by/4.0/>

原数据包含按颜色划分的八类 cube/cylinder。本项目将不同颜色类别重新映射为 `0=cube`、`1=cylinder`，并按完整视频序列重新划分训练、验证和测试，以降低相邻帧泄漏。数据集本体未加入团队仓库。

不得暗示 Ultralytics、Roboflow 或 Robocats 为本竞赛项目背书。
