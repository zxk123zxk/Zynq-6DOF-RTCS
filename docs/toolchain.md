# 工具链与版本

赛题 3.3.3.1：推荐 Vivado / Vitis **2026.1 或 2025.2**；"如使用其他版本需在报告中说明并保证脚本可复现"。
本项目用的是 **2023.2**，理由与重跑方法见 §2、§3。报告附录 A 已按此说明，本文件是它的可核查版本。

## 1. 版本表

| 环节 | 版本 | 证据（可自行核对） |
| --- | --- | --- |
| 综合与实现 | **Vivado v.2023.2 (win64) Build 4029153** | `artifacts/reports/utilization.rpt` 第 2 行 `| Tool Version : Vivado v.2023.2 (win64) Build 4029153 Fri Oct 13 20:14:34 MDT 2023` |
| 嵌入式 Linux | **PetaLinux 2023.2** | `scripts/petalinux/build_sd_image.sh` 强制要求先 source 2023.2 的 `settings.sh`，否则不执行 |
| RTL 仿真 | **Verilator 5.008**（Icarus 备用） | `sim/run_regression_wsl.sh`，跑完打印 `RTCS_WSL_REGRESSION_PASS` |
| PS 侧程序 | C11（`-std=c11 -Wall -Wextra -Werror`），CMake | `src/ps/linux/` 的 CMakeLists |
| 板端 Python | 3.10 / 3.11（PetaLinux 2023.2 rootfs 自带） | `scripts/check_py_compat.py` 按 ≤3.11 语法扫描板端脚本 |
| 上位机 Python | 3.11 | `requirements-vision.txt` |
| 视觉依赖 | numpy 1.26.4 / opencv-python 4.10.0.84 / ultralytics 8.4.43 / PyTorch 2.5.1（**CPU**） | `requirements-vision.txt`；本机无 CUDA，`torch.cuda.is_available()==False` |
| 未使用的工具 | 未用 Vitis、未用 HLS、未用 PYNQ | `src/hls/` 为空；`src/pl` 全是手写 SystemVerilog |
| 器件 | XC7Z020CLG400-2（ALINX AX7Z020） | `src/pl/vivado/create_project.tcl` 的 `set part` |

## 2. 为什么用 2023.2 而不是 2025.2 / 2026.1

1. **板级验证是在 2023.2 上做完的**。全部实测数据（13/13、15/16、LUT 12.69%、100 MHz 收敛）
   都出自这一版，`.bit` 与 `.xsa` 也是它产出的；换版本意味着重新综合、重新上板、重新测一遍，
   而 11-04 的交节点没有第二次上板窗口。
2. **脚本没有用任何版本特有的东西**：`build.tcl` → `src/pl/vivado/create_project.tcl` 只用
   `create_project / add_files / create_bd_cell / launch_runs / report_utilization / write_hw_platform`
   这类跨版本稳定的命令；Ps7 配置是 `set_property -dict`，IP 用 vlnv 而非版本号锁定。
3. **风险已量化**：换版本最可能踩的两处是 (a) `processing_system7` / `axi_interconnect` 的 IP
   版本被自动升级，(b) XDC 里包名与前缀变化。前者用固定 `-vlnv` 可复现，后者 XDC 只有
   `clk_fpga_0` 与三个 TTL 端口，`build.tcl` 在 ttl 模式下会自动核对 U20/V15/W15 引脚与
   `LVCMOS33`，引脚一变就报错而不是悄悄过。

## 3. 在 2025.2 / 2026.1 上重跑

```bash
# 1) 硬件（会覆盖 artifacts/hw 与 artifacts/reports，先备份现有 .bit/.xsa）
vivado -mode batch -source build.tcl          # 默认 ttl + build
# 2) 只验证工程能不能重建、不出 bit（快，约 1 分钟）
vivado -mode batch -source build.tcl -tclargs base
# 3) SD 镜像
source <PetaLinux-2025.2>/settings.sh
scripts/petalinux/create_project.sh --import-hw <现有工程目录>
scripts/petalinux/build_sd_image.sh <现有工程目录>
```

预期差异：Vivado 换版本后 LUT/FF 占用会有个位数百分比浮动（报告里的 12.69% / 10.84% 是 2023.2 的数字），
时序 WNS 会因为布线器不同而变化，但 100 MHz 目标不变。

## 4. 视觉侧从零装环境

```powershell
python -m venv D:\rtcs-venv          # 不要放在仓库内：路径 260 字符会撞 Windows MAX_PATH
D:\rtcs-venv\Scripts\pip install -r requirements-vision.txt
```

`ultralytics` 会带上 torch；CPU 版足以跑到约 22 FPS（报告 §3.3 的截图就是这个工况）。
权重与哈希见 `models/vision/README.md`。
