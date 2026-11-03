#!/usr/bin/env python3
# 板端补丁（2026-11-03 第二轮）：缩短"到位 → 抓取"之间的停顿。
#
# 只改 scripts/g3_station_runner.py，两件事：
#   1. GRIPPER_OBSERVE_MS 1200 → 1000。夹爪走完全行程在 1500 步/s 下约 210 ms，1000 够用；
#      原来 1200 在"夹住永远进不了容差带"时是纯干等（1000 是 C 命令的下限）。
#   2. approach 与 grasp 目标完全相同时，不再重复下发第二条 move-six，直接进夹爪闭合，
#      日志打 G3_STEP name=grasp result=MERGED。省掉"守卫 + 同步写 + 三轮到位确认"整套往返。
#
# 按行定位锚点，改完先在内存里编译，不通过不落盘。
# 用法（板端 ~/rtcs 下）：  cd ~/rtcs && python3 /tmp/patch.py
import sys
from pathlib import Path

TARGET = Path("scripts/g3_station_runner.py")

PREV_INIT = '''        # 上一条真正执行过的运动步（名字 + 目标）：用来识别"两条相邻步的目标完全一样"。
        # approach 与 grasp 在本工位就是同一个姿态（都由 apply_grasp_point 写成插值结果），
        # 再发一次 move-six 只是让 PL 重新校验一遍再确认到位——物块在带上跑的时候，
        # 这几百毫秒等于几十毫米的漂移（2026-11-03 现场表现：只夹到方块最左边一条边）。
        prev_name: str | None = None
        prev_targets: list[int] | None = None
'''

MERGE_BRANCH = '''            elif (name == "grasp" and prev_name == "approach"
                  and prev_targets is not None and targets == prev_targets):
                # 两条相邻步目标完全相同：不重复下发。省下的是"守卫 + 同步写 + 三轮
                # 到位确认"整套往返（实测 200~400 ms）。夹爪动作照常执行。
                merged = True
                ok, out = True, "MERGED no_motion"
'''

MERGE_PRINT = '''                elif merged:
                    print(f"G3_STEP name={name} result=MERGED elapsed_ms=0 "
                          f"reason=same_pose_as_{prev_name}")
'''

PREV_UPDATE = '''            if not resume_skip and not merged:
                prev_name, prev_targets = name, list(targets)

'''


def find(lines, needle, start=0, exact_strip=False):
    for index in range(start, len(lines)):
        text = lines[index].rstrip("\r\n")
        if (text.strip() == needle) if exact_strip else (needle in text):
            return index
    return -1


def main():
    if not TARGET.exists():
        print("TARGET_NOT_FOUND %s（先 cd ~/rtcs）" % TARGET)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    if "result=MERGED" in text:
        print("ALREADY_APPLIED 已经是补丁版，无需重复")
        return 0

    lines = text.splitlines(keepends=True)

    index = find(lines, "GRIPPER_OBSERVE_MS = 1200", exact_strip=True)
    if index < 0:
        print("ANCHOR_NOT_FOUND GRIPPER_OBSERVE_MS = 1200")
        return 2
    lines[index] = lines[index].replace("1200", "1000")

    index = find(lines, 'hold: int | None = grip_hold if resume in ("lift", "place")')
    if index < 0:
        print("ANCHOR_NOT_FOUND hold: int | None = grip_hold ...")
        return 2
    lines.insert(index + 1, PREV_INIT)

    index = find(lines, "step_start = time.monotonic()", exact_strip=True)
    if index < 0:
        print("ANCHOR_NOT_FOUND step_start = time.monotonic()")
        return 2
    lines.insert(index + 1, "            merged = False\n")

    # 插在"lift 走普通六轴联动"那段注释之前：链上就是 resume 分支的直接后继
    index = find(lines, "# lift 走普通六轴联动，不拆两段（10-24 定案）：")
    if index < 0:
        print("ANCHOR_NOT_FOUND '# lift 走普通六轴联动，不拆两段'")
        return 2
    lines.insert(index, MERGE_BRANCH)

    # 从 result=OK 那行往回找最近的 else:（SKIPPED 的打印有三处，不能按第一次出现找）
    index = find(lines, "result=OK elapsed_ms={took}")
    if index < 0:
        print("ANCHOR_NOT_FOUND result=OK elapsed_ms={took}")
        return 2
    cursor = index
    while cursor > 0 and lines[cursor].strip() != "else:":
        cursor -= 1
    if cursor <= 0:
        print("ANCHOR_NOT_FOUND 打印分支的 else:")
        return 2
    lines.insert(cursor, MERGE_PRINT)

    index = find(lines, 'action = item.get("gripper")', exact_strip=True)
    if index < 0:
        print('ANCHOR_NOT_FOUND action = item.get("gripper")')
        return 2
    lines.insert(index, PREV_UPDATE)

    patched = "".join(lines)
    compile(patched, str(TARGET), "exec")
    TARGET.write_bytes(patched.encode("utf-8"))
    print("PATCHED %s（6 处：夹爪观察窗 1200→1000 + 同姿态合并）" % TARGET)
    print("PATCH_OK 下一轮抓取生效（runner 每次启动重新加载，server 不用重启）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
