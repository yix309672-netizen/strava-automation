# -*- coding: utf-8 -*-
"""实跑试采: ADS 50 号, 只扫纽约, 目标 10 人(验证网格平移 + 采样排名是否生效)。

- 引擎从 主脚本/strava_ads.py 真实加载, 走界面「◎ 只采集」那条路。
- 结果真实写入 数据/collected_users_<时间戳>_50.txt 与历史总表(用户要求"也要入数据")。
- 目标 10 人: 内存里覆盖 collect_target_per_account 与 target_floor, 不改配置文件。
"""
import importlib.util, json, sys, time, os
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(str(ROOT / "主脚本"))
sys.path.insert(0, str(ROOT / "主脚本"))
sys.path.insert(0, str(ROOT))

SEQ = 50
TARGET = 10

spec = importlib.util.spec_from_file_location("strava_ads", ROOT / "主脚本" / "strava_ads.py")
m = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = m
spec.loader.exec_module(m)

# 只扫纽约, 跑得快; 目标 10 人
m.CFG["collect_regions"] = ["New York"]
m.CFG["collect_auto_regions"] = False
m.CFG["collect_target_per_account"] = TARGET
m.CFG["target_floor"] = TARGET
m.CFG["auto_close"] = True

cfg = {
    "collect_regions": ["New York"],
    "collect_auto_regions": False,
    "min_athletes": 5000,
    "max_followers": 200,
    "collect_target_per_account": TARGET,
    "segs_per_region": 0,
    "geo_filter": True,
    "auto_close": True,
    "location": "Chicago, Illinois",
}

print("=" * 78)
print(f"实跑: ADS {SEQ} 号 | 只扫 New York | 目标 {TARGET} 人 | 网格平移+按人数排名")
print("=" * 78)
t0 = time.time()
res = None
try:
    res = m.collect_one(SEQ, cfg)
except Exception as e:
    import traceback
    print("★ 异常:", e)
    traceback.print_exc(limit=5)

dt = time.time() - t0
print()
print("=" * 78)
print(f"耗时 {dt / 60:.1f} 分钟")
print("返回:", json.dumps(res, ensure_ascii=False)[:600] if res else None)
print("=" * 78)

d = ROOT / "数据"
# ★ 成果文件已改名为「链接-日期」; 两种都扫(老文件还在盘上)
fs = sorted(list(d.glob("链接-*.txt")) + list(d.glob("collected_users_*.txt")),
            key=lambda p: p.stat().st_mtime)[-4:]
print("最近的任务文件:")
for f in fs:
    n = len([x for x in f.read_text(encoding="utf-8", errors="replace").splitlines()
             if x.strip() and not x.startswith("#")])
    print(f"  {f.name}  {f.stat().st_size} 字节  {n} 条链接")
