cd ~/rtcs && cp -n config/g3_station_plan.json config/g3_station_plan.json.bak 2>/dev/null; python3 - <<'PY'
import json
from pathlib import Path
p = Path("config/g3_station_plan.json")
d = json.loads(p.read_text(encoding="utf-8"))
before = []
for st in d["steps"]:
    speeds = st.get("speed_raw")
    if isinstance(speeds, list):
        before.append((st["name"], sorted(set(speeds))))
        st["speed_raw"] = [1000] * len(speeds)
    g = st.get("gripper")
    if isinstance(g, dict) and "speed_raw" in g:
        before.append((st["name"] + ".gripper", [g["speed_raw"]]))
        g["speed_raw"] = 1000
for name, vals in before:
    print("%-16s 旧值 %s -> 1000" % (name, vals))
p.write_bytes((json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
print("SPEED_PATCHED 七步与夹爪全部 1000")
PY
md5sum config/g3_station_plan.json
