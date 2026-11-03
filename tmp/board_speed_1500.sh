cd ~/rtcs && cp -n config/g3_station_plan.json config/g3_station_plan.json.bak 2>/dev/null; python3 - <<'PY'
import json
from pathlib import Path
p = Path("config/g3_station_plan.json")
d = json.loads(p.read_text(encoding="utf-8"))
for st in d["steps"]:
    speeds = st.get("speed_raw")
    if isinstance(speeds, list):
        old = sorted(set(speeds))
        st["speed_raw"] = [1500] * len(speeds)
        if old != [1500]:
            print("%-10s 六轴 %s -> 1500" % (st["name"], old))
p.write_bytes((json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
print("SPEED_PATCHED 七步六轴全部 1500")
PY
md5sum config/g3_station_plan.json
