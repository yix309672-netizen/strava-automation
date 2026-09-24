# -*- coding: utf-8 -*-
"""把 42 个"同名但实现不同"的函数逐个摊开看, 分清哪些该不同、哪些是隐患。

分类:
  A. 浏览器适配层 —— 本来就必须不同(ads_* / bb() / open_window ...)  -> 不处理
  B. 纯逻辑 —— 应该一字不差, 不同就是手抄漏改                        -> 要看差异内容
"""
import ast
import difflib
import pathlib

ROOT = pathlib.Path(".")
A = ROOT / "主脚本" / "strava_ads.py"
B = ROOT / "主脚本" / "strava_bit.py"


def funcs(p):
    src = p.read_text(encoding="utf-8")
    t = ast.parse(src)
    out = {}
    for n in ast.walk(t):
        if isinstance(n, ast.FunctionDef):
            out[n.name] = ast.get_source_segment(src, n) or ""
    return out


fa, fb = funcs(A), funcs(B)
diff = sorted(n for n in set(fa) & set(fb) if fa[n].strip() != fb[n].strip())

# 适配层关键词: 提到这些的函数本来就该不同
ADAPT = ("ads_req", "ads_list", "ads_open", "ads_close", "ads_find", "ads_active",
         "bb(", "/browser/", "bitbrowser", "adspower", "ADS_", "open_window",
         "minimize_pid", "find_window_id", "connect_over_cdp", "ws://")

print("=" * 86)
print("同名函数的差异分类(%d 个)" % len(diff))
print("=" * 86)
adapt, logic = [], []
for n in diff:
    body = fa[n] + fb[n]
    (adapt if any(k in body for k in ADAPT) else logic).append(n)

print("  A. 浏览器适配层(本该不同, 不处理): %d 个" % len(adapt))
print("     " + ", ".join(adapt))
print()
print("  B. 纯逻辑(应一字不差): %d 个" % len(logic))
print("     " + ", ".join(logic))

print()
print("=" * 86)
print("B 类逐个看差异(只打印有实质差别的)")
print("=" * 86)
for n in logic:
    d = [l for l in difflib.unified_diff(
        fa[n].splitlines(), fb[n].splitlines(), lineterm="", n=0)
        if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    # 只看去掉空白后的实质差异
    real = [l for l in d if l[1:].strip() and not l[1:].strip().startswith("#")]
    print()
    print("  --- %s  (差异行 %d, 其中非注释 %d) ---" % (n, len(d), len(real)))
    for l in real[:10]:
        print("      " + l[:118])
    if len(real) > 10:
        print("      ...还有 %d 行" % (len(real) - 10))
