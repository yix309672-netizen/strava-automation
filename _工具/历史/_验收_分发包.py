# -*- coding: utf-8 -*-
"""验收⑤: 分发包布局下(_分发给同事/ 平铺, config 与脚本同目录)界面与引擎读到的是新参数

用法: python _验收_分发包.py
"""
import importlib.util
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
PKG = WS / "_分发给同事"
FAILS, N = [], [0]


def ck(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


print("=== 分发包界面(平铺布局) ===")
for f, nm in (("_gui_ads.py", "pkg_gui_ads"), ("_gui_bit.py", "pkg_gui_bit")):
    m = load(PKG / f, nm)
    app = m.App()
    try:
        app.withdraw()
        c = app._cfg()
        ck(f"{f}: min_athletes=5000", str(c.get("min_athletes")) == "5000", c.get("min_athletes"))
        ck(f"{f}: 每号目标=200", str(c.get("collect_target_per_account")) == "200",
           c.get("collect_target_per_account"))
        ck(f"{f}: 采集州=['New York']", c.get("collect_regions") == ["New York"],
           c.get("collect_regions"))
        ck(f"{f}: 不再下发 check_per_segment", "check_per_segment" not in c)
    finally:
        try:
            app.destroy()
        except Exception:
            pass

print("\n=== 分发包引擎: 读的是包内 config(两个 key 必须是空的) ===")
for f, nm in (("strava_ads.py", "pkg_eng_ads"), ("strava_bit.py", "pkg_eng_bit")):
    m = load(PKG / f, nm)
    cfg = m.CFG
    ck(f"{f}: min_athletes=5000", int(cfg.get("min_athletes") or 0) == 5000, cfg.get("min_athletes"))
    ck(f"{f}: collect_regions 含 New York", "New York" in (cfg.get("collect_regions") or []),
       cfg.get("collect_regions"))
    ck(f"{f}: 目标人数=200", int(cfg.get("collect_target_per_account") or 0) == 200,
       cfg.get("collect_target_per_account"))
    ck(f"{f}: 环带 100~1000", int(cfg.get("geo_band_min_km") or 0) == 100
       and int(cfg.get("geo_band_max_km") or 0) == 1000,
       (cfg.get("geo_band_min_km"), cfg.get("geo_band_max_km")))
    ck(f"{f}: 硬性下限常量 5000/200", getattr(m, "MIN_ATHLETES_FLOOR", 0) == 5000
       and getattr(m, "TARGET_FLOOR", 0) == 200)
    ck(f"{f}: adspower_key 为空(不会带出作者的 key)", str(cfg.get("adspower_key") or "") == "",
       repr(cfg.get("adspower_key")))

print("\n=== 包内文件与开发目录逐字节一致 ===")
import hashlib  # noqa: E402

PAIRS = [(WS / "主脚本" / "strava_ads.py", PKG / "strava_ads.py"),
         (WS / "主脚本" / "strava_bit.py", PKG / "strava_bit.py"),
         (WS / "geo_cities.py", PKG / "geo_cities.py"),
         (WS / "界面" / "ADS自动化.py", PKG / "_gui_ads.py"),
         (WS / "界面" / "比特派自动化.py", PKG / "_gui_bit.py")]
for a, b in PAIRS:
    ha = hashlib.sha256(a.read_bytes()).hexdigest()[:16]
    hb = hashlib.sha256(b.read_bytes()).hexdigest()[:16]
    ck(f"{b.name} 与开发目录一致", ha == hb, f"{ha} vs {hb}")

print("\n================ 分发包验收结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for x in FAILS:
    print("  ✗ " + x)
sys.exit(1 if FAILS else 0)
