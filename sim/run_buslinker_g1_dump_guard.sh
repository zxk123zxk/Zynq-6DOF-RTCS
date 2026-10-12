#!/usr/bin/env bash
# BusLinker 只读寄存器快照的功能回归：用 pty 假舵机验证组帧、寻址、应答解析，
# 并确认整条通路只发出 READ 指令。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
build_dir="$repo_root/build/sim"
mkdir -p "$build_dir"

gcc -std=c11 -Wall -Wextra -Werror -O2 \
  "$repo_root/src/ps/linux/apps/rtcs_buslinker_g1.c" \
  -o "$build_dir/rtcs-buslinker-g1-host"

mock_py="$build_dir/buslinker_mock.py"
mock_dev="$build_dir/buslinker_mock.dev"
mock_frames="$build_dir/buslinker_mock.frames"
rm -f "$mock_dev" "$mock_frames"
: > "$mock_frames"

cat > "$mock_py" <<'PY'
import os, pty, select, sys, time

dev_file, frames_file = sys.argv[1], sys.argv[2]
master, slave = pty.openpty()
with open(dev_file, 'w') as handle:
    handle.write(os.ttyname(slave))

regs = bytearray(0x48)

def put(addr, *values):
    for offset, value in enumerate(values):
        regs[addr + offset] = value

put(0x00, 3, 7)                 # 固件 3.7
put(0x03, 9, 3)                 # 舵机 9.3
put(0x05, 5)                    # ID 5
put(0x06, 0)                    # 1 Mbps
put(0x08, 1)                    # 对所有指令应答
put(0x0d, 70, 80, 40)           # 过温 70C / 过压 8.0V / 欠压 4.0V
put(0x10, 0xe8, 0x03)           # 最大扭矩 1000
put(0x13, 44, 47)               # 保护控制 44 / LED 报警 47
put(0x15, 32, 32, 0)            # 位置环 P/D/I
put(0x18, 16, 0)                # 最小启动力
put(0x1a, 1, 1)                 # 顺/逆时针不灵敏区
put(0x1c, 0x70, 0x17)           # 过流阈值 6000mA
put(0x1f, 0, 0)                 # 位置校正
put(0x21, 0)                    # 运行模式 0 = 位置伺服
put(0x22, 20, 200, 80, 10, 200, 10)
put(0x28, 1, 0, 0xd0, 0x07)     # 扭矩开 / 加速度 0 / 目标 2000
put(0x2c, 0, 0, 0xf4, 0x01)     # 0x2C=0 / 运行速度 500
put(0x37, 0)                    # 写入锁
put(0x38, 0xd0, 0x07, 0, 0)     # 当前位置 2000 / 速度 0
put(0x3c, 0, 0)                 # 负载
put(0x3e, 0x6f, 0x1e, 0, 0, 0)  # 电压 11.1V / 温度 30C / 标志
put(0x45, 0x96, 0)              # 电流 150mA
# V3.7 表从 0x08 跳到 0x0D、从 0x1C 跳到 0x1F；Feetech 系固件在 0x09..0x0C 放
# "最小/最大角度限制"。假舵机按待验证的机制填一组窄窗口，确保 CLI 真的去读
# 这个空档，而不是因为文档里没有就跳过。
put(0x09, 0x6c, 0x07, 0x34, 0x08)  # 角度下限 1900 / 上限 2100
put(0x1d, 0, 0)                    # 空档 0x1D..0x1E
put(0x41, 0x10)                    # 舵机状态：bit4 角度
put(0x42, 0)                       # 移动标志 0

log = open(frames_file, 'a', buffering=1)
buffer = bytearray()
deadline = time.time() + 40.0
while time.time() < deadline:
    ready, _, _ = select.select([master], [], [], 0.5)
    if not ready:
        continue
    try:
        chunk = os.read(master, 256)
    except OSError:
        break
    if not chunk:
        break
    buffer += chunk
    while True:
        start = buffer.find(b'\xff\xff')
        if start < 0:
            break
        if len(buffer) < start + 4:
            break
        # 帧总长 = LEN + 4（2 头 + ID + LEN + INST + 参数 + 校验）。READ 为 8，
        # 双字节 WRITE 为 9，所以不能再按固定 8 字节切。
        frame_len = buffer[start + 3] + 4
        if len(buffer) < start + frame_len:
            break
        frame = bytes(buffer[start:start + frame_len])
        del buffer[:start + frame_len]
        servo_id, length, inst, addr = frame[2], frame[3], frame[4], frame[5]
        log.write("id=%d len=%d inst=0x%02X addr=0x%02X flen=%d\n"
                  % (servo_id, length, inst, addr, frame_len))
        # 只应答 ID 5；别的保持沉默，让上位机超时。
        if servo_id != 5:
            continue
        if inst == 2:
            read_len = frame[6]
            payload = bytes(regs[addr:addr + read_len])
            body = bytes([servo_id, read_len + 2, 0x00]) + payload
            os.write(master, b'\xff\xff' + body + bytes([(~sum(body)) & 0xff]))
        elif inst == 3:
            data = frame[6:frame_len - 1]
            regs[addr:addr + len(data)] = data
            body = bytes([servo_id, 2, 0x00])
            os.write(master, b'\xff\xff' + body + bytes([(~sum(body)) & 0xff]))
PY

python3 "$mock_py" "$mock_dev" "$mock_frames" &
mock_pid=$!
trap 'kill "$mock_pid" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  [[ -s "$mock_dev" ]] && break
  sleep 0.1
done
[[ -s "$mock_dev" ]] || { echo 'mock servo did not publish a pty' >&2; exit 1; }
device=$(cat "$mock_dev")

"$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 dump \
  >"$build_dir/buslinker-dump.out" 2>&1

grep -q 'command=READ_REGISTER_DUMP' "$build_dir/buslinker-dump.out"
grep -q 'reg name=run_mode .*raw=\[00\] servo_error=0x00 value=0' "$build_dir/buslinker-dump.out"
grep -q 'reg name=protect_mask .*raw=\[2C 2F\] servo_error=0x00' "$build_dir/buslinker-dump.out"
grep -q 'reg name=torque_limit .*servo_error=0x00 value=1000' "$build_dir/buslinker-dump.out"
grep -q 'reg name=position_offset .*servo_error=0x00 value=0' "$build_dir/buslinker-dump.out"
grep -q 'reg name=position_speed .*raw=\[D0 07 00 00\] servo_error=0x00' "$build_dir/buslinker-dump.out"
# 文档跳过的地址空档必须被真的读到：不能因为"表里没有"就绕过。
grep -q 'reg name=gap_09_0c .*raw=\[6C 07 34 08\] servo_error=0x00' "$build_dir/buslinker-dump.out"
grep -q 'reg name=gap_1d_1e .*raw=\[00 00\] servo_error=0x00' "$build_dir/buslinker-dump.out"
grep -q 'reg name=servo_status .*servo_error=0x00 value=16' "$build_dir/buslinker-dump.out"
grep -q 'reg name=moving_flag .*servo_error=0x00 value=0' "$build_dir/buslinker-dump.out"
grep -q 'RTCS_BUSLINKER_G1_DUMP probes=26 ok=26 failed=0 read_only=1' \
  "$build_dir/buslinker-dump.out"

# 多字段块不得打印无意义的小端 value。
for block in temp_volt_thr gap_09_0c gap_1d_1e; do
  if grep -q "reg name=$block .* value=" "$build_dir/buslinker-dump.out"; then
    echo "Multi-field block $block printed a meaningless little-endian value" >&2
    exit 1
  fi
done

# 整表扫描：0x00..0x47 偶地址双字节，全部读到；某地址缺失只让那一行
# UNAVAILABLE，不得牵连相邻地址。用双字节是因为实测真舵机对 16 位字段高字节
# 的单字节读取会回固定的 0xD0 伪值。
"$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 sweep \
  >"$build_dir/buslinker-sweep.out" 2>&1
grep -q 'command=READ_REGISTER_SWEEP' "$build_dir/buslinker-sweep.out"
grep -q 'word addr=0x08 raw=\[01 6C\] servo_error=0x00' "$build_dir/buslinker-sweep.out"
grep -q 'word addr=0x0A raw=\[07 34\] servo_error=0x00' "$build_dir/buslinker-sweep.out"
grep -q 'word addr=0x40 raw=\[00 10\] servo_error=0x00' "$build_dir/buslinker-sweep.out"
[[ $(grep -c '^word addr=0x' "$build_dir/buslinker-sweep.out") -eq 36 ]]
grep -q 'RTCS_BUSLINKER_G1_SWEEP words=36 bytes=72 ok=36 failed=0 read_only=1' \
  "$build_dir/buslinker-sweep.out"

# 只读性质：假舵机记录的每一帧都必须是 READ(0x02)，且 ID 必须是 5。
[[ $(wc -l < "$mock_frames") -ge $((26 + 36)) ]]
if grep -v 'inst=0x02' "$mock_frames" | grep -q .; then
  echo 'BusLinker path emitted a non-READ frame' >&2
  grep -v 'inst=0x02' "$mock_frames" >&2
  exit 1
fi
if grep -v '^id=5 ' "$mock_frames" | grep -q .; then
  echo 'BusLinker path addressed the wrong servo ID' >&2
  exit 1
fi

# ID 不匹配时必须全部超时失败，而不是误判成功。
if "$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 6 dump \
    >"$build_dir/buslinker-wrong-id.out" 2>&1; then
  echo 'BusLinker dump accepted replies for the wrong servo ID' >&2
  exit 1
fi
grep -q 'RTCS_BUSLINKER_G1_DUMP probes=26 ok=0 failed=26 read_only=1' \
  "$build_dir/buslinker-wrong-id.out"

# ---- write-reg：唯一会写舵机的动词，逐条验证它的围栏 ----

# 读动词不得接受写选项。
if "$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 \
    --addr 0x09 --value 1 --confirm-write ping \
    >"$build_dir/buslinker-write-bad-verb.out" 2>&1; then
  echo 'read verb accepted write options' >&2
  exit 1
fi
grep -q 'write_options_only_valid_with_write_reg' "$build_dir/buslinker-write-bad-verb.out"

# 白名单之外的地址必须被拒。
if "$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 \
    --addr 0x10 --value 1000 --confirm-write write-reg \
    >"$build_dir/buslinker-write-bad-addr.out" 2>&1; then
  echo 'write-reg accepted an address outside the whitelist' >&2
  exit 1
fi
grep -q 'address_not_in_write_whitelist' "$build_dir/buslinker-write-bad-addr.out"

# 缺 --confirm-write 必须被拒。
if "$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 \
    --addr 0x09 --value 1926 write-reg \
    >"$build_dir/buslinker-write-no-confirm.out" 2>&1; then
  echo 'write-reg ran without --confirm-write' >&2
  exit 1
fi
grep -q 'write_requires_confirm_write' "$build_dir/buslinker-write-no-confirm.out"

# 广播 ID 254 必须被拒（只能单播）。
if "$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 254 \
    --addr 0x09 --value 0 --confirm-write write-reg \
    >"$build_dir/buslinker-write-broadcast.out" 2>&1; then
  echo 'write-reg accepted the broadcast ID' >&2
  exit 1
fi
grep -q 'invalid_id' "$build_dir/buslinker-write-broadcast.out"

# 上面四次拒绝都必须一帧不发。把帧记录清零，单独审写入阶段的帧。
: > "$mock_frames"
"$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 \
  --addr 0x37 --value 1 --confirm-write write-reg \
  >"$build_dir/buslinker-write-lock.out" 2>&1
grep -q 'name=write_lock addr=0x37 length=1 requested=1 before=0 persistence=SRAM_volatile' \
  "$build_dir/buslinker-write-lock.out"
grep -q 'RTCS_BUSLINKER_G1_WRITE .*requested=1 before=0 after=1 write_ack_error=0x00 value_matches=1' \
  "$build_dir/buslinker-write-lock.out"

"$build_dir/rtcs-buslinker-g1-host" --device "$device" --id 5 \
  --addr 0x09 --value 1926 --confirm-write write-reg \
  >"$build_dir/buslinker-write-limit.out" 2>&1
grep -q 'name=angle_limit_min addr=0x09 length=2 requested=1926 before=1900' \
  "$build_dir/buslinker-write-limit.out"
grep -q 'RTCS_BUSLINKER_G1_WRITE .*before=1900 after=1926 write_ack_error=0x00 value_matches=1' \
  "$build_dir/buslinker-write-limit.out"
grep -q 'TX FF FF 05 05 03 09 86 07' "$build_dir/buslinker-write-limit.out"
grep -q 'HINT 0x09/0x0B 为 NVS' "$build_dir/buslinker-write-limit.out"

# 每次成功写入固定 3 帧：写前读回 + WRITE + 写后读回。两次写入共 6 帧，
# 四次被拒的调用一帧都不许出现。
[[ $(wc -l < "$mock_frames") -eq 6 ]]
[[ $(grep -c 'inst=0x03' "$mock_frames") -eq 2 ]]
[[ $(grep -c 'inst=0x02' "$mock_frames") -eq 4 ]]
if grep 'inst=0x03' "$mock_frames" | grep -v -e 'addr=0x37' -e 'addr=0x09' | grep -q .; then
  echo 'write-reg emitted a WRITE outside the whitelist' >&2
  exit 1
fi
if grep -v '^id=5 ' "$mock_frames" | grep -q .; then
  echo 'write-reg addressed the wrong servo ID' >&2
  exit 1
fi

echo RTCS_BUSLINKER_G1_DUMP_GUARD_PASS
