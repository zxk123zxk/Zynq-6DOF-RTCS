# 第三方来源与交付说明

本独立 PC 视觉包使用 Ultralytics YOLO11，开发时使用 Ultralytics 8.4.43。官方源码：<https://github.com/ultralytics/ultralytics>；许可证说明：<https://www.ultralytics.com/license>。本包附 GNU AGPL-3.0 文本及可修改的演示源码。请在向第三方分发、比赛交付或未来公开前再次核对实际许可义务；Private 分享不是自动豁免。本文件不对独立 FPGA/机械臂控制工程进行重新许可。

模型先由官方 YOLO11n 权重在 Robocats Robot Arm V3 数据集上训练形成 YOLO A，再以用户确认的正俯拍场景图片微调。Robocats 数据集发布者为 Robocats，来源 <https://universe.roboflow.com/robocats/robot-arm-hxvrd/dataset/3>，原数据集声明 CC BY 4.0；本项目将颜色类别映射为 Cube/Cylinder，并按视频序列重新划分。数据集本体不在本包。后续场景数据来自团队现场视频，不在本包。

不得暗示 Ultralytics、Roboflow 或 Robocats 为本项目背书。若将此视觉代码与控制端紧密耦合，应重新审查许可证与接口边界。
