# G3 静态抓取 5 连跑原始记录（2026-10-22 21:52）

**口径声明（先读这条，否则数字会被误用）**：本轮用固定参数 `--grasp-xy 340,108.7`
驱动，**视觉未参与**。它验证的是"五轴示教表 + 七步关节路径"的开环稳定性，
**不是**"视觉识别→抓取"的端到端成功率。端到端（相机出点→喂 `--grasp-xy`）至今
只有 2026-10-21 的 1 个样本（x=318.6, y=74.8）。

## 命令

```sh
cd ~/rtcs && sudo python3 scripts/g3_station_runner.py config/g3_station_plan.json \
  --uio /dev/uio0 --grasp-xy 340,108.7 \
  --teaching-table config/grasp_teaching_table.json --loop 5
```

映射来源（板端日志原样）：

```
G3_INFO grasp_xyz=[1984, 1968, 2292, 2954, 1893] lift_xyz=[2045, 1240, 2534]
        | lift source: plan default verified pose (not derived)
        | interp: linear (3 points, lane=yes, axes=5)
G3_INFO skip standby: first motion goes straight from the reset/exit pose to the grasp pose
```

即：ID1-5 由三点五轴表沿 x 线性插值得到，ID6 取计划开度 2619，`lift` 保持固定标准抬升位。

## 结果

| 轮次 | 结果 | 夹爪接触位 | 节拍 (ms) |
| --- | --- | --- | --- |
| 1 | success=1 | 2399 | 6676 |
| 2 | success=1 | 2390 | 6568 |
| 3 | success=1 | 2398 | 6619 |
| 4 | success=1 | 2390 | 6619 |
| 5 | success=1 | 2399 | 6568 |

- `G3_RUN_SUMMARY cycles=5 failures=0 aborted=0`，成功率 **5/5**。
- 夹爪闭合目标 2300，5 轮接触位 2390–2399（未到底 = 夹住），**5/5 未掉件**；
  离散度 9 count（≈0.8 mm），一致性好。
- 放置张开实测 2747–2748（目标 2760）。
- 单轮节拍 6.57–6.68 s，均值 **6.61 s**；较 10-21 的 7.24 s 缩短 0.63 s，
  与"跳过 standby 省一趟 985 ms"的预期一致（`standby result=SKIPPED`）。
- 步耗时稳定：approach 934 / grasp 167 / gripper 1214-1220 / lift 832-883 /
  place 985 / retreat 883-934 / exit 883-884 ms。

## 已知限制（不得在文档中省略）

1. **开环**：xy 为人工给定，非相机输出。
2. **单点**：仅 x=340、y=108.7；示教区间 302.4–354.9（53 mm / 490 mm），区间外会被
   夹到端点姿态（不外推）。
3. **单车道**：只有 y=108.7 一条；物块换 y 后无表可查。
4. ID2 在 1965–1971，低于 2039 死区下界；本轮 5/5 未出现静默停顿，但属已知风险。

## 坐标系变更（2026-10-23 补注）

本文所有 (x, y) 属**旧标定帧**（手工点四角；`calibration.json` 已于 10-23 被
`belt_calibration_dynamic.py` 的自动标定覆盖）。坐标系重建后，同一批物理点的标签变为
**345.0 / 370.0 / 395.0（y=36.0）**，`config/grasp_teaching_table.json` 已按新帧更新。

**本文坐标不得与新表混用。** `targets`（关节角）未变，仍然有效——关节姿态与相机无关。

