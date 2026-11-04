#!/usr/bin/env bash
# 生成提交包：把仓库里"评委会看的东西"挑出来放进 dist/Zynq-6DOF-RTCS/，再打成一个 RAR。
#
#   bash scripts/package_submission.sh          # 只铺目录 + 体检
#   bash scripts/package_submission.sh --rar    # 铺目录 + 体检 + 调 Rar.exe 打包
#
# 赛题上传要求：RAR 格式、200 MB 以内（提交系统截图）。本脚本的三条原则：
#   1) **白名单**，不是黑名单：新出现的东西默认不进包，避免 tmp/ 与中间产物混进去；
#   2) 体积大户（Vivado 工程树、旧 ABI 归档、素材库、录像）不进包，它们是本地过程产物；
#   3) 打包后自检：体积、文件名是否纯英文、有没有 __pycache__/.pyc 漏进来。
#
# 体积实测（2026-11-04）：本脚本产物解压 99MB、RAR -m5 = 77MB；若按仓库根目录清单打
# （artifacts+build+dist+docs+…），实测 -m1 就有 599MB，超上限 3 倍——**只压 dist 里那一层**。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
dist="$repo_root/dist/Zynq-6DOF-RTCS"
limit_mb=200

rm -rf "$repo_root/dist"
mkdir -p "$dist"

# ---- 源码与工程（3.3.5.1 工程包）--------------------------------------------
copy_tree() {  # copy_tree <相对路径>：非空才拷，缺失只告警不中断
  if [[ -e "$1" ]]; then
    mkdir -p "$dist/$(dirname "$1")"
    cp -r "$1" "$dist/$1"
  else
    echo "WARN_MISSING $1"
  fi
}

for item in README.md LICENSE build.tcl requirements-vision.txt \
            src sim scripts config models skill tests evidence metrics docs vision_v11; do
  copy_tree "$item"
done

# ---- 上板产物（3.3.5.1 上板工程与实测输出）----------------------------------
for item in artifacts/hw artifacts/sd artifacts/sd_payload; do
  copy_tree "$item"
done
mkdir -p "$dist/artifacts/reports"
cp artifacts/reports/*.rpt artifacts/reports/*.md artifacts/reports/*.txt \
   "$dist/artifacts/reports/" 2>/dev/null || true

# ---- 清理不该进包的 ---------------------------------------------------------
# .venv/venv 一定要剔：venv 不能跨机器搬（pyvenv.cfg 里写死了原机器的解释器路径），
# 拿到手也跑不起来，纯粹白占 12 MB / 731 个文件，还会把 pip 自带的 LICENSE 混进包里。
find "$dist" -type d \( -name "__pycache__" -o -name ".venv" -o -name "venv" \
     -o -name ".pytest_cache" -o -name "*.egg-info" \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$dist" -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.jou" -o -name "*.log" \
     -o -name ".DS_Store" -o -name "*.synctex.gz" -o -name "*.aux" -o -name "*.out" \
     -o -name "*.toc" \) -delete 2>/dev/null || true
# 视觉模块里队友的一次性调试图与重复权重不随包分发
rm -f "$dist/vision_v11/1_manual_calibrated.jpg" \
      "$dist/vision_v11/result_color.jpg" "$dist/vision_v11/result_hough.jpg" \
      "$dist/vision_v11/debug_output.txt" 2>/dev/null || true

# 技术文档、海报、报告插图、厂商资料**一律不进代码包**：
#   · 报告 PDF/TeX 与海报 PPTx 在系统里单独提交，不需要重复打包；
#   · 报告插图（工位照片等）只服务报告，脱离报告没有意义；
#   · 厂商手册版权归原厂，不随包再分发（LICENSE 里也是这么写的）。
rm -rf "$dist"/docs/images "$dist"/docs/resource_file 2>/dev/null || true
rm -f "$dist"/docs/report-1031.pdf "$dist"/docs/report-1031.tex \
      "$dist"/docs/appendix-c-llm-and-skill.tex "$dist"/docs/template-logo.png \
      "$dist"/docs/*.pptx "$dist"/docs/preview_*.png 2>/dev/null || true
# artifacts/reports 只留综合/实现/时序/方法学的 .rpt 与原始测量 .txt，
# 内部的交接与素材评估 .md（含本机绝对路径、内部取舍讨论）不进包。
rm -f "$dist"/artifacts/reports/*.md 2>/dev/null || true

# 赛题 3.3.5.4：仓库内目录名与文件名须为纯英文。docs/ 里有个别历史文件（如
# 镜像文件启动.md，旧 ABI 的复验笔记）按用户要求留在仓库里、不参与当前流程，
# 但它们不进提交包——包里出现的每个文件都必须是英文名，否则在 Linux/CI 上是断链源。
find "$dist" -type f | LC_ALL=C grep -P '[^\x00-\x7F]' | while IFS= read -r f; do
  echo "DROP_NONASCII ${f#"$dist"/}"
  rm -f "$f"
done

# ---- 体检 -------------------------------------------------------------------
echo "=== 文件数与体积 ==="
files=$(find "$dist" -type f | wc -l)
size_mb=$(( $(du -sm "$dist" | cut -f1) ))
echo "PACKAGE files=$files unpacked=${size_mb}MB limit=${limit_mb}MB(rar)"

if [[ "$size_mb" -ge "$limit_mb" ]]; then
  echo "FAIL_VOLUME 解压后 ${size_mb}MB 已超 ${limit_mb}MB；RAR 通常能压到 60-80%，但不要赌。" >&2
fi

echo "=== 非英文文件名（赛题 3.3.5.4 要求纯英文小写/数字/_/-） ==="
find "$dist" -type f | LC_ALL=C grep -P '[^\x00-\x7F]' > /tmp/rtcs_nonascii.txt || true
if [[ -s /tmp/rtcs_nonascii.txt ]]; then
  sed "s|$dist/||" /tmp/rtcs_nonascii.txt | sed 's|^|  NONASCII |'
  echo "  FAIL_NONASCII 上面的文件仍在包里，必须先改名或加进删除清单" >&2
else
  echo "  OK 全部为 ASCII 文件名"
fi

echo "=== 必备项在位检查 ==="
for must in README.md LICENSE build.tcl src/pl/rtl/rtcs_top.sv sim/run_regression_wsl.sh \
            skill/README.md metrics/README.md docs/engineering-notes.md \
            docs/toolchain.md docs/llm-collaboration.md \
            artifacts/hw/rtcs_system.bit artifacts/hw/rtcs_system.xsa \
            artifacts/reports/utilization.rpt artifacts/reports/timing_summary.rpt; do
  [[ -s "$dist/$must" ]] && echo "  OK $must" || echo "  MISSING $must"
done
echo "=== 不得入包的敏感/冗余内容（应全部为 0）==="
for pat in "docs/images" "docs/resource_file" "docs/report-1031.pdf" "docs/report-1031.tex" \
           "*.pptx" "preview_*.png" "artifacts/reports/*.md"; do
  n=$(find "$dist" -name "$pat" 2>/dev/null | wc -l)
  echo "  ${pat}: ${n}"
done

# ---- 打包 -------------------------------------------------------------------
if [[ "${1:-}" == "--rar" ]]; then
  rar_exe=""
  for cand in "/d/5.下载工具/WinRAR/Rar.exe" "/c/Program Files/WinRAR/Rar.exe" \
              "/c/Program Files (x86)/WinRAR/Rar.exe" \
              "$(command -v rar 2>/dev/null || true)"; do
    [[ -n "$cand" && -x "$cand" ]] && rar_exe="$cand" && break
  done
  if [[ -z "$rar_exe" ]]; then
    echo "NO_RAR_EXE 未找到 Rar.exe：请装 WinRAR，或右键 dist/Zynq-6DOF-RTCS 手动压缩为 RAR。" >&2
    exit 1
  fi
  # 只压缩 dist/Zynq-6DOF-RTCS 这一层。**不要压仓库根目录**——根目录含 .git(551MB)、
  # Material_Library(1.2GB)、artifacts/archive(366MB)、build(83MB) 与 dist 自身，
  # 实测根目录清单打出来是 599MB，超 200MB 上限 3 倍。
  ( cd "$repo_root/dist" && "$rar_exe" a -r -m5 -ep1 -idq \
      "Zynq-6DOF-RTCS-submission.rar" "Zynq-6DOF-RTCS" )
  rar_mb=$(du -m "$repo_root/dist/Zynq-6DOF-RTCS-submission.rar" | cut -f1)
  echo "RAR_OK dist/Zynq-6DOF-RTCS-submission.rar ${rar_mb}MB"
  [[ "$rar_mb" -lt "$limit_mb" ]] || echo "FAIL_VOLUME RAR 超过 ${limit_mb}MB" >&2
else
  echo "下一步：bash scripts/package_submission.sh --rar（WinRAR 在 /d/5.下载工具/WinRAR）"
fi
