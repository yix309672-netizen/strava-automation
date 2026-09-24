# -*- coding: utf-8 -*-
"""量日志刷屏的开销: 旧写法(逐条插、不删) vs 新写法(批量+上限)。

实测场景: 采集时引擎每处理一个候选写一行。模拟往日志框灌 5000 行,
看总耗时, 以及灌完之后"点一下界面"有多迟钝(这才是用户说的"卡")。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

PROBE = r'''
import tkinter as tk, time, json, sys
from tkinter import ttk, scrolledtext
mode = sys.argv[1]; N = int(sys.argv[2])
root = tk.Tk(); root.withdraw()
txt = tk.Text(root, height=6); txt.pack()
root.update()

def old_style(txt, lines):
    for l in lines:
        txt.insert("end", l + "\n")
        txt.see("end")

def new_style(txt, lines, cap=800, trim=500):
    txt.insert("end", "\n".join(lines) + "\n")
    cur = int(txt.index("end-1c").split(".")[0])
    if cur > cap:
        txt.delete("1.0", "%d.0" % (cur - trim + 1))
    txt.see("end")

lines = ["[12:00:%02d] [check] athlete %d 位置='Chicago, Illinois' -> 保留" % (i % 60, i)
         for i in range(N)]
# 分 10 批灌(模拟 _drain_log 每 200ms 搬一次)
BATCH = max(1, N // 10)
t0 = time.time()
for i in range(0, N, BATCH):
    part = lines[i:i + BATCH]
    if mode == "old":
        old_style(txt, part)
    else:
        new_style(txt, part)
    root.update()
out = {"total_ms": (time.time() - t0) * 1000}
out["lines_kept"] = int(txt.index("end-1c").split(".")[0])

# ★ 关键指标: 灌完日志之后, 界面响应还快不快(改一行表格数据)
tv = ttk.Treeview(root, columns=["a"], show="headings", height=5); tv.pack()
for i in range(200): tv.insert("", "end", iid=str(i), values=("x",))
root.update()
t0 = time.time()
for i in range(20):
    tv.item(str(i), values=("y",)); root.update()
out["resp_ms"] = (time.time() - t0) * 1000
root.destroy()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def run(mode, n):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="logperf_"))
    pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, str(pf), mode, str(n)], cwd=str(tmp),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    shutil.rmtree(tmp, ignore_errors=True)
    for line in (r.stdout or "").splitlines():
        if line.startswith("PROBE="):
            return json.loads(line[6:])
    return None


print("=" * 86)
print("日志刷屏开销: 旧写法 vs 新写法")
print("=" * 86)
print("  %-10s %-12s %-14s %-16s %s"
      % ("行数", "写法", "灌入耗时(ms)", "框里留多少行", "灌完响应20次(ms)"))
print("  " + "-" * 82)
for n in (500, 2000, 5000, 10000):
    for mode, tag in (("old", "旧(逐条+不删)"), ("new", "新(批量+上限)")):
        r = run(mode, n)
        if r is None:
            print("  %-10s %-12s ★ 跑不起来" % (n, tag)); continue
        print("  %-10s %-12s %-14.0f %-16d %.0f"
              % (n, tag, r["total_ms"], r["lines_kept"], r["resp_ms"]))
    print()
print("  ★ 重点看最后一列: 日志灌满之后界面还灵不灵 —— 那才是用户说的「卡」。")
