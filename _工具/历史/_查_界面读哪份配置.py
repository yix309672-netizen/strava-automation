# -*- coding: utf-8 -*-
"""查: 界面为什么把「每段≥」显示成 5000, 而引擎用 2000。

已确认:
  · _label_of(MIN_ATH_CHOICES, 2000) 返回 '2000'  ✓ 函数没问题
  · 引擎读同一个 config.json, 用的是 2000       ✓ 配置没问题
  → 所以问题在【界面读配置的那段】: 它可能读的不是同一个文件。

界面的查找顺序是:
  ROOT/config.json -> ROOT/配置/config.json -> ROOT.parent/配置/... -> ROOT.parent/...
而引擎(_find_cfg)的顺序【一模一样】。那为什么结果不同?
    ★ 因为【ROOT 不一样】:
        界面在 界面/ 目录  -> ROOT = <项目>/界面
        引擎在 主脚本/ 目录 -> ROOT = <项目>/主脚本
      两者的 ROOT.parent 都是 <项目>, 但候选项的实际命中可能不同!
"""
import importlib.util
import json
import pathlib
import sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

spec = importlib.util.spec_from_file_location("g", "界面/ADS自动化.py")
g = importlib.util.module_from_spec(spec)
sys.modules["g"] = g
spec.loader.exec_module(g)

print("=" * 78)
print("界面侧")
print("=" * 78)
print("  ROOT = %s" % g.ROOT)
print("  它按这个顺序找 config.json:")
for c in (g.ROOT / "config.json", g.ROOT / "配置" / "config.json",
          g.ROOT.parent / "配置" / "config.json", g.ROOT.parent / "config.json"):
    exists = c.exists()
    mark = ""
    if exists:
        try:
            d = json.loads(c.read_text(encoding="utf-8"))
            mark = "  min_athletes=%r" % d.get("min_athletes")
        except Exception:
            mark = "  (读不了)"
    print("     %-58s %s%s" % (str(c).replace(str(pathlib.Path.cwd()), "<项目>"),
                               "有" if exists else "无", mark))
    if exists:
        print("     ^^^ 界面会【用这一份】")
        break

print()
print("=" * 78)
print("引擎侧")
print("=" * 78)
spec2 = importlib.util.spec_from_file_location("e", "主脚本/strava_ads.py")
e = importlib.util.module_from_spec(spec2)
sys.modules["e"] = e
spec2.loader.exec_module(e)
print("  ROOT = %s" % e.ROOT)
print("  _CFG_P = %s" % e._CFG_P)
print("  读到 min_athletes = %r" % e.CFG.get("min_athletes"))
print()
print("  %-24s %s" % ("界面 ROOT", g.ROOT))
print("  %-24s %s" % ("引擎 ROOT", e.ROOT))
print()
print("=" * 78)
print("结论")
print("=" * 78)
ui_cfg = None
for c in (g.ROOT / "config.json", g.ROOT / "配置" / "config.json",
          g.ROOT.parent / "配置" / "config.json", g.ROOT.parent / "config.json"):
    if c.exists():
        ui_cfg = c
        break
if ui_cfg and e._CFG_P and ui_cfg.resolve() != e._CFG_P.resolve():
    print("  ★ 界面和引擎读的【不是同一个 config.json】!")
    print("     界面: %s" % ui_cfg)
    print("     引擎: %s" % e._CFG_P)
else:
    print("  界面和引擎读的是同一份: %s" % ui_cfg)
    if ui_cfg:
        d = json.loads(ui_cfg.read_text(encoding="utf-8"))
        print("  那份里的 min_athletes = %r" % d.get("min_athletes"))
        print("  → 如果它是 2000, 界面就不该显示 5000, 得看 __init__ 的赋值时机")
