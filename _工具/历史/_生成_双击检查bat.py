# -*- coding: utf-8 -*-
"""生成"双击检查.bat" —— 用 Python 写, 避免 PowerShell 的编码坑。

★ 项目铁律: .bat 必须 CRLF 换行 + 纯 ASCII 内容(中文只能出现在文件名上)。
"""
import pathlib


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

BAT = r'''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - Check
cd /d "%~dp0"

echo ============================================================
echo    Strava Automation  -  Check
echo ============================================================
echo.

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

if not defined PYCMD goto nopython
if not exist "%~dp0check.py" goto nofile

echo  Running check ... (this takes about 10 seconds)
echo.
!PYCMD! "%~dp0check.py"

echo.
echo ============================================================
echo    A result file was created on your Desktop:
echo       检查结果_<机器名>_<时间>.txt
echo    Please send that file to the admin.
echo ============================================================
echo.
pause
endlocal
exit /b 0

:nopython
echo  [ERROR] No Python found on this computer.
echo          Double-click the SETUP file first - the .bat with a
echo          Chinese name. Then run this file again.
echo.
pause
endlocal
exit /b 1

:nofile
echo  [ERROR] check.py is missing from this folder.
echo          Keep this file in the SAME folder as the scripts.
echo.
pause
endlocal
exit /b 1
'''

DST = pathlib.Path.home() / "Desktop" / "同事修复工具"
DST.mkdir(parents=True, exist_ok=True)
p = DST / "双击检查.bat"
# 统一成 CRLF, 再按 ASCII 写出
text = BAT.replace("\r\n", "\n").replace("\n", "\r\n")
p.write_bytes(text.encode("ascii"))

b = p.read_bytes()
crlf = b.count(b"\r\n")
lf = b.count(b"\n") - crlf
na = sum(1 for x in b if x > 127)
print("  已写: %s" % p)
print("  CRLF=%d  裸LF=%d  非ASCII=%d  -> %s"
      % (crlf, lf, na, "合规 ✓" if lf == 0 and na == 0 else "★ 不合规"))
print()
print("  桌面\\同事修复工具\\ 现在有:")
for f in sorted(DST.iterdir()):
    print("     %-22s %8d B" % (f.name, f.stat().st_size))
