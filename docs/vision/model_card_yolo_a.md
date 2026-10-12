# YOLO A Cube/Cylinder 模型卡

## 状态

YOLO11n 实验 A 是当前视觉基线。权重与独立 PC 视觉程序的完整源码、配置和 AGPL-3.0 文本一起交付。

Ultralytics 官方许可页面明确说明：Ultralytics YOLO 训练或微调得到的模型默认受 AGPL-3.0 约束；使用或分发时，需要将包含它的完整衍生项目按 AGPL-3.0 公开完整对应源码，或者取得 Ultralytics Enterprise License。官方说明：<https://www.ultralytics.com/license>。

当前视觉程序与 FPGA/控制代码没有链接、导入或共享内部结构，只作为 PC 独立进程运行。视觉范围和聚合边界见 `LICENSE_SCOPE.md`。若未来形成单一程序或紧密耦合，必须重新审查，不能继续机械沿用当前范围判断。

## 模型与训练来源

- 架构：Ultralytics YOLO11n detection
- Ultralytics 版本：8.4.43
- 类别：`0=cube`、`1=cylinder`
- 输入尺寸：640
- 训练上限：50 epochs；实际运行 36 epochs；最佳 epoch 21
- batch：8
- 初始化：官方 `yolo11n.pt`
- 主数据来源：Roboflow `robocats/robot-arm-hxvrd/3`
- 数据集审计记录声明：CC BY 4.0
- Ultralytics 本地包元数据声明：AGPL-3.0
- Ultralytics 官方说明：训练/微调模型默认受 AGPL-3.0 约束

Roboflow 数据集页面及下载包均声明 CC BY 4.0，后续分发模型和报告时仍需保留数据集来源与署名。数据集许可不会消除 Ultralytics 模型的 AGPL-3.0 条件。

Private 仓库不是许可证豁免。当前团队共享依赖于接收权重的成员同时获得本视觉模块对应源码、AGPL 文本、配置和修改权。如果未来希望闭源商业使用或不按 AGPL 条件交付视觉程序，应取得覆盖实际用途的 Ultralytics Enterprise License。本记录不构成法律意见。

## 权重完整性

- 预期文件名：`yolo_a_cube_cylinder_best.pt`
- 大小：5,496,580 bytes
- SHA-256：`2874DF121E6BC780261A27E62C87A14F835E11F60857A2FD4778739398B0BF50`

## 已有评估摘要

这些结果来自公开 Robocats 的既有分组数据，不代表最终固定传送带性能。

| split/class | Precision | Recall | AP50 | AP50-95 |
|---|---:|---:|---:|---:|
| validation cube | 0.759 | 0.749 | 0.812 | 0.571 |
| validation cylinder | 0.775 | 0.824 | 0.826 | 0.649 |
| test cube | 0.857 | 0.754 | 0.914 | 0.696 |
| test cylinder | 0.560 | 0.915 | 0.696 | 0.514 |

封存 test 中存在已确认漏标帧，因此尤其是 Precision 会受评估标签缺失影响。跨场景诊断还发现红色 cube→cylinder、低对比白色 cube 漏检，以及桌面、线缆或圆形背景误检。当前模型只能作为基线，不能宣称已通过最终场景验收。
