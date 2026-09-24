# -*- coding: utf-8 -*-
"""重写桌面的 推送更新.bat: 纯 ASCII + 确定性选脚本 + 中文提示。

★★ 修的两个问题 ★★
 1) 【选错脚本】原来用 `for %%F in ("%~dp0*.py")` 扫桌面上所有 .py,
    取【最后一个】。桌面上现在有 3 个 .py(dedupe.py / dedupe_gui.py /
    一键推送更新.py), 今天恰好枚举到最后一个是推送工具才没出事 ——
    只要目录枚举顺序一变, 它就会去跑毫不相干的脚本。
    改法: 用 findstr 找【文件内容里有 SYNC_MAP 的那个】。
    SYNC_MAP 是纯 ASCII 且只有推送工具有, 所以既不依赖文件名,
    也【不需要在 .bat 里写中文】(写中文会让 cmd 解析崩)。

 2) 【英文提示】横幅改成 type msg_push.txt, 和同事包一个套路。
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

BAT = Path(r"C:\Users\1\Desktop\推送更新.bat")
# ★ 2026-09-20: 桌面被清理过一次, 把推送工具一起删进了回收站。
#   所以除了桌面, 项目里也留一份, 且【由同一个脚本写】—— 两份永远一致。
KEEP = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_发布工具")

CONTENT = r'''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - Push Update (admin)
cd /d "%~dp0"

if not exist "%~dp0msg_push.txt" goto nobanner
type "%~dp0msg_push.txt"
echo.
goto findscript

:nobanner
echo ============================================================
echo    Strava Automation  -  PUSH UPDATE  (admin only)
echo ============================================================
echo.

:findscript
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
  echo          Install Python first, then run this file again.
  echo.
  pause
  exit /b 1
)

rem  Find the push script by CONTENT, not by name or order.
rem  SYNC_MAP is ASCII-only and exists only in the push tool, so this
rem  is immune to other .py files sitting in the same folder.
set "PYFILE="
set "PYCOUNT=0"
for %%F in ("%~dp0*.py") do (
  set /a PYCOUNT+=1
  findstr /m /c:"SYNC_MAP" "%%~fF" >nul 2>&1 && set "PYFILE=%%~fF"
)
if not defined PYFILE (
  echo  [ERROR] Push script not found in this folder.
  echo          No .py file here contains SYNC_MAP.
  echo          Keep the push .py file next to this .bat.
  echo.
  pause
  exit /b 1
)
if !PYCOUNT! GTR 1 echo  [note] !PYCOUNT! .py files here; picked the one with SYNC_MAP.

set "ARG="
if /i "%~1"=="check" set "ARG=--check"

echo  Python : !PYCMD!
echo  Script : !PYFILE!
if defined ARG echo  Mode   : CHECK ONLY (no upload)
echo.

!PYCMD! -X utf8 "!PYFILE!" !ARG!
set "RC=!errorlevel!"

echo.
echo ============================================================
if "!RC!"=="0" (
  if defined ARG (
    echo    CHECK finished - nothing was uploaded.
    echo    Run this file again WITHOUT the "check" argument to publish.
  ) else (
    echo    Push finished. See the instructions above.
  )
) else (
  echo    Failed - screenshot this window and send it to yourself.
)
echo ============================================================
echo.
pause
endlocal
'''

body = CONTENT.replace("\r\n", "\n").replace("\n", "\r\n")
data = body.encode("ascii", "strict")
BAT.write_bytes(data)
KEEP.mkdir(parents=True, exist_ok=True)
(KEEP / BAT.name).write_bytes(data)
# 推送工具的 .py 和中文横幅也一起备到项目里
for n in ("一键推送更新.py", "msg_push.txt"):
    src = BAT.parent / n
    if src.is_file():
        import shutil as _sh
        _sh.copy2(src, KEEP / n)

non = sum(1 for x in data if x > 127)
bare = data.count(b"\n") - data.count(b"\r\n")
print("已写入:", BAT)
print("  大小   : %d B" % len(data))
print("  非ASCII: %d" % non)
print("  裸 LF  : %d" % bare)
assert non == 0 and bare == 0, "bat 必须是纯 ASCII + CRLF"
print("  OK: 纯 ASCII + CRLF")

# 确认它引用的 msg 文件在
for line in body.split("\r\n"):
    s = line.strip()
    if s.lower().startswith("type "):
        t = s[5:].strip().strip('"').replace("%~dp0", "")
        p = BAT.parent / t
        print("  引用 %-16s 存在=%s" % (t, p.is_file()))
