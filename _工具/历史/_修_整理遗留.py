# -*- coding: utf-8 -*-
"""修 _整理工具.py 留下的替换错误。

上一版把 `Path(__file__).parent` 全局替换成 _find_project_root(__file__),
但没考虑带前缀的写法, 于是:
    pathlib.Path(__file__).resolve().parent   ->  pathlib._find_project_root(__file__)
    os.path.Path(...) 之类同理
结果 import pathlib 之后找不到那个函数 —— 一跑就 AttributeError。

这里把 <模块>._find_project_root(__file__) 统一还原成 _find_project_root(__file__),
再检查一遍还有没有漏网的写法。
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
DIRS = [ROOT / "_工具" / d for d in ("生成", "体检", "历史")]

# 形如  pathlib._find_project_root / os.path._find_project_root / x.y._find_...
BAD = re.compile(r"\b[\w\.]*\._find_project_root\(")
fixed, checked = [], 0

for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        if "_find_project_root" not in t:
            continue
        checked += 1
        t2 = BAD.sub("_find_project_root(", t)
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            fixed.append(p.name)

print("=" * 70)
print(f"含 _find_project_root 的脚本: {checked} 个")
print(f"已修正错误写法的: {len(fixed)} 个")
for x in fixed:
    print("   ", x)

# 再扫一遍: 确认没有残留的 <模块>._find_project_root
left = []
for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        for m in BAD.finditer(t):
            left.append((p.name, m.group(0)))
print()
if left:
    print("★ 还有残留:")
    for n, s in left[:20]:
        print(f"   {n}: {s}")
else:
    print("没有残留 —— 全部是裸调用 _find_project_root(__file__)")
print("=" * 70)
