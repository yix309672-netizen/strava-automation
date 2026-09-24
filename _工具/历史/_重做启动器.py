# -*- coding: utf-8 -*-
"""
重建分发包的启动/入口文件。

关键发现（已核实）：
  strava_bit.py / strava_ads.py 只用 connect_over_cdp 连接指纹浏览器
  已开好的浏览器，全库零处 .launch()、零处 DrissionPage 引用。
  => 不需要 DrissionPage，也不需要 150MB 的 Playwright 浏览器内核。

纯 ASCII 输出，避免 GBK 控制台崩溃。
"""
import re
import subprocess
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent
PKG = WS / "_分发给同事"

CRLF = "\r\n"


def wbat(name, text):
    """写 .bat，强制 CRLF（LF-only 的 bat 会让 goto/label 出错）"""
    text = text.replace("\r\n", "\n").replace("\n", CRLF)
    p = PKG / name
    p.write_bytes(text.encode("ascii"))
    return p


def wtxt(name, text):
    p = PKG / name
    p.write_text(text, encoding="utf-8", newline="\r\n")
    return p


# =====================================================================
#  启动.bat  --  只装环境，不打开界面
# =====================================================================
SETUP = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava Auto - Environment Setup
cd /d "%~dp0"

echo ============================================================
echo    Strava Automation  -  Environment Setup
echo.
echo    This file only INSTALLS things.
echo    It will NOT open the app - you open that yourself later.
echo ============================================================
echo.

rem  The 4 packages the scripts really use.
rem  (DrissionPage is NOT needed: the scripts connect to the
rem   fingerprint browser over CDP and never launch a browser.)
rem  tkinter is also required, but it ships with Python itself,
rem  which is why we must use the FULL installer and not the
rem  embeddable zip (that one has no tkinter at all).
set "PKGS=playwright requests numpy pillow"
set "PYCMD="
set "PYDIR=%~dp0_python"

rem  Use the absolute path to PowerShell: some machines have a broken
rem  or restricted PATH where a bare "powershell" is not found.
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell"

rem =====================================================================
rem  1. Is there a system Python that ALREADY has everything?
rem     If yes we download nothing at all.
rem =====================================================================
echo [1/4] Looking for a ready-to-use Python ...

rem  A Python inside this folder wins - but only if it is COMPLETE.
rem  Older packages shipped a Python without tkinter, and the GUI
rem  cannot open without tkinter, so detect that and reinstall.
if exist "%PYDIR%\python.exe" (
  "%PYDIR%\python.exe" -c "import tkinter" >nul 2>&1
  if not errorlevel 1 (
    set "PYCMD="%PYDIR%\python.exe""
    echo       Using the Python inside this folder.
    goto :DEPS
  )
  echo       The Python in this folder is incomplete.
  echo       Removing it and installing a complete one ...
  rd /s /q "%PYDIR%" >nul 2>&1
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  echo       Found the Python launcher: py -3
  set "PYCMD=py -3"
)

if not defined PYCMD (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    echo       Found python on PATH.
    set "PYCMD=python"
  )
)

if not defined PYCMD goto :PORTABLE

rem  A system Python is only good enough when it has ALL of these.
rem  tkinter is part of the standard library: it cannot be pip installed,
rem  so a Python without it is useless to us and we install our own.
set "HAVEALL=1"
!PYCMD! -c "import playwright" >nul 2>&1 || set "HAVEALL="
!PYCMD! -c "import requests"   >nul 2>&1 || set "HAVEALL="
!PYCMD! -c "import numpy"      >nul 2>&1 || set "HAVEALL="
!PYCMD! -c "import PIL"        >nul 2>&1 || set "HAVEALL="
!PYCMD! -c "import tkinter"    >nul 2>&1 || set "HAVEALL="
if defined HAVEALL (
  echo       It already has everything we need.
  goto :VERIFY
)

rem =====================================================================
rem  2. Install a COMPLETE Python inside this folder.
rem
rem     MUST be the full installer, NOT the embeddable zip:
rem     the embeddable package ships no tkinter (34 files, no tcl/tk),
rem     and this GUI is a tkinter program, so it would never open.
rem     InstallAllUsers=0 keeps it working without admin rights,
rem     and we touch nothing outside this folder (no PATH, no file
rem     associations, no py launcher).
rem =====================================================================
:PORTABLE
echo.
echo [2/4] Installing Python inside this folder
echo       about 26 MB download, no admin rights needed ...

if not exist "%PYDIR%" mkdir "%PYDIR%"

set "PYSETUP=%TEMP%\strava_py_setup.exe"
set "U1=https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe"
set "U2=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

echo       Downloading about 26 MB, please wait ...
"%PS%" -NoProfile -Command "try{$ProgressPreference='SilentlyContinue';Invoke-WebRequest -Uri '%U1%' -OutFile '%PYSETUP%' -TimeoutSec 1800 -UseBasicParsing}catch{exit 1}"
if not exist "%PYSETUP%" (
  echo       Mirror failed, trying python.org ...
  "%PS%" -NoProfile -Command "try{$ProgressPreference='SilentlyContinue';Invoke-WebRequest -Uri '%U2%' -OutFile '%PYSETUP%' -TimeoutSec 1800 -UseBasicParsing}catch{exit 1}"
)
if not exist "%PYSETUP%" (
  echo.
  echo  [ERROR] Could not download Python.
  echo          Check your internet connection and run this file again.
  echo          Or ask the admin to send you the "_python" folder directly.
  echo.
  pause
  exit /b 1
)

echo       Installing, this takes about a minute ...
"%PYSETUP%" /quiet InstallAllUsers=0 TargetDir="%PYDIR%" Include_tcltk=1 Include_pip=1 Include_launcher=0 Include_test=0 Include_doc=0 Include_debug=0 Include_symbols=0 PrependPath=0 Shortcuts=0 AssociateFiles=0 CompileAll=0

rem  NOTE: "%PYSETUP%" is deliberately NOT deleted yet - :REPAIR below may
rem  still need it. It is removed on every exit path further down.

if exist "%PYDIR%\python.exe" goto :GOTPY

rem  The installer dedupes by product name: if this user already has
rem  Python 3.11 from an earlier package, it "repairs" that one and
rem  puts nothing in our folder (exit code is still 0, see the bundle
rem  log: WixBundleInstalled=1 -> "Exit code: 0x0"). Reuse that one -
rem  but only when it really works, which is what :TRYREG checks.
echo       Python 3.11 is already installed for this user - checking it ...
call :TRYREG

if not defined PYCMD (
  rem  The registered Python is MISSING (its folder was deleted - e.g.
  rem  someone removed this folder and unpacked the package again, the
  rem  registry still points at the OLD location) or it has no tkinter
  rem  (the old packages shipped a Python without it). In both cases
  rem  the normal installer does nothing, and neither /uninstall
  rem  (returns 1603) nor installing another version (returns 1638,
  rem  the upgrade code is shared across 3.x) gets us out. /repair does:
  rem  it puts the files back at the registered location. Verified.
  echo       It is missing or incomplete - repairing, about a minute ...
  call :REPAIR
)

if exist "%PYSETUP%" del "%PYSETUP%" >nul 2>&1

if not defined PYCMD (
  echo.
  echo  [ERROR] Python could not be installed.
  echo.
  echo          This computer has a "Python 3.11.9 64-bit" entry that
  echo          is broken, so the installer refuses to install a fresh
  echo          copy. Please clear it by hand:
  echo.
  echo            1. Open  Settings - Apps - Installed apps
  echo            2. Find "Python 3.11.9 64-bit" and Uninstall it
  echo            3. Run this file again
  echo.
  echo          Still stuck? Screenshot this window and send it to the admin.
  echo.
  pause
  exit /b 1
)
if exist "%PYSETUP%" del "%PYSETUP%" >nul 2>&1
goto :DEPS


rem ---------------------------------------------------------------------
rem  :TRYREG - use the Python 3.11 that Windows has registered for this
rem  user, but only when it EXISTS and can import tkinter.
rem
rem  Checking the file alone is not enough. A registered Python whose
rem  folder was deleted still leaves an (empty) folder behind, and the
rem  old packages shipped a Python with no tkinter at all - both look
rem  "present" but cannot open the GUI. So actually import it.
rem ---------------------------------------------------------------------
:TRYREG
set "PYREG="
for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Python\PythonCore\3.11\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do set "PYREG=%%b"
if defined PYREG if "!PYREG:~-1!"=="\" set "PYREG=!PYREG:~0,-1!"
if not defined PYREG goto :eof
if not exist "!PYREG!\python.exe" goto :eof
"!PYREG!\python.exe" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :eof
set "PYCMD="!PYREG!\python.exe""
rem  Remember where it lives: Start_*.bat needs to find the same one.
>"%~dp0python_path.txt" echo !PYREG!\python.exe
echo       Using the registered Python; wrote python_path.txt.
goto :eof


rem ---------------------------------------------------------------------
rem  :REPAIR - ask the installer to restore the registered Python, then
rem  poll for up to ~80 seconds until :TRYREG succeeds.
rem ---------------------------------------------------------------------
:REPAIR
"%PYSETUP%" /repair /quiet
set "_RW=0"
:REPWAIT
call :TRYREG
if defined PYCMD goto :eof
set /a _RW+=1
if !_RW! GEQ 40 goto :eof
ping -n 3 127.0.0.1 >nul 2>&1
goto :REPWAIT

:GOTPY
if exist "%PYSETUP%" del "%PYSETUP%" >nul 2>&1
set "PYCMD="%PYDIR%\python.exe""

rem =====================================================================
rem  3. Install only the packages that are missing
rem =====================================================================
:DEPS
echo.
echo [3/4] Checking the required packages ...

rem  pip ships with the full installer; repair it if it went missing
!PYCMD! -m pip --version >nul 2>&1
if errorlevel 1 !PYCMD! -m ensurepip --default-pip >nul 2>&1

set "NEED="
!PYCMD! -c "import playwright" >nul 2>&1 || set "NEED=!NEED! playwright"
!PYCMD! -c "import requests"   >nul 2>&1 || set "NEED=!NEED! requests"
!PYCMD! -c "import numpy"      >nul 2>&1 || set "NEED=!NEED! numpy"
!PYCMD! -c "import PIL"        >nul 2>&1 || set "NEED=!NEED! pillow"

if not defined NEED (
  echo       Every package is already installed.
  goto :VERIFY
)

echo       Missing:!NEED!
echo       Downloading about 55 MB, usually 1 to 3 minutes ...
echo.
!PYCMD! -m pip install --no-warn-script-location -i https://pypi.tuna.tsinghua.edu.cn/simple!NEED!
if errorlevel 1 (
  echo.
  echo       Mirror failed, trying the default source ...
  !PYCMD! -m pip install --no-warn-script-location!NEED!
)

rem =====================================================================
rem  4. Verify
rem =====================================================================
:VERIFY
echo.
echo [4/4] Verifying ...
!PYCMD! -c "import playwright, requests, numpy, PIL" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [ERROR] Some packages are still missing.
  echo          Run this file again - already downloaded parts are kept.
  echo          If it keeps failing, screenshot this window for the admin.
  echo.
  pause
  exit /b 1
)

rem  tkinter cannot be pip installed, so check it separately and say so
!PYCMD! -c "import tkinter" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [ERROR] This Python has no tkinter, so the window cannot open.
  echo          Delete the "_python" folder and run this file again.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo    Environment is READY.
echo ============================================================
echo.

rem  Also pull the newest scripts while we are here. Silently skipped
rem  when the server cannot be reached.
if exist "%~dp0update.py" (
  !PYCMD! "%~dp0update.py" --auto
  echo.
)
echo    How to use it from now on:
echo.
echo      1. Start your fingerprint browser client first -
echo         BitBrowser or AdsPower.
echo.
echo      2. Then double-click ONE of these two files:
echo.
echo           Start_BitBrowser.bat   for BitBrowser
echo           Start_AdsPower.bat     for AdsPower
echo.
echo      3. Fill in your accounts in the table, then collect.
echo.
echo    You never need to run THIS setup file again.
echo ============================================================
echo.
pause
endlocal
"""


# =====================================================================
#  入口启动器（纯 ASCII 文件名，避免中文名 + .py 关联的坑）
# =====================================================================
ENTRY = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - __TITLE__
cd /d "%~dp0"

echo ============================================================
echo    Strava Automation  -  __TITLE__
echo ============================================================
echo.

rem  Find a Python that can run the app, then hand over to
rem  open_app.py, which knows the GUI file names.
set "PYCMD="

if exist "%~dp0_python\python.exe" set "PYCMD="%~dp0_python\python.exe""

rem  The setup may have had to reuse a Python that is already installed
rem  on this computer; it records the path here so we can find the same one.
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
  echo          Please double-click the SETUP file first.
  echo          It is the other .bat file in this folder with a
  echo          Chinese name. It installs everything for you.
  echo.
  echo          Then double-click THIS file again.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0open_app.py" (
  echo  [ERROR] open_app.py is missing from this folder.
  echo          Please unzip the package again.
  echo.
  pause
  exit /b 1
)

rem  Pull new scripts from the server when there is a newer version.
rem  It never touches accounts, results, logs or the Python runtime,
rem  and it silently skips when the server is unreachable - an update
rem  problem must never stop you from working.
if exist "%~dp0update.py" (
  echo  Checking for updates ...
  !PYCMD! "%~dp0update.py" --auto
  echo.
)

echo  BEFORE you continue, make sure your fingerprint browser
echo  client is already running, otherwise connecting will fail.
echo.
echo  Starting the GUI now - please wait a few seconds.
echo.
echo  Keep this black window open while you collect.
echo  If anything crashes, the error shows up here.
echo.

!PYCMD! "%~dp0open_app.py" __KEY__
set "RC=!errorlevel!"

echo.
if not "!RC!"=="0" (
  echo  [WARNING] The app closed with code !RC!.
  echo            Screenshot this window and send it to the admin.
  echo.
)
echo  The window can be closed now.
pause
endlocal
"""


# =====================================================================
#  open_app.py  --  纯 ASCII，用 \uXXXX 转义写中文文件名
# =====================================================================
OPENAPP = r'''# -*- coding: utf-8 -*-
"""
Entry point that launches the GUI.

Why this indirection instead of having the .bat run the GUI directly:

  * The launcher .bat files stay pure ASCII and free of Chinese text,
    which cmd.exe handles badly across codepages.
  * The GUI file names live in exactly ONE place (TARGETS below), so
    renaming them only means editing this file.
  * The GUI files start with "_" on purpose: they are internal, and a
    colleague whose computer has no Python would get nothing at all
    from double-clicking a .py file. They should use the .bat files.

Usage:  open_app.py bit     -> BitBrowser GUI  (_gui_bit.py)
        open_app.py ads     -> AdsPower GUI    (_gui_ads.py)
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

TARGETS = {
    "bit": "_gui_bit.py",
    "ads": "_gui_ads.py",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        sys.stderr.write("usage: open_app.py [bit|ads]\n")
        return 2

    which = sys.argv[1]
    script = BASE / TARGETS[which]

    if not script.exists():
        sys.stderr.write(
            "[ERROR] The GUI file is missing from this folder.\n"
            "        Please unzip the package again.\n"
        )
        return 1

    sys.stdout.write("Launching the %s GUI ...\n"
                     % ("BitBrowser" if which == "bit" else "AdsPower"))
    sys.stdout.flush()

    try:
        return subprocess.call([sys.executable, str(script)], cwd=str(BASE))
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        sys.stderr.write("[ERROR] Could not start Python: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''


# =====================================================================
#  Test_Server.bat  --  一键自检中心服务器连通性
# =====================================================================
SERVERTEST = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - Server Connection Test
cd /d "%~dp0"

echo ============================================================
echo    Strava Automation  -  Server Connection Test
echo ============================================================
echo.
echo  This checks whether this computer can reach the shared
echo  dedup server.
echo.
echo  If it cannot, collecting will refuse to start. That is on
echo  purpose: without the server, several people would start
echo  collecting the exact same athletes.
echo.

rem  server + key are read automatically from config.json
set "PYCMD="
if exist "%~dp0_python\python.exe" set "PYCMD="%~dp0_python\python.exe""

rem  The setup may have had to reuse a Python that is already installed
rem  on this computer; it records the path here so we can find the same one.
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
  echo          Double-click the SETUP file first - it is the other
  echo          .bat file in this folder, the one with a Chinese
  echo          name. Then run this file again.
  echo.
  pause
  exit /b 1
)

!PYCMD! "%~dp0claim_client.py" --test
set "RC=!errorlevel!"

echo.
echo ============================================================
if "!RC!"=="0" (
  echo    Result: OK - this computer can reach the server.
) else (
  echo    Result: FAILED - see the message above.
  echo    Wait a minute and try again, or send this window
  echo    to the admin as a screenshot.
)
echo ============================================================
echo.
pause
endlocal
"""


# =====================================================================
#  更新.bat  --  手动拉一次新版本
# =====================================================================
UPDATEBAT = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - Update
cd /d "%~dp0"

echo ============================================================
echo    Strava Automation  -  Update scripts
echo ============================================================
echo.
echo  This pulls the newest scripts from the server.
echo  Your accounts, results and the Python runtime are NOT touched.
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

if not defined PYCMD (
  echo  [ERROR] No Python found on this computer.
  echo          Double-click the SETUP file first - the .bat with a
  echo          Chinese name. Then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0update.py" (
  echo  [ERROR] update.py is missing from this folder.
  echo          Please unzip the package again.
  echo.
  pause
  exit /b 1
)

!PYCMD! "%~dp0update.py"
set "RC=!errorlevel!"

echo.
echo ============================================================
if "!RC!"=="0" (
  echo    Done. You can start the app now.
) else (
  echo    Something went wrong - screenshot this window.
)
echo ============================================================
echo.
pause
endlocal
"""


# =====================================================================
#  使用说明.txt
# =====================================================================
README = r"""════════════════════════════════════════════════════════
  使用说明
════════════════════════════════════════════════════════

  ★★★ 只有这 5 个文件是给你双击的 ★★★

        启动.bat                装环境（只做一次）
        Start_BitBrowser.bat    比特浏览器
        Start_AdsPower.bat      AdsPower
        更新.bat                想手动更新时用（平时会自动更新）
        Test_Server.bat         连不上服务器时自检

  ★ 那些 .py 文件【一律不要双击】。
    你电脑上没装 Python，双击 .py 不会有任何反应，这是正常的。
    它们不是给你点的，是给程序内部调用的。
    已经有同事在这上面卡住了，别重复。

  ★ 这个文件夹不要改名、不要拆开。所有文件必须待在一起。


════════════════════════════════════════════════════════
  三步走
════════════════════════════════════════════════════════

     ①  解压到桌面（或任意文件夹）
     ②  双击「启动.bat」装环境      约 2-3 分钟，只做一次
     ③  先开指纹浏览器客户端
         再双击 Start_BitBrowser.bat

  界面打开后，在界面里填账号、点采集（见第 ④ 步）。


════════════════════════════════════════════════════════
【第 ① 步】解压
════════════════════════════════════════════════════════

  右键压缩包 → 解压到当前文件夹。
  放桌面、放 D 盘都行，路径带中文没关系。

  别带 & # % 这类符号，也别直接把压缩包里的文件拖出来用。


════════════════════════════════════════════════════════
【第 ② 步】双击「启动.bat」装环境
════════════════════════════════════════════════════════
                                        ★ 只做一次，约 2-3 分钟

  弹出黑色窗口，它自动装好一切，你什么都不用做：

     ① 看你电脑有没有能用的 Python
        有 → 直接用（这种情况几秒钟就好了，什么都不下载）
        没有 → 自动下载完整版 Python 装进本文件夹
               （约 26 MB，不需要管理员权限，不碰你系统里的东西）
     ② 下载 4 个依赖包（约 55 MB）
     ③ 检查是否全部装好

  ★ 窗口里出现「Environment is READY.」才算成功。

      成功了长这样：
      ============================================================
         Environment is READY.
      ============================================================

  ★ 装完它【不会】打开界面 —— 这是故意的，界面你自己双击开。

  ★ 这个文件一辈子只需要跑一次。以后直接用第 ③ 步。

  ★ 装的时候别关窗口，等它跑完。
    万一中断了，重新双击一次，已经下好的不会重复下。

  ★ 如果窗口里出现 [ERROR]，把整个黑窗口截图发给管理员，
    不要自己猜。


════════════════════════════════════════════════════════
【第 ③ 步】先开指纹浏览器，再双击入口文件
════════════════════════════════════════════════════════

  ① ★ 先启动你的指纹浏览器客户端（比特浏览器 或 AdsPower）
     没开的话，后面连不上。

  ② 再双击（用哪个就双击哪个）：

          用比特浏览器 → Start_BitBrowser.bat
          用 AdsPower   → Start_AdsPower.bat

     ★ 这两个是纯英文文件名，双击一定有效 ——
       不需要你电脑装过 Python，也不需要 .py 的文件关联。
       黑窗口出来后，界面会在几秒内自己弹出来。

  ③ ★ 黑窗口【不要关】，采集期间一直让它开着。
     万一程序崩了，报错就显示在这个黑窗口里。


════════════════════════════════════════════════════════
【第 ④ 步】在界面里填账号，开始采集
════════════════════════════════════════════════════════

  ① 点「1.连接并加载」
     → 表格里出现你的浏览器环境，「编号」那一列就是环境序号

  ② 双击表格里「账号」那一格 → 填你的邮箱
     双击「密码」那一格 → 填你的密码
     ★ 填完自动保存，关掉程序也不会丢
     ★ 编号必须跟你浏览器里那个环境的序号对得上

  ③ 上面「编号 [ ] ~ [ ]」填范围，比如 1 ~ 5

  ④ 点「2.扫描状态」，看每个账号的登录 / 会员情况

  ⑤ 点「◎ 只采集」开始采集
     （想跑全流程就点「▶ 开始任务」）

     ★ 点「▶ 开始任务」时，右上角「执行内容」下拉框决定做哪几步：
          全部(资料+隐私+轨迹)   改名字+位置+头像+隐私+单位+传轨迹
          仅资料+隐私            只改资料，不传轨迹
          仅隐私                 上面都不做，只把隐私和单位设好
          仅上传轨迹             只传轨迹，不改任何资料
       「◎ 只采集」不受这个下拉框影响。

  ⑥ 随时点「■ 停止」，1 秒内立即停下


════════════════════════════════════════════════════════
  ★ 用 AdsPower 的人：先填一次 Key（只做一次）
════════════════════════════════════════════════════════

  用【比特浏览器】的人可以跳过这一节。

  用 AdsPower 的话，加载账号前要先填一次 Key，否则会提示
  「API Key mismatch」并且加载出 0 个账号。

  为什么：AdsPower 的本地 API Key 是【每台电脑各自生成】的，
  包里带的不是你的，必须换成你自己的。

  怎么做：

     ① 打开 AdsPower 客户端
     ② 进「设置」→「本地API」
     ③ 复制那一串 Key（很长的一串字母数字）
     ④ 用记事本打开本文件夹的 config.json
     ⑤ 找到这行：    "adspower_key": "",
        把 Key 粘到两个引号中间：
                       "adspower_key": "你复制的那一串",
     ⑥ 保存，重新双击 Start_AdsPower.bat

  ★ 只做这一次，以后不用再管。


════════════════════════════════════════════════════════
  ★ 更新是自动的，你不用管
════════════════════════════════════════════════════════

  你每次双击 Start_BitBrowser.bat / Start_AdsPower.bat 时，
  程序会顺便问一下服务器有没有新版本：

      有新版本 → 自动下载替换，黑窗口会显示「已更新 N 个文件」
      没新版本 → 不显示任何东西，直接开界面

  ★ 更新只换程序本身，绝对不会动：
       你的账号（bit_accounts.json / ads_accounts.json）
       采集成果（collected_users_<时间戳>.txt）
       进度、去重记录、日志、Python 环境
    config.json 只在【服务器新增了设置项】时补进去，
    你自己填过的值永远不会被覆盖。

  ★ 服务器连不上就直接跳过，不影响你使用。

  ★ 想手动更新一次：双击「更新.bat」（会显示详细过程）。

  ★ 以后不用再重新解压整个包了 —— 除非管理员特别通知。


════════════════════════════════════════════════════════
  ★ 界面打不开？按顺序做这三件事
════════════════════════════════════════════════════════

  第 1 步  确认你双击的是 Start_BitBrowser.bat，不是 .py。
           .py 双击没反应是正常的，不是你电脑坏了。

  第 2 步  重新双击「启动.bat」，完整等到 Environment is READY.
           如果它报 [ERROR]，把黑窗口截图发管理员。

  第 3 步  确认指纹浏览器客户端已经打开，再双击
           Start_BitBrowser.bat。黑窗口会一直开着并显示报错，
           截图发管理员。

  ★★★ 如果你拿的是【旧版包】（2026-09-18 之前发给你的）：
        旧版有个 bug —— 它装的 Python 缺一个界面必需的组件，
        界面 100% 打不开，重跑多少次都没用。
        解决：把旧文件夹【整个删掉】，重新解压新包，再走三步走。
        重装会重新下载约 80 MB，这是修 bug 必须的。


════════════════════════════════════════════════════════
  ★ 最重要的一件事：去重是【全局共享】的
════════════════════════════════════════════════════════

  20 个人同时采，系统自动保证【绝不会采到同一个人】。

  每次要查一个人之前，程序先问中心服务器「这个人归我吗」：

      归我   → 才打开他的资料页去看
      不归我 → 直接跳过，连页面都不打开，零流量

  查完不管合格还是淘汰都回报中心，别人就再也不会查他。

  所以：
    ✓ 可以和同事同时跑同一个州、同一个路段，不会重复
    ✓ 你可能比别人采得少，但绝不会和别人撞
    ✓ 你的 collected_users_<时间戳>.txt 是你自己采到的，别人看不到


════════════════════════════════════════════════════════
  采集结果在哪
════════════════════════════════════════════════════════

  就在本文件夹里，每次任务生成一份（文件名带任务开始时间）：
      collected_users_<YYYYMMDD>_<HHMMSS>.txt          ← 任务成品（汇总）
      collected_users_<YYYYMMDD>_<HHMMSS>_<号>.txt      ← 号级明细（每个号一份）
  一行一个链接，采到一个就自动追加一行，随时能打开看。
  ★ 文件开头几行是 # 开头的任务信息（开始/结束时间、每个号多少条），
    那不是链接，别当链接用。

  想自己留一份，直接复制走。
  （管理员那边也有汇总，丢了可以找他要）


════════════════════════════════════════════════════════
  数据都存在本文件夹，关了电脑也不会丢
════════════════════════════════════════════════════════

  bit_accounts.json     你填的账号密码（关界面自动保存）
  bit_results.json      扫描状态结果（自动保存）
  task_state.json       每个账号做到哪一步（自动保存）
  collected_users_<时间戳>.txt  每次任务的成果（自动生成）
  collected_seen.json   去重记录（★ 绝对别删）
  claim_cache_*.json    本地缓存（别删）
  logs\                 运行日志（出问题看这里）
  _python\              启动器装的 Python（★ 别删）
  python_path.txt       记录实际用的是哪个 Python（★ 别删）
                        （没这个文件也正常，说明用的是包内的 _python）


════════════════════════════════════════════════════════
  常见问题
════════════════════════════════════════════════════════

Q: 双击「启动.bat」黑窗口一闪就没了？
A: 多半被安全软件拦了。右键「启动.bat」→ 以管理员身份运行
   再试一次，或临时关掉杀毒软件。

Q: 装了很久不动？
A: 第一次总共要下约 80 MB（Python 26 MB + 依赖包 55 MB），
   网慢会久一点。窗口别关，等着就行。
   实在卡住就关掉重新双击，已经下好的不会重下。

Q: 提示下载失败？
A: 网络问题。确认能上网后重新双击一次即可。
   一直失败就截图发给管理员。

Q: 双击 Start_BitBrowser.bat 说找不到 Python？
A: 你还没跑第 ② 步。先双击「启动.bat」装环境。

Q: 双击 .py 文件没反应？
A: 对，就是没反应，这是正常的。
   .py 不是给你双击的，去双击 Start_BitBrowser.bat。

Q: 点「连接并加载」没反应 / 加载出 0 个环境？
A: 指纹浏览器客户端没开。先打开它，再点一次。

Q: ★ 提示「API Key mismatch. Please replace it」/ 加载出 0 个账号？
A: 用 AdsPower 的人会碰到这个。原因：AdsPower 的本地 API Key
   【每台电脑都不一样】，包里带的不是你的。
   解决（1 分钟）：
     ① 打开 AdsPower 客户端 → 设置 → 本地API
     ② 找到那一串 Key（很长的一串字母数字），复制
     ③ 用记事本打开本文件夹的 config.json
     ④ 找到这一行：   "adspower_key": "",
        把 Key 粘进两个引号中间，变成：
                       "adspower_key": "你复制的那一串",
     ⑤ 保存，关掉程序重新双击 Start_AdsPower.bat
   ★ 用比特浏览器的人不用管这个，比特默认不校验 Key。

Q: 提示 ModuleNotFoundError？
A: 环境没装全。重新双击「启动.bat」，它会补装缺的。

Q: 怎么知道有没有更新到新版？
A: 双击「更新.bat」，它会显示：
       [更新] 已是最新版本 (xxxxxx)     ← 已经是最新
       [更新] 已更新 N 个文件: ...      ← 刚更新了
   平时开界面时会自动更新，不用手动点。

Q: 提示「领取服务不可用」，采集直接取消了？
A: 连不上中心服务器。双击 Test_Server.bat 自检一下：
   显示「服务端 OK」就正常；连不上等一分钟再试，或找管理员。
   ★ 这是故意的：连不上就不采 ——
     否则 20 个人会立刻开始重复采同一批人。

Q: 为什么有些账号被跳过？
A: 采集需要 Strava 会员（要用热力图功能），免费号自动跳过。

Q: 采集很慢？
A: 正常。每个人都要打开一次资料页做筛选，还要模拟人的节奏，
   一个州大约 10-20 分钟。挂着不用管它。

Q: 哪些文件绝对不能删？
A: collected_users_<时间戳>.txt   你的成果
   （一次任务一个文件，文件名就是那次任务的开始时间；
     开头 # 那几行是任务信息，不是链接）
   collected_seen.json   去重记录
   bit_accounts.json     你的账号
   _python\              运行环境
   python_path.txt       运行环境在哪（有的话）


════════════════════════════════════════════════════════
  文件夹里都是什么
════════════════════════════════════════════════════════

  ★ 可以双击的 5 个：
  启动.bat                 装环境（只跑一次，不打开界面）
  Start_BitBrowser.bat     比特浏览器：装完环境后双击这个
  Start_AdsPower.bat       AdsPower：装完环境后双击这个
  更新.bat                 手动更新一次（平时会自动更新）
  Test_Server.bat          连不上服务器时双击这个自检

  ★ 不要双击的（程序内部用）：
  update.py                自动更新器，由上面的 bat 调用
  open_app.py              入口脚本，由上面的 bat 调起
  _gui_bit.py              比特浏览器界面，由 bat 自动调起
  _gui_ads.py              AdsPower 界面，由 bat 自动调起
  strava_bit.py            比特派主程序，界面自动调用
  strava_ads.py            ADS 主程序，界面自动调用
  claim_client.py          全局去重客户端
  geo_cities.py            位置判定数据

  ★ 配置和数据：
  config.json              配置（已配好，不用改）
  bit_accounts.json        你的账号（空白，界面里填）
  ads_accounts.json        同上（用 AdsPower 时填这个）
  bit_results.json         扫描结果（空白，自动填）
  ads_results.json         同上
  使用说明.txt              本文件


════════════════════════════════════════════════════════
  筛选条件（脚本自动执行，你不用管）
════════════════════════════════════════════════════════

  路段人数   ≥ 200 人
  性别       男性
  年龄段     45-54 / 55-64 / 65-69
  时间       本月
  粉丝       < 200
  关注       < 200
  私密账号   排除
  位置       保留距芝加哥 / 洛杉矶 100-800 km 的
             （没填所在地的也保留，读取出错的也保留）

  采集范围   12 个州 × 每州 8 个路段 × 每段筛 40 人
             Indiana / Michigan / Wisconsin / Iowa / Missouri /
             Ohio / Kentucky / Minnesota / Tennessee /
             West Virginia / Pennsylvania / New York


════════════════════════════════════════════════════════
  出问题了怎么办
════════════════════════════════════════════════════════

  把黑色窗口里报错的内容截图，发给管理员。
  日志也在本文件夹的  logs\  目录里。

  说清楚这三件事，管理员能更快帮你：
    1. 你双击的是哪个文件
    2. 黑窗口里最后几行写的什么
    3. 界面开出来了没有
"""


# =====================================================================
def main():
    print("[BUILD] writing launchers ...")

    p1 = wbat("启动.bat", SETUP)
    print("  启动.bat              %6d B" % p1.stat().st_size)

    for key, title in (("bit", "BitBrowser"), ("ads", "AdsPower")):
        text = ENTRY.replace("__TITLE__", title).replace("__KEY__", key)
        p = wbat("Start_%s.bat" % title, text)
        print("  Start_%-12s.bat  %6d B" % (title, p.stat().st_size))

    p2 = wbat("open_app.py", OPENAPP)   # 内容纯 ASCII，CRLF 无妨
    print("  open_app.py           %6d B" % p2.stat().st_size)

    p4 = wbat("Test_Server.bat", SERVERTEST)
    print("  Test_Server.bat       %6d B" % p4.stat().st_size)

    p5 = wbat("更新.bat", UPDATEBAT)
    print("  更新.bat                %6d B" % p5.stat().st_size)

    # 用最新的 update.py（同事端自动更新器）
    # （GUI 和引擎的同步在下面统一做）

    # 用最新的 claim_client.py（自检时可自动读 config.json 的 key）
    # 以及两个引擎主脚本 —— 以前靠手工复制，两边跑偏过一次，
    # 所以现在统一由构建脚本同步，谁是源一目了然。
    import shutil as _sh
    for _src, _dst in ((WS / "claim_client.py", PKG / "claim_client.py"),
                       (WS / "update.py", PKG / "update.py"),
                       (WS / "主脚本" / "strava_ads.py", PKG / "strava_ads.py"),
                       (WS / "主脚本" / "strava_bit.py", PKG / "strava_bit.py"),
                       # 界面也要同步 —— 以前只改名不复制内容,
                       # 结果界面里的修复永远到不了同事手里
                       (WS / "界面" / "ADS自动化.py", PKG / "_gui_ads.py"),
                       (WS / "界面" / "比特派自动化.py", PKG / "_gui_bit.py")):
        if _src.is_file():
            if (not _dst.exists()
                    or _dst.read_bytes() != _src.read_bytes()):
                _sh.copy2(_src, _dst)
                print("  %-20s 已从 %s 同步 (%d B)"
                      % (_dst.name, _src.parent.name, _dst.stat().st_size))

    p3 = wtxt("使用说明.txt", README)
    print("  使用说明.txt            %6d B" % p3.stat().st_size)

    # ---------------- GUI 文件改名（幂等迁移）----------------
    #  原来叫 比特派自动化.py / ADS自动化.py。
    #  同事看到中文名的 .py 会去双击，而那台电脑往往没装 Python，
    #  双击必然打不开。改成下划线开头的英文名，谁都不会想去点它。
    for old, new in (("比特派自动化.py", "_gui_bit.py"),
                     ("ADS自动化.py", "_gui_ads.py")):
        src, dst = PKG / old, PKG / new
        if src.exists() and not dst.exists():
            src.rename(dst)
            print("  %s -> %s" % (old, new))
        elif src.exists() and dst.exists():
            src.unlink()
            print("  %s 已删除（%s 已存在）" % (old, new))

    # ---------------- 校验 ----------------
    print("\n[CHECK] validity")
    ok = True
    for name in ("启动.bat", "Start_BitBrowser.bat", "Start_AdsPower.bat",
                 "Test_Server.bat", "更新.bat", "open_app.py"):
        raw = (PKG / name).read_bytes()
        bad = [b for b in raw if b > 127]
        crlf = raw.count(b"\r\n")
        lf = raw.count(b"\n")
        ascii_ok = not bad
        crlf_ok = (crlf == lf)
        if not (ascii_ok and crlf_ok):
            ok = False
        print("  %-22s ascii=%-5s crlf=%-5s lines=%d"
              % (name, ascii_ok, crlf_ok, lf))

    # echo 行里出现 cmd 特殊字符会在 if 块内被当成语法 -> 解析崩溃
    # （曾经就是 "(the .bat with a" 里的左括号把 Test_Server.bat 搞崩的）
    print("\n[CHECK] echo 行里的 cmd 特殊字符")
    special = "()&|<>^"
    for name in ("启动.bat", "Start_BitBrowser.bat", "Start_AdsPower.bat",
                 "Test_Server.bat", "更新.bat"):
        text = (PKG / name).read_text(encoding="ascii")
        hits = []
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.lower().startswith("echo"):
                body = stripped[4:]
                found = [c for c in special if c in body]
                if found:
                    hits.append((i, "".join(found), stripped))
        if hits:
            ok = False
            print("  %-22s %d 处危险:" % (name, len(hits)))
            for i, chars, line in hits:
                print("      L%-4d [%s] %s" % (i, chars, line[:64]))
        else:
            print("  %-22s 干净" % name)

    # 括号总数必须配对，否则 cmd 一定解析失败
    print("\n[CHECK] 括号配对")
    for name in ("启动.bat", "Start_BitBrowser.bat", "Start_AdsPower.bat",
                 "Test_Server.bat", "更新.bat"):
        text = (PKG / name).read_text(encoding="ascii")
        # 去掉 rem 注释行和 echo 行再数，避免正文里的中文/文字干扰
        code = [l for l in text.splitlines()
                if not l.strip().lower().startswith(("rem", "echo"))]
        joined = "\n".join(code)
        op, cl = joined.count("("), joined.count(")")
        mark = "OK" if op == cl else "FAIL"
        if op != cl:
            ok = False
        print("  %-22s ( = %d,  ) = %d   %s" % (name, op, cl, mark))

    # open_app.py 真能跑吗（顺便确认它指向的 GUI 文件名）
    import sys as _sys
    r = subprocess.run(
        [_sys.executable, "-c",
         "import runpy,sys; sys.argv=['x']; "
         "m=runpy.run_path(r'%s'); "
         "print(ascii(sorted(m['TARGETS'].values())))"
         % str(PKG / "open_app.py")],
        capture_output=True, text=True, encoding="ascii", errors="replace")
    printed = (r.stdout or "").strip() or (r.stderr or "").strip()
    print("\n[CHECK] open_app.py TARGETS -> %s"
          % printed.replace("\n", " ")[:200])
    for want in ("_gui_bit.py", "_gui_ads.py"):
        if want not in printed:
            print("[FAIL] open_app.py 没指向 %s" % want)
            return 1

    # 目标文件真的存在吗 + 中文名（会被同事误双击）必须已经不存在
    print("[CHECK] target files exist:")
    for name in ("_gui_bit.py", "_gui_ads.py"):
        exists = (PKG / name).exists()
        print("  %-22s %s" % (name, exists))
        if not exists:
            ok = False
    for bad in ("比特派自动化.py", "ADS自动化.py"):
        if (PKG / bad).exists():
            print("  [FAIL] %s 还在 —— 同事会去双击它" % bad)
            ok = False

    if not ok:
        print("\n[FAIL] some file failed validation")
        return 1

    # ==================================================================
    #  发货前强制体检 —— 不通过就不出包
    #  （曾经出过事：有人从分发包里跑了界面，界面把真实账号写进了
    #    ads_results.json，差点连账号一起发出去）
    # ==================================================================
    print("\n[GATE] 发货前体检（不通过就不打包）")
    # ★ 这里是【子串匹配】, 所以按任务命名的成果文件要单列 collected_users_:
    #   新名字 collected_users_<时间戳>[_号].txt 不含子串 "collected_users.txt",
    #   只列旧名会让它绕过体检被打进包 —— 成果外泄给 20 个人。
    RUNTIME_JUNK = ("__pycache__", "logs", "_python", "claim_cache_",
                    "collected_users.txt", "collected_users_",
    "链接-",      # ★ 成果文件新名字(链接-日期), 打包时必须排除
                    "collected_seen.json",
                    "task_state.json", "python_path.txt",
                    "._pkg_version", ".log")
    ALLOW_MAIL = ("example.com", "test.com", "localhost", "your_", "xxx@")
    MAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+")

    blockers = []
    shipped = []
    for f in sorted(PKG.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(PKG)).replace("\\", "/")
        shipped.append(rel)

        junk = [j for j in RUNTIME_JUNK if j in rel]
        if junk:
            blockers.append("%s  <- 运行残留(%s)，不该发货" % (rel, ",".join(junk)))
            continue

        if rel.endswith((".json", "accounts.json", "results.json")):
            body = f.read_text(encoding="utf-8", errors="replace").strip()
            if rel.endswith(("accounts.json", "results.json")) and body not in ("{}", ""):
                blockers.append("%s  <- 账号/结果文件不是空白 (%d B)"
                                % (rel, f.stat().st_size))

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for mt in MAIL_RE.finditer(text):
            addr = mt.group(0)
            if any(a in addr.lower() for a in ALLOW_MAIL):
                continue
            blockers.append("%s  <- 含疑似真实邮箱: %s" % (rel, addr))

    print("    待发货 %d 个文件" % len(shipped))
    if blockers:
        print("\n  [BLOCKED] 体检不通过，拒绝打包：")
        for b in blockers:
            print("      - " + b)
        zp = WS / "_分发给同事.zip"
        if zp.exists():
            zp.unlink()
            print("\n  已删除旧的 zip，避免误发。")
        print("\n  处理办法: 删掉上面列出的运行残留，把账号/结果文件恢复成 {}")
        return 1
    print("    邮箱扫描: 干净")
    print("    账号/结果文件: 均为空白")
    print("    运行残留: 无")

    # ---------------- 打包（zipfile 精确控制内容）----------------
    print("\n[ZIP] repacking ...")
    zp = WS / "_分发给同事.zip"
    if zp.exists():
        zp.unlink()
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in shipped:
            if any(j in rel for j in RUNTIME_JUNK):
                continue
            z.write(PKG / rel, rel)

    with zipfile.ZipFile(zp) as z:
        names = sorted(z.namelist())
        print("  %s  (%.0f KB packed, %d files)"
              % (zp.name, zp.stat().st_size / 1024, len(names)))
        for n in names:
            print("    %-24s %9d B" % (n, z.getinfo(n).file_size))

        # 打包后再验一遍 zip 里真实的内容
        final = []
        for n in names:
            if any(j in n for j in RUNTIME_JUNK):
                final.append("%s  <- 运行残留混进 zip" % n)
            t = z.read(n).decode("utf-8", "ignore")
            for mt in MAIL_RE.finditer(t):
                if not any(a in mt.group(0).lower() for a in ALLOW_MAIL):
                    final.append("%s  <- zip 内含邮箱: %s" % (n, mt.group(0)))
            if n.endswith(("accounts.json", "results.json")) and t.strip() not in ("{}", ""):
                final.append("%s  <- zip 内不是空白" % n)
        if final:
            print("\n  [BLOCKED] zip 复检不通过，已删除：")
            for b in final:
                print("      - " + b)
            z.close()
            zp.unlink()
            return 1
        print("\n  zip 复检: CLEAN  (无邮箱 / 账号空白 / 无运行残留)")

    print("\n[DONE] 可以发货: %s" % zp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
