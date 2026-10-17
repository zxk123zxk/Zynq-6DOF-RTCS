# 给板端 PetaLinux rootfs 加 python3 —— 2026-10-16
#
# 缘由：G3 状态机编排层（scripts/g3_station_runner.py）与视觉侧脚本是 Python；
# 精简 rootfs 默认不带 python3，板端跑 `python3` 报 command not found。
#
# 最小集说明（对应 Yocto/PetaLinux 的 python3 分包）：
#   python3-core   基础运行时 + argparse/shlex/subprocess/pathlib 等
#   python3-json   json 模块（runner 读计划/表需要）
#   python3-misc   杂项模块兜底
#
# 注意：PetaLinux 2023.2 的 python3 是 3.10.x，无 tomllib（3.11+ 才有）；
# 依赖方 g3_offline_plan.py 已内置 tomllib 缺失时的严格回退解析，无需额外处理。
IMAGE_INSTALL:append = " python3-core python3-json python3-misc"
