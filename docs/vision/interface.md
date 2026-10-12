# 视觉到控制端接口说明

权威 Python 类型位于 `src/vision/cube_cylinder_pipeline/detection_types.py`。

## ObjectDetection

| 字段 | 类型 | 语义 |
|---|---|---|
| `class_id` | `int` | `0=cube`，`1=cylinder` |
| `class_name` | `str` | 与 ID 严格对应的 `cube` 或 `cylinder` |
| `confidence` | `float` | `[0,1]`；YOLO 模型分数或 OpenCV 几何分数，两者不可视作同一标定概率 |
| `bbox_xyxy_px` | 4 个 float | 原始完整图像中的 `(x1,y1,x2,y2)`，单位 px |
| `center_px` | 2 个 float | 原始完整图像中的 `(u,v)`，单位 px |
| `timestamp_s` | float/None | 时间含义必须结合帧的 `timestamp_kind` |
| `valid` | bool | 导出的对象必须为 `True`；无效目标通过不输出该对象表达 |

图像坐标系以左上角为原点，`u/x` 向右，`v/y` 向下。ROI 内检测会恢复 ROI 左上角偏移后再输出。

## ObjectDetectionFrame

包含 `frame_index`、`timestamp_s`、`timestamp_kind`、原图宽高和零到多个 `detections`。空检测使用空 tuple/list，不沿用上一帧目标。

时间戳语义：视频使用媒体时间轴；Camera 使用软件单调采集时间而非硬件曝光时间；静态图片没有运动学时间戳。

## 尚未提供

- `yaw` 或完整物体姿态；
- 真实 Workspace `(x_mm,y_mm)`；
- Robot Base 坐标；
- 抓取优先级、轨迹或机械臂动作。

控制团队若需要这些字段，应先共同确定坐标系、单位、失效语义和版本化传输协议，不应从 bbox 或像素中心自行推断物理坐标。

## 历史兼容字段

`yolo_inference.YoloDetection.role` 是旧实验遗留兼容字段。本轮保持不变，但正式 cube/cylinder 流程只依据 `class_id`/`class_name`，不使用 normal/anomaly 语义。
