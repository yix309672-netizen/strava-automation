# -*- coding: utf-8 -*-
"""抓真机实跑的完整堆栈(不改任何逻辑)"""
import importlib.util
import json
import sys
import traceback
from pathlib import Path

WS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sa", WS / "主脚本" / "strava_ads.py")
sa = importlib.util.module_from_spec(spec)
sys.modules["sa"] = sa
spec.loader.exec_module(sa)

SEQ = sys.argv[1] if len(sys.argv) > 1 else "3"
rows = json.loads((WS / "数据" / "ads_results.json").read_text(encoding="utf-8"))
r = rows.get(str(SEQ)) or {}
cfg = dict(sa.CFG)
cfg.update({
    "collect_regions": ["New York"], "min_athletes": 5000, "max_followers": 200,
    "collect_target_per_account": 200, "segs_per_region": 0, "geo_filter": True,
    "auto_close": True,
})
print(f"实跑 {SEQ} 邮箱={r.get('email')}", flush=True)
try:
    res = sa.run_one_seq(SEQ, r.get("email", ""), r.get("password", ""), cfg)
    print("返回:", json.dumps(res, ensure_ascii=False), flush=True)
except Exception:
    print("!!! 完整堆栈:", flush=True)
    traceback.print_exc()
