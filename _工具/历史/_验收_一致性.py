# -*- coding: utf-8 -*-
"""验收脚本④: 两版引擎核心逻辑一致性(ast 级)

用法:  python _验收_一致性.py
说明:  允许两版在"浏览器 API / 无关模块"上不同, 但采集相关的
       参数表、硬性常量、纽约必扫、豁免、自动选州必须一致。
"""
import ast
import difflib
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
A = WS / "主脚本" / "strava_ads.py"
B = WS / "主脚本" / "strava_bit.py"
FAILS, N = [], [0]


def check(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def load_funcs(p):
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = (ast.get_source_segment(src, node) or "", node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = (ast.get_source_segment(src, node) or "", node)
    return src, lines, out


sa, la, fa = load_funcs(A)
sb, lb, fb = load_funcs(B)

print("=== 参数表一致性 ===")
for fn in ("collect_regions", "check_athlete", "fetch_lb_filtered", "detect_home_loc"):
    if fn not in fa or fn not in fb:
        check(f"{fn} 两版都存在", False, f"ADS={fn in fa} BIT={fn in fb}")
        continue
    pa = [a.arg for a in fa[fn][1].args.args]
    pb = [a.arg for a in fb[fn][1].args.args]
    check(f"{fn} 参数表一致", pa == pb, f"ADS={pa} | BIT={pb}")

print("\n=== 硬性口径必须两版都在 ===")
MARKERS = {
    "每段≥5000 硬性下限常量": r"MIN_ATHLETES_FLOOR\s*=\s*5000",
    "每号≥200 硬性常量": r"TARGET_FLOOR\s*=\s*200",
    "纽约必扫判定": r"is_new_york\(",
    "纽约来源豁免上限": r"exempt_max",
    "圆心自动识别": r"resolve_center\(",
    "自动选州": r"states_in_band\(",
    "未达标要报警": r"(未达标|只采到)",
    "环带上限 1000 传入": r"(geo_band_max_km|BAND_MAX_KM)",
}
for label, pat in MARKERS.items():
    na, nb = len(re.findall(pat, sa)), len(re.findall(pat, sb))
    check(f"{label}: 两版都有", na > 0 and nb > 0, f"ADS={na} BIT={nb}")

print("\n=== 核心函数体相似度(剔除注释/文档字符串后再比, 差异要能解释) ===")


def _code_only(seg):
    seg = re.sub(r'"""(?:.|\n)*?"""', " ", seg)      # 文档字符串
    seg = re.sub(r"'''(?:.|\n)*?'''", " ", seg)
    seg = re.sub(r"#[^\n]*", " ", seg)               # 行注释
    return re.sub(r"\s+", " ", seg).strip()


for fn in ("collect_regions", "check_athlete", "fetch_lb_filtered"):
    if fn not in fa or fn not in fb:
        continue
    ta, tb = _code_only(fa[fn][0]), _code_only(fb[fn][0])
    r = difflib.SequenceMatcher(None, ta, tb).ratio()
    tag = "一致" if r > 0.9 else ("接近(结构不同)" if r > 0.7 else "★差异较大")
    print(f"  {fn:<20} 纯代码相似度 {r:.3f}  {tag}")
    if r <= 0.7:
        d = list(difflib.unified_diff(ta.split(" "), tb.split(" "), lineterm="", n=0))
        print("     前 40 个差异 token: " + " ".join(d[:40])[:500])

print("\n=== 旧口径残留检查(不许再写死 100-800 / 老默认) ===")
for label, pat in (("文案 100-800 残留", r"100-800"), ("写死芝加哥/洛杉矶筛选", r"距芝加哥/洛杉矶")):
    na, nb = len(re.findall(pat, sa)), len(re.findall(pat, sb))
    check(f"{label}", na == 0 and nb == 0, f"ADS={na} BIT={nb}")

print("\n================ 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for x in FAILS:
    print("  ✗ " + x)
sys.exit(1 if FAILS else 0)
