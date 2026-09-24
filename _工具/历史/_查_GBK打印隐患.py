# -*- coding: utf-8 -*-
"""扫描: 哪些脚本里的字符在 GBK(cp936) 控制台下会 print 崩。

背景(实测): _打包给同事.py 里的 print("✓") 在 GBK 控制台抛 UnicodeEncodeError,
崩在【压缩之前】, 结果是桌面上根本没有 zip。修法是 reconfigure(errors="replace")。
本脚本负责把同类隐患一次找全, 不再一个个撞。

只查【字符串字面量里】的字符 —— 注释里的无所谓(不会 print)。
用 gbk 严格编码试探, 编不过的就是危险字符。
"""
import ast
import sys
from pathlib import Path

# ★ 本脚本自己也会 print 那些危险字符 —— 刚写出来就当场崩了一次(证明检测有效)。
#   用 U+XXXX 形式打印, 全程 ASCII, 自己先不踩自己的坑。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
# 真正会被同事执行的脚本
TARGETS = ["_打包给同事.py", "_同步分发.py", "发布更新.py", "检查.py",
           "update.py", "fix_update.py", "claim_client.py", "open_app.py"]
for d in ("主脚本", "界面", "_分发给同事"):
    p = ROOT / d
    if p.is_dir():
        TARGETS += [str(x.relative_to(ROOT)) for x in p.glob("*.py")]

SAFE = {"—", "·", "★", "→", "≤", "≥", "×", "…", "　"}


def risky(ch):
    try:
        ch.encode("gbk")
        return False
    except Exception:
        return True


def scan(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return None, f"解析失败 {e}"
    hits = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for ch in node.value:
                if ord(ch) > 127 and risky(ch):
                    hits.setdefault(ch, node.lineno)
    return hits, None


print("=" * 72)
total = 0
for rel in TARGETS:
    p = ROOT / rel
    if not p.is_file():
        continue
    hits, err = scan(p)
    if err:
        print(f"  {rel:34s} {err}")
        continue
    if hits:
        total += len(hits)
        chars = " ".join(f"U+{ord(c):04X}(L{n})" for c, n in sorted(hits.items()))
        print(f"  ★ {rel:34s} {chars}")
print("=" * 72)
print(f"共 {total} 处 GBK 编不出的字符出现在字符串里 (注释里的不算)")
# 顺带确认打包脚本已经有兜底
pk = (ROOT / "_打包给同事.py").read_text(encoding="utf-8")
print("打包脚本有 reconfigure 兜底:", 'reconfigure(errors="replace")' in pk)
