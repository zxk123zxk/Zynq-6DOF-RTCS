# V1.1 视觉输出接口

公开 API：`vision.Detector(...).detect(frame_bgr) -> FrameResult`；`integration.to_ps_payload(FrameResult) -> dict`。输入是 OpenCV BGR 原始帧；推理层不打开摄像头、不绘图、不发送通信。`Detector` 默认使用模块内 `models/best.pt`，支持 `device=auto/cpu/0`、`imgsz`、`conf`。

`FrameResult` 含 `frame_width`、`frame_height` 和 `detections: tuple[Detection,...]`。每个 `Detection` 含 `class_id`（0=Cube，1=Cylinder）、`class_name`、`confidence`、`bbox_xyxy`、`center_x`、`center_y`。框采用 `[x1,y1,x2,y2]` 浮点像素；中心是框两端平均值。多目标各自成项，无目标为空元组／JSON 空数组。输出不会复用上一帧位置。

仅供后续 PS 适配的数据示例：

```json
{"frame_width":640,"frame_height":480,"detections":[{"class_id":0,"class_name":"Cube","confidence":0.86,"bbox_xyxy":[100.0,70.0,140.0,112.0],"center_x":120.0,"center_y":91.0,"frame_width":640,"frame_height":480}]}
```

无目标：`{"frame_width":640,"frame_height":480,"detections":[]}`。相机 CLI 在此之外保留 V1.0 的 `frame_index` 和 `timestamp_monotonic_s`；后者是软件单调时钟，非硬件曝光时间，也不能直接跨设备同步。

原点为原始图像左上角，x 向右、y 向下，单位像素；bbox 中心不一定是物体几何中心或抓取点。没有实际相机标定、外参及工作平面验证时，不得当作工作台毫米或 Robot Base 坐标。PS 通信格式、时间同步、过期目标处理和多目标选择均需团队确认；本模块不实现串口、TCP、UDP、AXI 或运动控制。
