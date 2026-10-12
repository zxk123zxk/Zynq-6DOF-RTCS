# 视觉模型目录

本目录包含正式 YOLO A 权重。该权重与独立 PC 视觉程序、对应源码、配置和许可证材料一起按 `docs/vision/LICENSE_SCOPE.md` 交付；该范围声明不自动重许可独立的 FPGA/控制程序。

权重位置为 `models/vision/yolo_a_cube_cylinder_best.pt`。使用前执行：

```powershell
Get-FileHash models\vision\yolo_a_cube_cylinder_best.pt -Algorithm SHA256
```

并与 `SHA256SUMS` 比较。模型来源、限制和历史指标见 `docs/vision/model_card_yolo_a.md`。
