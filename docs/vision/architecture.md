# 视觉模块架构

## 数据流

```text
USB Camera / local video / image directory
                  |
                  v
      cube_cylinder_live_test.py
                  |
        optional fixed ROI crop
          +-------+-------+
          |               |
          v               v
   YOLO A inference   OpenCV geometry
   yolo_inference.py  controlled scene only
          |               |
          +-------+-------+
                  v
       ObjectDetectionFrame (0..N)
                  |
       restore original-image ROI offset
                  |
          annotated media + JSONL + log
```

`compare` 模式仅在同一帧显示两套算法结果，不进行融合、投票或异常筛选。

## 模块职责

| 模块 | 职责 |
|---|---|
| `cube_cylinder_live_test.py` | Camera/视频/图片调度、ROI、绘制和运行产物保存 |
| `yolo_inference.py` | 加载显式权重，完成图片、目录或视频 YOLO 推理 |
| `detection_types.py` | 多目标像素输出契约及字段不变量 |
| `yolo_baseline_adapter.py` | 将历史 YOLO A JSON 记录适配为统一接口 |
| `opencv_geometry_detector.py` | 受控背景下的实验性轮廓/几何识别 |
| `synthetic_demo.py` | 生成可重复的 OpenCV 合成演示 |

## 工程边界

本模块到原图像素检测结果结束。真实 Homography、Workspace→Robot Base、IK、轨迹、AXI 和 RTL 均不在本次迁移范围。模型检测结果不得直接解释为机械臂可执行抓取点。
