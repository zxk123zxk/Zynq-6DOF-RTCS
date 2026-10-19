#!/usr/bin/env bash
# 把状态机跑起来所需的文件集中到一个扁平目录 artifacts/sd_payload/，
# 直接整份拖进 SD 卡的 FAT32 分区即可（板端再按 §4.4 拷进 ~/rtcs）。
#
# 只收"运行必需"的文件：三个脚本 + 两份配置 + 一份模板（用于验证门禁是否生效）。
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
  config/g2_measured_limits.toml
  config/g3_station_plan.json
  config/g3_station_plan.template.json
)

for file in "${files[@]}"; do
  [[ -s "$file" ]] || { echo "MISSING $file" >&2; exit 66; }
done

rm -rf "$payload"
mkdir -p "$payload"
for file in "${files[@]}"; do
  cp "$file" "$payload/"
done

# 1) 限位三处同源（toml / pkg / TTL 包装层）—— 这一项必须过，否则打包出去就是错的
python3 scripts/check_limit_sync.py

# 2) 计划门禁状态（信息性，不阻塞打包）：dry-run 能过说明已填实；被拒说明还差示教
python3 scripts/g3_station_runner.py "$payload/g3_station_plan.json" --once --dry-run \
  >/tmp/g3_stage_dryrun.out 2>&1 || true
if grep -q '^G3_CYCLE end=1 success=1$' /tmp/g3_stage_dryrun.out; then
  echo "PLAN_STATUS filled (dry-run OK)"
else
  echo "PLAN_STATUS NOT_RUNNABLE: $(grep -m1 '^G3_PLAN_REJECTED ' /tmp/g3_stage_dryrun.out || echo 'see /tmp/g3_stage_dryrun.out')"
fi

# 3) 报出还有哪些步是占位（真跑会被拒）
placeholders=$(grep -c '"measured_at": "TODO' "$payload/g3_station_plan.json" || true)
echo "--- artifacts/sd_payload ---"
ls -l "$payload"
echo "SD_PAYLOAD_OK files=${#files[@]} placeholder_steps=$placeholders dir=$payload"
if [[ "$placeholders" -gt 0 ]]; then
  echo "WARN 有 $placeholders 步仍是占位值：真跑会被 G3_PLAN_REJECTED 挡住，先示教再跑。"
fi
