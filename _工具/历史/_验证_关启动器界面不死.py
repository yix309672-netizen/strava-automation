# -*- coding: utf-8 -*-
"""验证: 关掉启动器窗口, 界面【不会】跟着死。

这就是这次事故的要害: 两个界面挂同一个控制台, 关窗口=全掉。
启动器用 `start` 把界面放进【独立进程树 + 新窗口】, 所以要验的就是:
    杀掉启动器 -> 界面进程还活着。

做法: 临时目录里放一个"假界面"(只 sleep 的 python 脚本) + 拷一份真启动器,
      跑启动器, 等它把假界面拉起来, 再强杀启动器那棵树,
      最后看假界面还在不在。不动真界面, 不弹窗口。
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
TMP = Path(tempfile.mkdtemp(prefix="_launchtest_"))
ok_all = True

# 假界面: 写一个"我还活着"的文件, 然后一直睡
STUB = '''
import sys, time, pathlib
pathlib.Path("alive.txt").write_text("started", encoding="utf-8")
time.sleep(600)
'''
(TMP / "_launch_gui.py").write_text(STUB, encoding="utf-8")

for bat_name, tag in (("启动_ADS界面.bat", "ADS"), ("启动_比特界面.bat", "BIT")):
    shutil.copy2(ROOT / bat_name, TMP / bat_name)
    for f in ("alive.txt",):
        p = TMP / f
        if p.exists():
            p.unlink()

    # 启动(不要 wait, 它会 timeout 6 秒)
    p = subprocess.Popen(["cmd", "/c", str(TMP / bat_name)], cwd=str(TMP),
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    # 等假界面起来
    alive = TMP / "alive.txt"
    for _ in range(40):
        if alive.exists():
            break
        time.sleep(0.5)

    started = alive.exists()
    # ★ 强杀启动器【整棵树】—— 模拟用户关掉那个窗口
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)
    time.sleep(2)

    # 假界面还在吗? 用 wmic 找带 _launch_gui.py 的 python 进程
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*_launch_gui.py*' } | "
         "Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True, timeout=60)
    cnt = (r.stdout or "0").strip()
    survived = cnt not in ("", "0")

    good = started and survived
    if not good:
        ok_all = False
    print(f"{'OK ' if good else '★  '}{tag}: 界面起来了={started}  "
          f"杀掉启动器后仍在跑={survived}  (进程数={cnt})")

    # 清理: 杀掉残留的假界面
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*_launch_gui.py*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True, timeout=60)
    time.sleep(1)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("★★★ 关掉启动器窗口, 界面照样活着 —— 不会再一关全掉 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
