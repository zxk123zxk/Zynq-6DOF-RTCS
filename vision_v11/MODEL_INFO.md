# 模型信息

V1.1 仅拆分 PC 端推理、采集、结果和接口代码；权重未经重新训练或修改。模型效果和下述历史验证数字与 V1.0 相同，不能把软件重构写成识别率提升。

- 架构：Ultralytics YOLO11n detection，两类：`0=Cube`、`1=Cylinder`。
- 权重：`models/best.pt`，大小 5,457,427 bytes；SHA-256 `C684B1562C95F5DA04153E6C3417BB8F3DC88E1B4974D448510C929C7821A4D7`。
- 来源：团队工程 `experiments/conveyor_topdown_finetune/runs/yolo11n_scene_v4_seed42_run01/weights/best.pt`；以 YOLO A 为初始权重，使用用户确认的正俯拍场景 v4 数据迁移微调。不是旧 YOLO A 权重。
- 推荐推理：完整图像、`imgsz=640`、`conf=0.25`；类别映射在加载时强制校验。

## 已记录的训练与验证

原训练报告记录：训练 73 张，验证 30 张；上限 80 轮，`patience=20`，第 40 轮早停，最佳权重来自第 20 轮。验证集用于早停和选权重，不是独立测试。该集全类 Precision 0.997、Recall 1.000、mAP50 0.995、mAP50–95 0.804；Cube mAP50–95 0.711，Cylinder mAP50–95 0.896。

另有 80 张同源基线图的参考对照：95 个用户审核目标中，86 个类别和框匹配正确，7 个 Cube→Cylinder 错分类，2 个未匹配目标，6 个未匹配预测框。训练、验证和这 80 张图来自同四段视频；**这些数字不是新机位或跨场景准确率**。手接近或遮挡时错误较突出，动态传送带与不同光照、颜色仍需独立验证。

用户报告该权重已用于 USB 摄像头实时识别；这属于先前现场测试结论。交付包制作时的模型加载检查不能代替队友设备上的摄像头和跨场景验收。当前输出只有像素框与中心，不含 yaw、Workspace 毫米坐标或机械臂基坐标。

许可与第三方来源见 [NOTICE.md](NOTICE.md) 和 [LICENSE-AGPL-3.0.txt](LICENSE-AGPL-3.0.txt)。
