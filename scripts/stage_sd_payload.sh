#!/usr/bin/env bash
# 只收"运行必需"的文件，集中到扁平目录 artifacts/sd_payload/，整份拖进 SD 卡的
# FAT32 分区即可。**板端要还原成两个子目录**（脚本按 ~/rtcs/scripts 与 ~/rtcs/config
# 定位，拍平进 ~/rtcs 会找不到）：
#   5 个 .py  -> ~/rtcs/scripts/
#   4 个配置  -> ~/rtcs/config/
# 镜像/证据不在其中：BOOT.BIN/image.ub 在 artifacts/sd/，evidence/*.md 只是路径留痕，
# 程序不读它们。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
payload="$repo_root/artifacts/sd_payload"

files=(
  scripts/g3_station_runner.py
  scripts/g3_offline_plan.py
  scripts/grasp_point_map.py
  scripts/teach_add_point.py
  # 板端闭环的接收端。原先漏在清单外：payload 里靠手工拷进去的那份，
  # 下次重打包时 `rm -rf` 会连它一起删掉，现场就变成"PC 发坐标、板端没人收"。
  scripts/static_grasp_server.py
  # 动态拦截的快路径（闭爪/抬升直接调 C 命令，绕过 runner 的 1858 ms 启动）
  scripts/fast_path.py
  config/g2_measured_limits.toml
  config/g3_station_plan.json
  config/g3_station_plan.template.json
)

# 示教表存在就一起带上（视觉抓取必需）；不存在不报错——第一次上板本来就要现场建。
optional=(
  config/grasp_teaching_table.json
)

for file in "${files[@]}"; do
  [[ -s "$file" ]] || { echo "MISSING $file" >&2; exit 66; }
done

rm -rf "$payload"
mkdir -p "$payload"
for file in "${files[@]}"; do
  cp "$file" "$payload/"
done
for file in "${optional[@]}"; do
  if [[ -s "$file" ]]; then
    cp "$file" "$payload/"
    echo "OPTIONAL_INCLUDED $file"
  else
    echo "OPTIONAL_ABSENT $file"
  fi
done

# 1) 限位三处同源（toml / pkg / TTL 包装层）—— 这一项必须过，否则打包出去就是错的
python3 scripts/check_limit_sync.py

# 1b) 板端 Python 版本兼容：3.12 才允许的语法（f-string 嵌套同类引号）在板上是 SyntaxError，
#     而本地 py_compile 用的是 3.13，看不出来。**只告警不阻断**（按 CLAUDE.md），
#     但看到这行就别往板上拷，否则 arm 一启动就是"runner 秒退、没有 G3_ 输出"。
if ! python3 scripts/check_py_compat.py "$payload"/*.py; then
  echo "PY_COMPAT_WARN 上面这些文件在板端 Python<=3.11 上会语法错误" >&2
fi

# 2) 计划门禁状态（信息性，不阻塞打包）：dry-run 能过说明已填实；被拒说明还差示教
python3 scripts/g3_station_runner.py "$payload/g3_station_plan.json" --once --dry-run \
  >/tmp/g3_stage_dryrun.out 2>&1 || true
if grep -q '^G3_CYCLE end=1 success=1' /tmp/g3_stage_dryrun.out; then
  echo "PLAN_STATUS filled (dry-run OK)"
else
  echo "PLAN_STATUS NOT_RUNNABLE: $(grep -m1 '^G3_PLAN_REJECTED ' /tmp/g3_stage_dryrun.out || echo 'see /tmp/g3_stage_dryrun.out')"
fi

# 3) 报出还有哪些步是占位（真跑会被拒）
placeholders=$(grep -c '"measured_at": "TODO' "$payload/g3_station_plan.json" || true)
echo "--- artifacts/sd_payload ---"
ls -l "$payload"
# 用目录里实际的份数，不用 ${#files[@]}：后者漏掉 optional 与以后新增的项，
# 会让人以为"少拷了一个"（10-29 实际踩到：目录 9 个、回显 files=8）。
staged=$(find "$payload" -maxdepth 1 -type f | wc -l)
echo "SD_PAYLOAD_OK files=$staged required=${#files[@]} placeholder_steps=$placeholders dir=$payload"
if [[ "$placeholders" -gt 0 ]]; then
  echo "WARN 有 $placeholders 步仍是占位值：真跑会被 G3_PLAN_REJECTED 挡住，先示教再跑。"
fi
