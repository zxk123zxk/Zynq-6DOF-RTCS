from pathlib import Path
import sys
p = Path("scripts/static_grasp_server.py")
s = p.read_text(encoding="utf-8")
if "DEFAULT_ID2_OFFSET" in s:
    print("ALREADY_APPLIED 无需重复"); sys.exit(0)
pairs = [
 ("GRIP_OBSERVE_MIN_MS = 1000\n",
  "GRIP_OBSERVE_MIN_MS = 1000\n\n"
  "# 夹取位 ID2 偏移（负=抬头）。2026-10-31 起静态也生效：到位时抬高，合拢时方块被掀起\n"
  "# 一角、与皮带接触面变小，抓住后到抬升之间的摩擦对抗明显减弱。包内 id2_offset 可覆盖。\n"
  "DEFAULT_ID2_OFFSET = -50\n"
  "ID2_OFFSET_CMDS = (\"static_capture\", \"dynamic_stage\")\n"),
 ('offset = packet.get("id2_offset")\n',
  'offset = packet.get("id2_offset", DEFAULT_ID2_OFFSET)\n'),
 ('if isinstance(offset, int) and offset and cmd == "dynamic_stage":\n',
  'if isinstance(offset, int) and offset and cmd in ID2_OFFSET_CMDS:\n'),
 ("# 现场指定的 ID2 偏移（负值 = 夹取点抬高一点），只作用于拦截位，不动静态路径。\n",
  "# 现场指定的 ID2 偏移（负值 = 夹取点抬高一点）：静态与拦截位共用同一组数。\n"),
]
for old, new in pairs:
    if s.count(old) != 1:
        print("ANCHOR_BAD 出现 %d 次：%r。未做任何修改" % (s.count(old), old[:40])); sys.exit(2)
    s = s.replace(old, new, 1)
compile(s, str(p), "exec")
p.write_bytes(s.encode("utf-8"))
print("PATCHED_OK 重启 server 生效：sudo python3 scripts/static_grasp_server.py --source stdin --uio /dev/uio0")
