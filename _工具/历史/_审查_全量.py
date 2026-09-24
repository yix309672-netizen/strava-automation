# -*- coding: utf-8 -*-
"""全量审查: 找出"两个引擎之间对不上"的地方。

pyflakes 只能查单个文件的未定义名字。真正危险的是【跨文件不一致】:
  ① 引用了另一个引擎才有的函数名(刚才那种, 已被 except 吞掉, 功能静默失效)
  ② 同名函数两边实现不同(改了一边忘了另一边 -> 两台机器行为不一样)
  ③ 同名常量取值不同(最容易造成"我的机器能用、同事的不行")
  ④ 界面引用了引擎里不存在的属性
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
A = ROOT / "主脚本" / "strava_ads.py"
B = ROOT / "主脚本" / "strava_bit.py"
GA = ROOT / "界面" / "ADS自动化.py"
GB = ROOT / "界面" / "比特派自动化.py"


def parse(p):
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs, consts, calls = {}, {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = ast.get_source_segment(src, node) or ""
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    try:
                        consts[t.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    # 模块级定义的名字
    defined = set(funcs)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
    return funcs, consts, calls, defined


fa, ca, calla, defa = parse(A)
fb, cb, callb, defb = parse(B)
print("=" * 84)
print("审查 1: 引用了【另一个引擎才有的】名字(会被 except 吞掉, 功能静默失效)")
print("=" * 84)
bad = 0
for name, calls, defined, other, tag in (
        ("ADS", calla, defa, defb, "ads"), ("BIT", callb, defb, defa, "bit")):
    # 调用了"对方有、自己没有"的名字 —— 可疑
    sus = sorted(c for c in calls
                 if c not in defined and c in other
                 and not c.startswith("__"))
    if sus:
        bad += len(sus)
        print("  ★ %s 调用了自己没有、对方有的: %s" % (name, sus))
if not bad:
    print("  ✓ 没有这种调用")

print()
print("=" * 84)
print("审查 2: 同名函数两边实现不同(改一边忘一边 -> 两台机器行为不一样)")
print("=" * 84)
diff = []
for n in sorted(set(fa) & set(fb)):
    if fa[n].strip() != fb[n].strip():
        diff.append(n)
print("  同名但实现不同: %d 个" % len(diff))
if diff:
    print("  " + ", ".join(diff[:40]))
    if len(diff) > 40:
        print("  ...还有 %d 个" % (len(diff) - 40))
    print("  ★ 说明: 其中多数是【浏览器适配层】本来就该不同(ads_*/bb() 等),")
    print("    但如果出现在【纯逻辑函数】上, 就是真隐患 —— 下面逐个看行数差")
    for n in diff:
        la = len([x for x in fa[n].splitlines() if x.strip()])
        lb = len([x for x in fb[n].splitlines() if x.strip()])
        if abs(la - lb) <= 2 and n not in ("main",):
            print("     %-28s ADS %3d 行 / BIT %3d 行  (仅差 %d 行, 像手抄漏改)"
                  % (n, la, lb, abs(la - lb)))

print()
print("=" * 84)
print("审查 3: 同名常量取值不同(最容易造成'我的能用、同事的不行')")
print("=" * 84)
cd = []
for k in sorted(set(ca) & set(cb)):
    if ca[k] != cb[k]:
        cd.append((k, ca[k], cb[k]))
if cd:
    for k, x, y in cd:
        print("  ★ %-24s ADS=%r  BIT=%r" % (k, x, y))
else:
    print("  ✓ 两边同名常量取值一致")

print()
print("=" * 84)
print("审查 4: 界面引用了引擎里不存在的属性")
print("=" * 84)
for gui, eng, tag in ((GA, A, "ADS"), (GB, B, "BIT")):
    src = gui.read_text(encoding="utf-8")
    used = set(re.findall(r"\bSA\.(\w+)", src)) | set(re.findall(r"\bmod\.(\w+)", src))
    missing = sorted(u for u in used if u not in defa and u not in defb)
    if missing:
        print("  ★ %s 界面用到但引擎没有: %s" % (tag, missing))
    else:
        print("  ✓ %s 界面用到的引擎名字都在" % tag)

print()
print("=" * 84)
print("审查 5: 语法 + 未定义名(pyflakes)")
print("=" * 84)
import subprocess
r = subprocess.run([sys.executable, "-m", "pyflakes", str(A), str(B), str(GA),
                    str(GB), "update.py", "fix_update.py", "发布更新.py",
                    "claim_client.py"],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
out = (r.stdout or "").strip()
for line in out.splitlines():
    print("  " + line[:120])
if not out:
    print("  ✓ 全部干净")
