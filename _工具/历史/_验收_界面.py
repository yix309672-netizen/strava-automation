# -*- coding: utf-8 -*-
"""验收脚本③: 两个界面 + 配置文件的采集参数(真起 Tk 检查控件与 _cfg())

用法:  python _验收_界面.py
"""
import importlib.util
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
FAILS, N = [], [0]


def check(name, cond, extra=""):
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


def buttons(w):
    out = []
    for c in w.winfo_children():
        try:
            if c.winfo_class() in ("TButton", "Button"):
                out.append(str(c.cget("text")))
        except Exception:
            pass
        out += buttons(c)
    return out


print("=== 配置文件 ===")
cfg = json.loads((WS / "配置" / "config.json").read_text(encoding="utf-8"))
check("min_athletes == 5000", cfg.get("min_athletes") == 5000, cfg.get("min_athletes"))
check("collect_target_per_account == 200", cfg.get("collect_target_per_account") == 200,
      cfg.get("collect_target_per_account"))
check("geo_band_min_km == 100", cfg.get("geo_band_min_km") == 100, cfg.get("geo_band_min_km"))
check("geo_band_max_km == 1000", cfg.get("geo_band_max_km") == 1000, cfg.get("geo_band_max_km"))
check("collect_regions 含 New York", "New York" in (cfg.get("collect_regions") or []),
      cfg.get("collect_regions"))
check("check_per_segment 键已作废/删除", "check_per_segment" not in cfg)
check("老的 adspower_key / claim_key 没被动",
      bool(cfg.get("adspower_key")) and bool(cfg.get("claim_key")))

print("\n=== 两个界面 ===")
cfgs = {}
for f, nm in (("ADS自动化.py", "gui_ads"), ("比特派自动化.py", "gui_bit")):
    print(f"\n--- {f} ---")
    m = load(WS / "界面" / f, nm)
    app = m.App()
    try:
        app.withdraw()
        c = app._cfg()
        cfgs[f] = c
        check("有「每号目标人数」输入框", hasattr(app, "var_target"),
              getattr(app, "var_target", None) and app.var_target.get())
        if hasattr(app, "var_target"):
            check("默认 200", str(app.var_target.get()) == "200", app.var_target.get())
        check("_cfg 带 collect_target_per_account=200",
              str(c.get("collect_target_per_account")) == "200", c.get("collect_target_per_account"))
        check("_cfg 不再发 check_per_segment", "check_per_segment" not in c)
        check("_cfg 不再发 segs_per_region(或为0)", str(c.get("segs_per_region", "0")) == "0",
              c.get("segs_per_region"))
        check("min_athletes 读到 5000(不再退回200)", str(c.get("min_athletes")) == "5000",
              c.get("min_athletes"))
        check("采集州= New York", c.get("collect_regions") == ["New York"], c.get("collect_regions"))
        bs = buttons(app)
        need = ["1.连接并加载", "2.扫描状态", "⟳ 刷新结果", "3.预览分配",
                "▶ 开始任务", "◎ 只采集", "■ 停止", "✕ 关闭全部浏览器"]
        missing = [x for x in need if x not in bs]
        check("8 个按钮都还在", not missing, missing or bs)
    finally:
        try:
            app.destroy()
        except Exception:
            pass

print("\n=== 关闭全部浏览器: 调的引擎函数必须真实存在 ===")
import ast  # noqa: E402

for f, eng in (("ADS自动化.py", "strava_ads.py"), ("比特派自动化.py", "strava_bit.py")):
    gui_src = (WS / "界面" / f).read_text(encoding="utf-8")
    eng_src = (WS / "主脚本" / eng).read_text(encoding="utf-8")
    names = {n.name for n in ast.parse(eng_src).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    want = "ads_close_all" if "ADS" in f else "bit_close_all"
    bad = "bit_close_all" if "ADS" in f else "ads_close_all"
    check(f"{f}: close_browsers 调 {want}()", f"SA.{want}()" in gui_src)
    check(f"{f}: 没有调错成 {bad}()", f"SA.{bad}()" not in gui_src)
    check(f"{eng}: {want} 真的存在", want in names, sorted(n for n in names if "close_all" in n))

if len(cfgs) == 2:
    a, b = cfgs.values()
    keys = ("collect_regions", "min_athletes", "max_followers", "collect_target_per_account")
    same = all(str(a.get(k)) == str(b.get(k)) for k in keys)
    check("两个界面的采集参数完全一致", same,
          {k: (a.get(k), b.get(k)) for k in keys if str(a.get(k)) != str(b.get(k))})

print("\n================ 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for x in FAILS:
    print("  ✗ " + x)
sys.exit(1 if FAILS else 0)
