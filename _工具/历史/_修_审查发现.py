# -*- coding: utf-8 -*-
"""修掉全量审查发现的问题。

审查结果:
  ★ 真问题(会崩/功能静默失效):
     ① strava_bit.py 里 geo_lookup / region_is_ny 引用了 ADS 才有的名字 —— 已修
     ② claim_client.py 里重复导入 json / Path(第 295-296 行)
  · 清理项(不影响功能, 但属于"不干净"):
     ③ fix_update.py 导入 requests 没用
     ④ 发布更新.py 导入 hashlib 没用
     ⑤ JS_READ_LOC 两个引擎不一致: ADS 返回 {loc,kind}, 比特只返回 {loc}
        查过 kind 【从没被读过】-> 无害; 但两边不一致就是隐患, 统一成 ADS 那份
     ⑥ 同名函数两边实现不同 42 个: 其中多数是浏览器适配层(本该不同),
        纯逻辑函数里的差异逐个看(下面只处理【确认有害】的)
"""
import ast
import pathlib
import py_compile
import re
import sys

ROOT = pathlib.Path(".")
DONE = []


def edit(path, old, new, tag, count=1):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    n = s.count(old)
    if n == 0:
        DONE.append("· %s (没匹配到, 跳过)" % tag)
        return False
    s = s.replace(old, new, count)
    p.write_text(s, encoding="utf-8")
    DONE.append("✓ %s" % tag)
    return True


# ---------------- ② claim_client 重复导入 ----------------
p = ROOT / "claim_client.py"
s = p.read_text(encoding="utf-8")
lines = s.splitlines()
# 看看 295/296 行长什么样
print("=" * 74)
print("② claim_client.py 重复导入")
for i in (293, 294, 295, 296):
    if i < len(lines):
        print("   L%d: %s" % (i + 1, lines[i].rstrip()[:90]))
dups = [l for l in lines[292:299] if l.strip().startswith(("import json", "from pathlib"))]
if dups:
    for d in dups:
        # 只删函数体里那一处重复(模块顶部已有)
        s2 = s.replace("\n    " + d + "\n", "\n", 1)
        if s2 != s:
            s = s2
            DONE.append("✓ claim_client 删掉重复的 %s" % d.strip())
    p.write_text(s, encoding="utf-8")
else:
    DONE.append("· claim_client 没找到重复行")

# ---------------- ③ fix_update 没用的 requests ----------------
p = ROOT / "fix_update.py"
s = p.read_text(encoding="utf-8")
m = re.search(r"^(\s*)import requests.*$", s, re.M)
if m:
    line = m.group(0)
    # 只在"确实没被用"时删
    body = s.replace(line, "")
    if not re.search(r"\brequests\.", body):
        s = s.replace(line + "\n", "", 1)
        p.write_text(s, encoding="utf-8")
        DONE.append("✓ fix_update 删掉没用的 import requests")
    else:
        DONE.append("· fix_update 的 requests 其实有用到, 保留")
else:
    DONE.append("· fix_update 没有 import requests")

# ---------------- ④ 发布更新 没用的 hashlib ----------------
p = ROOT / "发布更新.py"
s = p.read_text(encoding="utf-8")
m = re.search(r"^import hashlib.*$", s, re.M)
if m:
    body = s.replace(m.group(0), "")
    if not re.search(r"\bhashlib\.", body):
        s = s.replace(m.group(0) + "\n", "", 1)
        p.write_text(s, encoding="utf-8")
        DONE.append("✓ 发布更新 删掉没用的 import hashlib")
    else:
        DONE.append("· 发布更新 的 hashlib 有用到, 保留")

# ---------------- ⑤ JS_READ_LOC 两边统一 ----------------
print()
print("=" * 74)
print("⑤ JS_READ_LOC 统一成 ADS 那份(两边不一致就是隐患)")
a = (ROOT / "主脚本" / "strava_ads.py").read_text(encoding="utf-8")
b = (ROOT / "主脚本" / "strava_bit.py").read_text(encoding="utf-8")


def grab(src, name):
    i = src.index(name + " = r\"\"\"")
    j = src.index("\"\"\"", i + len(name) + 6)
    return src[i:j + 3]


js_a = grab(a, "JS_READ_LOC")
js_b = grab(b, "JS_READ_LOC")
if js_a != js_b:
    b2 = b.replace(js_b, js_a, 1)
    if b2 != b:
        (ROOT / "主脚本" / "strava_bit.py").write_text(b2, encoding="utf-8")
        DONE.append("✓ JS_READ_LOC 统一(比特改用 ADS 那份)")
else:
    DONE.append("· JS_READ_LOC 本来就一致")

print()
print("=" * 74)
print("改了什么")
print("=" * 74)
for d in DONE:
    print("  " + d)

print()
print("语法 + pyflakes 复查:")
import subprocess
files = ["主脚本/strava_ads.py", "主脚本/strava_bit.py",
         "界面/ADS自动化.py", "界面/比特派自动化.py",
         "update.py", "fix_update.py", "发布更新.py", "claim_client.py"]
bad = 0
for f in files:
    try:
        py_compile.compile(f, doraise=True, cfile="__pycache__/x.pyc")
    except Exception as e:
        bad += 1
        print("  ★ 语法 FAIL %s: %s" % (f, str(e)[:120]))
r = subprocess.run([sys.executable, "-m", "pyflakes"] + files,
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
out = (r.stdout or "").strip()
if out:
    for l in out.splitlines():
        print("  " + l[:120])
else:
    print("  ✓ pyflakes 全干净")
print("  语法失败 %d 个" % bad)
