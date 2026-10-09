# G2 ABI 08 ID 1 实物证据

板端命令：`sudo rtcs-pl-g2 --uio /dev/uio0 move --id 1 --target 2000 --speed-raw 1500 --time-raw 10 --execute`。
板端显示 `abi=0x52540008 physical_tx=ENABLED`、`torque_toggle=0x28:1`、最终 `RTCS_PL_G2_OK id=1 target=2000 position_raw=2010 final_error=10 samples=21 elapsed_ms=1058 timing=WITHIN_2S`。后续独立 READ 显示 `position_raw=2001`、`RTCS_PL_G1_OK id=1 command=READ_POSITION`。完整逐样本内容已按用户消息抄录在 [id1-success-board-log.txt](id1-success-board-log.txt)；本归档保留匹配镜像及 SHA256。

用户观察：ID 1 舵机标称 4000 count 行程、中心约 2000，约 1000 count 对应 90°。这不是机械臂关节的实测安全限位。安装方向、关节零位与安全最小/最大值待实物标定；不得由标称行程推算。
