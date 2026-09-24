# -*- coding: utf-8 -*-
"""生成两个"独立窗口"启动器, 免得再被误关。

★★ 为什么要有 (2026-09-20 的事故) ★★
   两个界面是从【同一个控制台】里跑起来的。Windows 关掉一个控制台窗口时,
   会向挂在这个控制台上的【所有】进程发关闭信号 —— 于是关掉那个黑窗口,
   两个界面连同正在跑的采集一起全掉了。
   (链接没丢, 因为引擎是逐条落盘的; 但那批号白跑了。)

   这两个启动器用 `start` 把界面放到【它自己的新窗口 + 独立进程树】里:
     · 关掉启动器这个窗口, 界面照样跑
     · 关掉 ADS 的窗口, 比特那个不受影响
     · 标题写清楚是哪个, 一眼能分清

★ .bat 内容必须纯 ASCII(中文放文件名里就行); 中文路径交给
  _launch_gui.py 去拼, 见那个文件的说明。
"""
import sys
from pathlib import Path

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")

TEMPLATE = r'''@echo off
rem  Launch one GUI in its OWN window and its OWN process tree.
rem  Closing this launcher - or any other window - will NOT kill it.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYCMD="
if exist "%~dp0_python\python.exe" set "PYCMD="%~dp0_python\python.exe""
if not defined PYCMD if exist "%~dp0python_path.txt" (
  set /p PYFROMFILE=<"%~dp0python_path.txt"
  if exist "!PYFROMFILE!" set "PYCMD="!PYFROMFILE!""
)
if not defined PYCMD (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
  echo  [ERROR] No Python found on this computer.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0_launch_gui.py" (
  echo  [ERROR] _launch_gui.py is missing from this folder.
  echo.
  pause
  exit /b 1
)

rem  `start` puts the GUI in a NEW window with its own process tree,
rem  so nothing here is attached to this console any more.
start "%TITLE%" !PYCMD! "%~dp0_launch_gui.py" %WHICH%

echo  The GUI is opening in its own window:  %TITLE%
echo  You may close THIS window now - it will not affect the GUI.
echo.
echo  To STOP collecting, use the STOP button in the GUI - never
echo  close the console window while a task is running.
timeout /t 6 >nul
endlocal
'''

SPECS = [("启动_ADS界面.bat", "Strava-ADS", "ads"),
         ("启动_比特界面.bat", "Strava-Bit", "bit")]

bad = []
for name, title, which in SPECS:
    body = (TEMPLATE.replace("%TITLE%", title).replace("%WHICH%", which)
            .replace("\r\n", "\n").replace("\n", "\r\n"))
    try:
        data = body.encode("ascii", "strict")
    except UnicodeEncodeError as e:
        bad.append("%s 含非 ASCII: %s" % (name, e))
        continue
    (ROOT / name).write_bytes(data)
    print("  + %-24s %5d B  ASCII+CRLF OK" % (name, len(data)))

print()
if bad:
    for x in bad:
        print("  ★", x)
    sys.exit(1)
print("★★★ 两个独立窗口启动器已生成 ★★★")
