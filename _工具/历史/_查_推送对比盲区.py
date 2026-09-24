# -*- coding: utf-8 -*-
"""演示 一键推送更新.py 的对比盲区。

事实: 它的 SYNC_MAP 只管 8 个文件, 但包里实际有 30 个会被发布的文件。
      第二节"会变的文件"只遍历 SYNC_MAP ->
      改了 .bat / msg_*.txt / 使用说明.txt, 它会照样打印
      "★ 没有任何文件变化", 让管理员以为推送没生效。

这个脚本不改任何东西, 只把"覆盖 vs 未覆盖"列出来。
"""
import importlib.util
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
TOOL = Path(r"C:\Users\1\Desktop\一键推送更新.py")
PKG = ROOT / "_分发给同事"

src = TOOL.read_text(encoding="utf-8")
m = re.search(r"SYNC_MAP = \((.*?)\n\)\n", src, re.S)
covered = set(re.findall(r'PKG / "([^"]+)"', m.group(1)))

# 复用发布端真实的排除规则
spec = importlib.util.spec_from_file_location("_pub", ROOT / "发布更新.py")
pub = importlib.util.module_from_spec(spec)
sys.modules["_pub"] = pub
spec.loader.exec_module(pub)

published = []
for f in sorted(PKG.rglob("*")):
    if not f.is_file():
        continue
    rel = f.relative_to(PKG).as_posix()
    if any(x in rel for x in pub.EXCLUDE):
        continue
    published.append(rel)

print("=" * 74)
print(f"包里【会发布】的文件: {len(published)} 个")
print(f"SYNC_MAP 覆盖的    : {len(covered)} 个 -> {sorted(covered)}")
print("=" * 74)
blind = [p for p in published if p not in covered]
print(f"★ 对比盲区: {len(blind)} 个文件改了也【不会】被报出来")
for b in blind:
    print("     -", b)
print("=" * 74)
print("结论: 包确实每次都会整体上传(发布更新.py 无条件上传整个目录),")
print("      但「变了什么」的报告只看了 %d/%d 个文件 —— 报告会骗人。"
      % (len(covered), len(published)))
