# -*- coding: utf-8 -*-
"""红/绿验证: 改一个 .bat, 一键推送更新.py 到底报不报出来。

红(改之前): SYNC_MAP 只管 8 个文件 -> 改 .bat 也打印"没有任何文件变化"
绿(改之后): 遍历全部会发布的文件 -> 应当报出 Start_AdsPower.bat 内容变了

★ 安全: 用 try/finally 还原, 无论中间出什么事都把字节原样写回去, 最后校验哈希。
"""
import hashlib
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

PKG = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")
TOOL = Path(r"C:\Users\1\Desktop\一键推送更新.py")
TARGET = PKG / "Start_AdsPower.bat"

orig = TARGET.read_bytes()
h0 = hashlib.sha256(orig).hexdigest()
print(f"原始 Start_AdsPower.bat  sha256={h0[:12]}  {len(orig)} B")
print("=" * 74)

try:
    # 追加一行纯 ASCII 注释(保持 CRLF) —— 模拟"我改了启动器"
    TARGET.write_bytes(orig + b"\r\nrem probe-change-for-test\r\n")
    print(f"已改: +1 行注释, 新大小 {TARGET.stat().st_size} B")
    print("跑 一键推送更新.py --check ...")

    r = subprocess.run([sys.executable, str(TOOL), "--check"],
                       cwd=str(TOOL.parent), stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=300)
    out = r.stdout.decode("utf-8", errors="replace")

    hit_changed = "Start_AdsPower.bat" in out and "内容变了" in out
    # 只在"内容变了(...)"那一行里找
    line = next((l for l in out.splitlines() if "内容变了" in l), "")
    detected = "Start_AdsPower.bat" in line
    print()
    print("该行输出:", line.strip()[:160] if line else "(没找到该行)")
    print()
    if detected:
        print("★★★ 绿: 改 .bat 被正确报出来了 —— 盲区已修复 ★★★")
        rc = 0
    else:
        print("★★★ 红: 仍然没报出来 —— 盲区还在 ★★★")
        rc = 1
finally:
    TARGET.write_bytes(orig)
    h1 = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    print()
    print(f"已还原  sha256={h1[:12]}  一致={h1 == h0}")

sys.exit(rc)
