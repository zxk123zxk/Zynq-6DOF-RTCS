#!/usr/bin/env python3
"""板端补丁（2026-10-31）：让 static_capture 也带上夹取位 ID2 偏移。

背景：ID2 偏移原先只对 dynamic_stage 生效。静态抓取到位时同样要抬高（-50 步），
否则抓住后到抬升之间臂与皮带摩擦对抗。这一条只改 `scripts/static_grasp_server.py`
一个文件，PC 侧（capture_agent.py / grasp_point.py）不用上板。

用法（板端 ~/rtcs 下）：
    cd ~/rtcs && python3 /tmp/patch.py
"""
import sys
from pathlib import Path

TARGET = Path("scripts/static_grasp_server.py")

# ① 常量：接在 observe 下限那条常量后面
ANCHOR_A = "GRIP_OBSERVE_MIN_MS = 1000\n"
ADD_A = '''
# 夹取位 ID2 的固定偏移（负数 = 把头抬高一点）。2026-10-31 起**静态也生效**：
# 静态到位时同样抬高 50 步，合拢时上指把方块掀起一角、与带面接触面变小，
# 抓住后到抬升之间那段时间的摩擦对抗明显减弱（动态先验证过，静态沿用同一组数）。
# 包里的 "id2_offset" 字段可逐条覆盖；填 0 就是不加偏移（回到改动前）。
DEFAULT_ID2_OFFSET = -50
ID2_OFFSET_CMDS = ("static_capture", "dynamic_stage")
'''

# ② 下发处：从"只给 dynamic_stage"改成"静态也算"
OLD_B = '''    extra = list(DYNAMIC_EXTRA.get(cmd, ()))
    offset = packet.get("id2_offset")
    if isinstance(offset, int) and offset and cmd == "dynamic_stage":
        # 现场指定的 ID2 偏移（负值 = 夹取点抬高一点），只作用于拦截位，不动静态路径。
        extra += ["--grasp-id2-offset", str(offset)]
'''
NEW_B = '''    extra = list(DYNAMIC_EXTRA.get(cmd, ()))
    offset = packet.get("id2_offset", DEFAULT_ID2_OFFSET)
    if isinstance(offset, int) and offset and cmd in ID2_OFFSET_CMDS:
        # 现场指定的 ID2 偏移（负值 = 夹取点抬高一点）。静态与拦截位共用同一组数，
        # 静态下同样能减小"抓住后到抬升之间"与传动皮带的摩擦对抗。
        extra += ["--grasp-id2-offset", str(offset)]
'''


def main() -> int:
    if not TARGET.exists():
        print("TARGET_NOT_FOUND %s（先 cd ~/rtcs）" % TARGET)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    if "DEFAULT_ID2_OFFSET" in text:
        print("ALREADY_APPLIED 已经是补丁版，无需重复")
        return 0
    missing = [name for name, anchor in (("常量锚点", ANCHOR_A), ("下发锚点", OLD_B))
               if anchor not in text]
    if missing:
        print("ANCHOR_NOT_FOUND %s：板端文件与预期版本不一致，未做任何修改。"
              "请直接拷 SD 载荷里的 static_grasp_server.py" % " / ".join(missing))
        return 2
    patched = text.replace(ANCHOR_A, ANCHOR_A + ADD_A, 1).replace(OLD_B, NEW_B, 1)
    # 落盘前先在内存里编译：语法不过就整体放弃，绝不写半成品。
    compile(patched, str(TARGET), "exec")
    # 用 write_bytes 而不是 write_text：后者在 Windows 上会把 LF 转成 CRLF，
    # 板端文件是 LF，转换后和仓库正本比对会出现"内容一致但字节不同"的假差异。
    TARGET.write_bytes(patched.encode("utf-8"))
    print("PATCHED %s（2 处：常量 + 下发条件）" % TARGET)
    print("PATCH_OK 重启 server 生效：sudo python3 scripts/static_grasp_server.py "
          "--source stdin --uio /dev/uio0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
