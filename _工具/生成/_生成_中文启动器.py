# -*- coding: utf-8 -*-
"""把分发包里的 .bat 改成【中文提示】。

★★ 铁律: .bat 必须是纯 ASCII ★★
   实测(2026-09-20): 不管 UTF-8 还是 GBK, 只要 .bat 里出现中文, cmd.exe 就报
       'elayedExpansion' is not recognized as an internal or external command
   原因是 cmd 按【字节偏移】回读 .bat, 多字节字符让偏移错位, 后面行被截断。
   所以中文一律放 msg_*.txt, 由 .bat 用 `type` 打出来
   (chcp 65001 + UTF-8 文件 -> 实测显示正常, if() 块里、goto 之后都正常)。

两种改法:
   · 短文件(更新/修复更新/Test_Server/Start_*) -> 整份重写, 逻辑照抄
   · 长文件(启动.bat, 300 行)               -> 只换文字块, 逻辑一行不动
     每次替换都断言"确实换到了", 没换到就报错退出 —— 防止静默改坏。
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

PKG = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")

FINDPY = '''set "PYCMD="
if exist "%~dp0_python\\python.exe" set "PYCMD="%~dp0_python\\python.exe""

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
'''

NOPY = '''if not defined PYCMD (
  type "%~dp0msg_nopython.txt"
  echo.
  pause
  exit /b 1
)
'''

# 注意: 这个模板会被 % 格式化, 所以字面量 % 必须写成 %%
HEAD = '''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title %s
cd /d "%%~dp0"

type "%%~dp0%s"
echo.
'''

BATS = {}

BATS["更新.bat"] = (
    HEAD % ("Strava - Update scripts", "msg_update.txt") + FINDPY + "\n" + NOPY + '''
if not exist "%~dp0update.py" (
  type "%~dp0msg_fail.txt"
  echo.
  pause
  exit /b 1
)

!PYCMD! "%~dp0update.py"
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" (
  type "%~dp0msg_done.txt"
) else (
  type "%~dp0msg_fail.txt"
)
echo.
pause
endlocal
''')

BATS["修复更新.bat"] = (
    HEAD % ("Strava - Repair Update", "msg_repair.txt") + '''
if not exist "%~dp0fix_update.py" goto nofile

''' + FINDPY + '''
if not defined PYCMD goto nopython

!PYCMD! "%~dp0fix_update.py"
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" (
  type "%~dp0msg_done.txt"
) else (
  type "%~dp0msg_fail.txt"
)
echo.
pause
endlocal
exit /b 0

:nopython
type "%~dp0msg_nopython.txt"
echo.
pause
endlocal
exit /b 1

:nofile
type "%~dp0msg_fail.txt"
echo.
pause
endlocal
exit /b 1
''')

BATS["Test_Server.bat"] = (
    HEAD % ("Strava - Server Connection Test", "msg_test.txt") + FINDPY + "\n" + NOPY + '''
!PYCMD! "%~dp0claim_client.py" --test
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" (
  type "%~dp0msg_done.txt"
) else (
  type "%~dp0msg_fail.txt"
)
echo.
pause
endlocal
''')

# ★★ 隐藏模式(2026-09-20 用户要求"把黑色终端窗口隐藏") ★★
#   默认: 双击后立刻用 _hide.ps1 把自己的控制台窗口藏起来, 只留采集界面。
#   藏起来之后:
#     · 不能 pause —— 没有窗口可以按键, 进程会永远挂在后台
#     · 不能只 echo 报错 —— 没人看得见
#   所以出错一律走 _msgbox.vbs 弹【中文提示框】, 并把输出记到
#   logs\start_log.txt 供管理员诊断。
#   想看窗口排查:  Start_AdsPower.bat show
#
# ★ 模板用 {BANNER} / {APP} 占位, 由 start_body() 做 replace ——
#   不走 % 格式化, 所以下面的 %~dp0 可以照原样写, 不用写成 %%~dp0。
_HIDE = r'''
rem  ============================================================
rem   Hidden by default. Run with the argument  show  to keep the
rem   console window (for troubleshooting).
rem  ============================================================
set "HIDDEN=1"
if /i "%~1"=="show" set "HIDDEN="

if defined HIDDEN (
  rem  Hide THIS console window, and do it FIRST: finding Python can
  rem  take a few hundred ms, and doing it before hiding makes the
  rem  black window visibly flash. powershell shares the console with
  rem  cmd, so GetConsoleWindow() inside it returns this very window.
  rem  If it fails (no console / powershell blocked), fall back to the
  rem  visible behaviour so nothing is ever lost silently.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_hide.ps1" >nul 2>&1
  if errorlevel 1 set "HIDDEN="
)

set "FAILMSG=msg_hidden_fail.txt"
set "NOPYMSG=msg_hidden_nopython.txt"
if not defined HIDDEN (
  type "%~dp0{BANNER}"
  echo.
  set "FAILMSG=msg_fail.txt"
  set "NOPYMSG=msg_nopython.txt"
) else (
  rem  Console is gone: keep a log for the admin instead of printing.
  if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>&1
  break > "%~dp0logs\start_log.txt"
)
'''

_RUN = r'''
if not defined PYCMD (
  call :DIE "!NOPYMSG!"
  exit /b 1
)

if not exist "%~dp0open_app.py" (
  call :DIE "!FAILMSG!"
  exit /b 1
)

rem  Pull new scripts from the server when there is a newer version.
rem  It never touches accounts, results, logs or the Python runtime,
rem  and it silently skips when the server is unreachable.
if exist "%~dp0update.py" (
  if defined HIDDEN (
    !PYCMD! "%~dp0update.py" --auto >> "%~dp0logs\start_log.txt" 2>&1
  ) else (
    !PYCMD! "%~dp0update.py" --auto
  )
)

if not defined HIDDEN (
  type "%~dp0msg_running.txt"
  echo.
)

if defined HIDDEN (
  !PYCMD! "%~dp0open_app.py" {APP} >> "%~dp0logs\start_log.txt" 2>&1
) else (
  !PYCMD! "%~dp0open_app.py" {APP}
)
set "RC=!errorlevel!"

if not "!RC!"=="0" (
  call :DIE "!FAILMSG!"
  exit /b !RC!
)

rem  Hidden mode must NOT pause: there is no window to press a key in,
rem  and the process would linger in the background forever.
if not defined HIDDEN (
  type "%~dp0msg_done.txt"
  echo.
  pause
)
endlocal
exit /b 0

:DIE
rem  %1 = message file name. Hidden -> Chinese message box, visible -> print + pause.
if defined HIDDEN (
  wscript "%~dp0_msgbox.vbs" "%~dp0%~1" "Strava"
) else (
  type "%~dp0%~1"
  echo.
  pause
)
exit /b 0
'''

# Start_*.bat: 横幅交给 START 段处理(隐藏模式下要写进日志而不是打印),
# 所以这个头【不打印横幅】。
HEAD_NOBANNER = '''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title %s
cd /d "%%~dp0"

'''


def start_body(banner, app):
    """Start_*.bat 的正文: 先隐藏 -> 再找 Python -> 再启动。

    ★ 顺序很重要:
      1) _HIDE 必须在 FINDPY 【之前】。找 Python 要跑 py/python 探测,
         几百毫秒里那个黑窗口是看得见的 —— 先隐藏才不会有闪烁。
      2) 不能再用公共的 NOPY 段: 它在失败时 `type` + `pause`,
         而隐藏模式下没人能按键, 进程会永远挂在后台。
         这里改用 :DIE, 它按模式自动选"弹框"还是"打印+pause"。
    ★ 用 .replace 而不是 % 格式化: 模板里全是 %~dp0 这种字面量,
      走 % 格式化就必须逐个写成 %%~dp0, 漏一个就整个崩 —— 已经踩过一次。
    """
    return (_HIDE.replace("{BANNER}", banner)
            + FINDPY + "\n"
            + _RUN.replace("{APP}", app))


BATS["Start_AdsPower.bat"] = (
    HEAD_NOBANNER % "Strava - AdsPower" + start_body("msg_ads.txt", "ads"))
BATS["Start_BitBrowser.bat"] = (
    HEAD_NOBANNER % "Strava - BitBrowser" + start_body("msg_bit.txt", "bit"))

# ---------------------------------------------------------------- 启动.bat
# 长文件: 只替换【给人看的文字】, 其余字节原样保留。
# 每条 = (原文, 新文); 新文为 None 表示整块删掉(用中文 msg 覆盖了)。
SETUP_EDITS = [
    # 开头横幅 -> 整份中文说明
    ('''echo ============================================================
echo    Strava Automation  -  Environment Setup
echo.
echo    This file only INSTALLS things.
echo    It will NOT open the app - you open that yourself later.
echo ============================================================
echo.
''', '''type "%~dp0msg_setup.txt"
echo.
'''),
    # 步骤 1
    ('echo [1/4] Looking for a ready-to-use Python ...',
     'echo [1/4] Python'),
    ('echo       Using the Python inside this folder.',
     'echo       OK - using the Python in this folder.'),
    ('''  echo       The Python in this folder is incomplete.
  echo       Removing it and installing a complete one ...''',
     '  echo       Incomplete Python found - reinstalling ...'),
    ('  echo       Found the Python launcher: py -3',
     '  echo       OK - found: py -3'),
    ('    echo       Found python on PATH.',
     '    echo       OK - found: python'),
    ('  echo       It already has everything we need.',
     '  echo       OK - all packages present.'),
    # 步骤 2
    ('''echo [2/4] Installing Python inside this folder
echo       about 26 MB download, no admin rights needed ...''',
     '''echo [2/4] Installing Python (about 26 MB, no admin rights needed) ...'''),
    ('echo       Downloading about 26 MB, please wait ...',
     'echo       Downloading ...'),
    ('  echo       Mirror failed, trying python.org ...',
     '  echo       Mirror failed, trying python.org ...'),
    ('echo       Installing, this takes about a minute ...',
     'echo       Installing ...'),
    ('echo       Python 3.11 is already installed for this user - checking it ...',
     'echo       Python 3.11 already installed - checking it ...'),
    ('  echo       It is missing or incomplete - repairing, about a minute ...',
     '  echo       Repairing ...'),
    # 步骤 3 / 4
    ('echo [3/4] Checking the required packages ...',
     'echo [3/4] Checking packages ...'),
    ('  echo       Every package is already installed.',
     '  echo       OK - nothing to install.'),
    ('echo       Downloading about 55 MB, usually 1 to 3 minutes ...',
     'echo       Downloading packages (about 55 MB, 1-3 min) ...'),
    ('  echo       Mirror failed, trying the default source ...',
     '  echo       Mirror failed, trying default source ...'),
    ('echo [4/4] Verifying ...', 'echo [4/4] Verifying ...'),
]

# 失败块 -> 中文
SETUP_FAILS = [
    ('''  echo.
  echo  [ERROR] Could not download Python.
  echo          Check your internet connection and run this file again.
  echo          Or ask the admin to send you the "_python" folder directly.
  echo.
  pause
  exit /b 1''',
     '''  type "%~dp0msg_setup_fail.txt"
  echo.
  pause
  exit /b 1'''),
    ('''  echo.
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
  exit /b 1''',
     '''  type "%~dp0msg_setup_fail.txt"
  echo.
  pause
  exit /b 1'''),
    ('''  echo.
  echo  [ERROR] Some packages are still missing.
  echo          Run this file again - already downloaded parts are kept.
  echo          If it keeps failing, screenshot this window for the admin.
  echo.
  pause
  exit /b 1''',
     '''  type "%~dp0msg_setup_fail.txt"
  echo.
  pause
  exit /b 1'''),
    ('''  echo.
  echo  [ERROR] This Python has no tkinter, so the window cannot open.
  echo          Delete the "_python" folder and run this file again.
  echo.
  pause
  exit /b 1''',
     '''  type "%~dp0msg_setup_fail.txt"
  echo.
  pause
  exit /b 1'''),
]

# 结尾大段英文 -> 中文
SETUP_TAIL = ('''echo.
echo ============================================================
echo    Environment is READY.
echo ============================================================
echo.
''', '''echo.
type "%~dp0msg_setup_ok.txt"
echo.
''')

SETUP_FINAL = ('''echo    How to use it from now on:
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
''', '')


def apply_edits(name, edits):
    """逐条替换。★ 必须【可重复运行】: 第二次跑时英文原文已经没了,
    如果还当成错误, 就变成"改一次报一次假错", 反而诱导人去乱改。
    判定: 原文找不到, 但新文已经在里面 -> 说明上次已经改过, 正常跳过。"""
    p = PKG / name
    text = p.read_text(encoding="utf-8", errors="replace")
    misses, alreadies = [], []
    for old, new in edits:
        o = old.replace("\r\n", "\n")
        n = new.replace("\r\n", "\n")
        t = text.replace("\r\n", "\n")
        if o not in t:
            # 新文是空串 = 这条是【删除】。删掉的东西没法用"新文在不在"验证,
            # 而"原文不在"本身就说明它已经没了(上次删过, 或本来就没有),
            # 两种都是想要的结果, 不算失败。
            if not n.strip():
                alreadies.append(old.strip().splitlines()[0][:50])
            elif n.strip() in t:
                alreadies.append(old.strip().splitlines()[0][:50])
            else:
                misses.append(old.strip().splitlines()[0][:70])
            continue
        text = t.replace(o, n, 1)
    if alreadies:
        print("     (其中 %d 处上次已改过, 跳过)" % len(alreadies))
    return text, misses


def main():
    bad = []
    for name, text in BATS.items():
        body = text.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            data = body.encode("ascii", "strict")
        except UnicodeEncodeError as e:
            bad.append("%s 有非 ASCII 字符: %s" % (name, e))
            continue
        (PKG / name).write_bytes(data)
        print("  + %-24s %5d B  %3d 行  (整份重写)" % (name, len(data), body.count("\r\n")))

    # 启动.bat: 逐条替换
    text, misses = apply_edits("启动.bat", SETUP_EDITS + SETUP_FAILS
                               + [SETUP_TAIL, SETUP_FINAL])
    if misses:
        bad.append("启动.bat 有 %d 处没匹配上: %s" % (len(misses), misses))
    body = text.replace("\r\n", "\n").replace("\n", "\r\n")
    try:
        data = body.encode("ascii", "strict")
    except UnicodeEncodeError as e:
        bad.append("启动.bat 替换后仍含非 ASCII: %s" % e)
        data = None
    if data:
        (PKG / "启动.bat").write_bytes(data)
        print("  + %-24s %5d B  %3d 行  (逐条替换 %d 处)"
              % ("启动.bat", len(data), body.count("\r\n"),
                 len(SETUP_EDITS + SETUP_FAILS + [SETUP_TAIL, SETUP_FINAL])))

    # 全部 .bat 复查: 纯 ASCII + type 目标存在
    print()
    for f in sorted(PKG.glob("*.bat")):
        b = f.read_bytes()
        non = sum(1 for x in b if x > 127)
        bare = b.count(b"\n") - b.count(b"\r\n")
        tgt_missing = []
        for line in f.read_text(encoding="ascii", errors="replace").splitlines():
            s = line.strip()
            if s.lower().startswith("type "):
                t = s[5:].strip().strip('"').replace("%~dp0", "")
                # ★ 含 % 的是变量(:DIE 里的 "%~dp0%~1"), 运行时才展开,
                #   不是文件名字面量 —— 不能当"缺文件"报。第一版就是这么假报的。
                if "%" in t:
                    continue
                if not (PKG / t).is_file():
                    tgt_missing.append(t)
        flag = "OK " if (non == 0 and bare == 0 and not tgt_missing) else "★  "
        if non or bare or tgt_missing:
            bad.append("%s nonASCII=%d bareLF=%d 缺目标=%s"
                       % (f.name, non, bare, tgt_missing))
        print("  %s %-24s 非ASCII=%d 裸LF=%d 缺目标=%s"
              % (flag, f.name, non, bare, tgt_missing or "无"))

    print()
    if bad:
        print("★★★ 有问题 ★★★")
        for x in bad:
            print("   -", x)
        return 1
    print("★★★ 全部 .bat: 纯 ASCII + CRLF + type 目标齐全 ★★★")
    return 0


if __name__ == "__main__":
    sys.exit(main())
