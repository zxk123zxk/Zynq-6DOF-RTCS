# 视觉模块许可证范围

## 适用范围

以下视觉交付内容按 GNU Affero General Public License v3.0（`AGPL-3.0-only`）提供：

- `src/vision/`
- `tests/vision/`
- `models/vision/yolo_a_cube_cylinder_best.pt`
- `models/vision/training_config_yolo_a.yaml`
- `docs/vision/`
- `requirements-vision.txt`

完整许可证文本见 `docs/vision/LICENSE-AGPL-3.0.txt`。

该许可声明不自动适用于仓库中独立的 FPGA RTL、PS/PL、机械臂控制、Vivado、Vitis 或 PetaLinux 文件。当前视觉程序作为独立 PC 进程运行，没有导入、链接或嵌入这些控制模块；未来只计划通过明确的外部数据接口交换检测结果。

GNU 官方 FAQ 指出，独立程序通过命令行、管道或 socket 等保持边界、进行有限通信，通常可以作为独立程序或聚合处理；是否构成一个结合作品最终仍取决于实际耦合方式。若未来把视觉代码直接链接进控制程序、共享复杂内部数据结构或形成单一可执行程序，必须重新进行许可证审查。

## 当前 Private 团队共享

Private 仓库不是许可证豁免。当前团队成员取得权重时，也同时取得本目录列出的视觉源码、许可证、配置和修改权。不得只把权重从仓库中抽出后以附加限制的方式另行分发。

## 比赛交付和演示

- 仅在本地运行并通过屏幕演示，不等于向主办方交付程序副本。
- 如果向主办方交付视觉程序或权重副本，应同时提供本视觉模块的对应源码、许可证和署名材料。
- 如果未来通过网络向用户提供修改后的视觉服务，需要按 AGPL 第 13 节向网络用户提供对应源码获取方式。

## 未来公开前

公开 GitHub 前必须重新确认：

1. 本视觉范围内的完整源码、权重、配置和许可证均可访问；
2. Robocats 数据集署名和变更说明完整；
3. 没有密钥、个人路径、隐私视频或无权公开的数据；
4. 视觉与控制模块的实际通信边界仍符合独立程序假设；
5. 若团队希望闭源、商业化或以不兼容 AGPL 的方式紧耦合部署，先取得 Ultralytics Enterprise License。

本文件是工程合规记录，不构成法律意见。
