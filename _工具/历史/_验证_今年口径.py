# -*- coding: utf-8 -*-
"""验证: 时间范围改成「今年」之后, 从界面到引擎整条链都对得上。"""
import ast
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

ROOT = pathlib.Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-46s %r" % ("OK  " if ok else "★FAIL", label, got))


def load_gui(p):
    spec = importlib.util.spec_from_file_location("gx", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["gx"] = m
    spec.loader.exec_module(m)
    return m


print("=" * 80)
print("验证: 时间范围 = 今年 (this_year) 整条链")
print("=" * 80)

print()
print("--- ① 两处 config.json ---")
for rel in ("配置/config.json", "_分发给同事/config.json"):
    d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    check(rel, d.get("collect_date_range"), "this_year")

print()
print("--- ② 界面能不能正确显示成「今年」 ---")
for gui in ("界面/ADS自动化.py", "界面/比特派自动化.py"):
    g = load_gui(ROOT / gui)
    lab = g._label_of(g.DATE_CHOICES, "this_year")
    check("%s 显示" % pathlib.Path(gui).name, lab, "今年")
    # 反查: 显示文字 -> 值
    check("%s 反查回值" % pathlib.Path(gui).name,
          g._value_of(g.DATE_CHOICES, "今年"), "this_year")

print()
print("--- ③ 引擎拿到的榜单口径 ---")
sys.path.insert(0, str(ROOT / "主脚本"))
spec = importlib.util.spec_from_file_location(
    "engads", ROOT / "主脚本" / "strava_ads.py")
m = importlib.util.module_from_spec(spec)
sys.modules["engads"] = m
spec.loader.exec_module(m)

check("引擎 CFG 里的值", m.CFG.get("collect_date_range"), "this_year")
g, d = m._lb_filters()
check("_lb_filters() 解析出的时间范围", d, "this_year")
check("性别仍是默认 male", g, "male")
check("this_year 属于合法取值", "this_year" in m.DATE_RANGES_VALID, True)
# 再确认一遍拼出来的 URL 参数
check("非法值会被挡住(不会发给 Strava)",
      m._lb_filters("male", "year2026")[1], "this_month")

print()
print("--- ④ update.py 的强制名单 ---")
src = (ROOT / "update.py").read_text(encoding="utf-8")
tree = ast.parse(src)
keys = None
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "POLICY_KEYS":
        keys = [e.value for e in node.value.elts]
check("POLICY_KEYS 已摘掉 collect_regions",
      "collect_regions" in (keys or []), False)
# ★ 2026-09-19 更正: min_athletes 也摘掉了 —— 界面上现在有「每段≥」下拉框,
#   留在强制名单里会每次更新把同事的选择改回服务器值(下拉框白做)。
#   这条断言原来写反了, 是它自己过时, 不是代码错了。
check("min_athletes 也已摘掉(它现在由「每段≥」下拉框决定)",
      "min_athletes" in (keys or []), False)
check("jobs 仍在(仍强制下发)", "jobs" in (keys or []), True)
check("max_followers 仍在", "max_followers" in (keys or []), True)
print("        现在的名单: %s" % (keys,))

print()
print("=" * 80)
if FAIL:
    print("★ 失败 %d 项: %s" % (len(FAIL), FAIL))
    raise SystemExit(1)
print("✓ 通过 %d 项: 配置=今年 · 界面显示「今年」· 引擎用 this_year · 强制名单已解冲突" % len(PASS))
