# 视觉模型目录

本目录放**最终作品实际使用**的权重与哈希。仓库里共有三份 `.pt`，容易混，按此表理解：

| 文件 | 用途 | 载入它的代码 | SHA-256（前 16 位） |
| --- | --- | --- | --- |
| `models/vision/yolo11n_scene_v4_best.pt` | **最终权重**（YOLO11n，正俯拍场景 v4 微调）；与 `vision_v11/…/models/best.pt` **字节相同**，此处为方便索引放一份 | `vision_v11/…/vision/detector.py`（默认 `models/best.pt`） | `c684b1562c95f5da` |
| `models/vision/yolo_a_cube_cylinder_best.pt` | **上一代权重**（YOLO A，保留用于 `src/vision/` 的离线对照与复现） | `src/vision/plane_mapping.py`、`src/vision/cube_cylinder_live_test.py` | 见 `SHA256SUMS` |

两份是不同网络的权重，**不是**同一份文件的两次改名：最终的抓取链路只跑 `yolo11n_scene_v4`，
`yolo_a` 只在 `src/vision/` 的离线脚本里出现，不参与比赛时的抓取。

类别固定为 `0=cube`（异常件，要抓）、`1=cylinder`（合格件，不抓）；输入 640×640，
推理设备 CPU。权重训练规模与已知限制（验证集非独立测试、跨机位未验证等）见
`docs/engineering-notes.md` §6，对外引用时不要省略这几条。

校验哈希：

```powershell
Get-FileHash models\vision\yolo11n_scene_v4_best.pt -Algorithm SHA256
Get-FileHash models\vision\yolo_a_cube_cylinder_best.pt -Algorithm SHA256
```

## 许可

Ultralytics YOLO11 及其微调权重为 **AGPL-3.0**，不等同于本仓库的 MIT；调用 ultralytics 的代码
（`vision_v11/…/vision/`、`src/vision/`）受该范围约束，不自动再许可独立的 FPGA/控制模块。
第三方署名见 `vision_v11/Zynq_RTCS_YOLO_Vision_Module_v1_1/NOTICE.md` 与
`LICENSE-AGPL-3.0.txt`。
