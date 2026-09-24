# -*- coding: utf-8 -*-
"""给我自己的检查/验证脚本统一加 stdout 兜底。

★★ 为什么 ★★
   控制台或管道是 GBK(cp936) 时, print("✓") 这类字符会抛
   UnicodeEncodeError, 脚本在【最后一行汇总】崩掉 —— 看起来像被测对象有问题,
   其实只是自己打印不出来。同一个坑已经踩了 4 次:
     _打包给同事.py / _查_GBK打印隐患.py / _验证_推送工具异常路径.py /
     _验证_同事拿到能用.py
   与其一个个撞, 不如全量补一遍。引擎那边早就有这个兜底了。

只给【缺这段】的文件加; 已经有 reconfigure 的不动。加在 import 之后。
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

GUARD = '''

# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
'''

targets = sorted(list(ROOT.glob("_查_*.py")) + list(ROOT.glob("_验证_*.py"))
                 + list(ROOT.glob("_生成_*.py")))
changed, skipped, failed = [], [], []

for p in targets:
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        failed.append(f"{p.name}(读不了: {e})")
        continue
    if "reconfigure" in text:
        skipped.append(p.name)
        continue
    lines = text.splitlines(keepends=True)
    # 找最后一条顶层 import / from 行
    last = None
    for i, ln in enumerate(lines[:60]):
        if re.match(r"^(import |from )\S", ln):
            last = i
    if last is None:
        failed.append(f"{p.name}(找不到 import 行)")
        continue
    lines.insert(last + 1, GUARD)
    p.write_text("".join(lines), encoding="utf-8")
    changed.append(p.name)

print("=" * 70)
print(f"已加兜底 {len(changed)} 个:")
for c in changed:
    print("   +", c)
print(f"本来就有, 跳过 {len(skipped)} 个: {skipped}")
if failed:
    print(f"★ 没能处理 {len(failed)} 个:")
    for f in failed:
        print("   -", f)
print("=" * 70)
