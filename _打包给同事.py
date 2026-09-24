# -*- coding: utf-8 -*-
"""打包一个【自包含移交包】发给同事。

和以前的区别:
  · 以前靠"自动更新"下发 —— 同事那边链断了就一动不动
  · 这次是【完整包】: 解压覆盖就能用, 不依赖更新链路
  · 额外塞一个【一键检查.bat】: 同事双击一次, 结果写到桌面, 发回来即可

内容 = 分发包的全部文件 + 检查工具。
★ 体检: 不能含邮箱、不能含真实密钥(与发布流程同一套标准)。
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent

# ★★ 2026-09-20 修(实测复现): 控制台/管道是 GBK(cp936) 时, 下面这些
#   print("... ✓") 会抛 UnicodeEncodeError。而这个异常发生在【压缩之前】,
#   所以现象是: 打印完"体检"就崩, 桌面上【根本没有 zip】, 报错还很容易被忽略。
#   引擎早就有同款兜底(reconfigure errors="replace"), 打包脚本漏了。
#   注意: 重定向输出时 Python 用系统 ANSI 代码页而不是控制台代码页,
#   所以这不是"只有老 cmd 才有"的问题 —— 管道/重定向一样会中。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

PKG = ROOT / "_分发给同事"

# ★★ 2026-09-20 用户要求:「你不要更新那么多同事包可以吗。不能分类整理好吗?」★★
#   以前每打一次包就在【桌面】上留一个 "发给同事_脚本包_<时间戳>.zip" 和一个
#   同名文件夹。今晚反复改、反复打包, 一晚上堆了 12 个(6 zip + 6 目录)。
#   现在:
#     · 统一放进 桌面\Strava发布包\ , 桌面不再散落
#     · 名字固定叫 发给同事_脚本包_最新.zip —— 永远只有【一个】, 直接覆盖
#     · 打包用的中间目录放系统临时目录, 用完就删, 不落在桌面上
#   想留历史版本的话, 自己把那个 zip 复制改名即可(发布包本身可随时重打)。
DESK = pathlib.Path.home() / "Desktop"
OUTROOT = DESK / "Strava发布包"
ZIP = OUTROOT / "发给同事_脚本包_最新.zip"
OUTDIR = pathlib.Path(tempfile.gettempdir()) / "strava_pkg_build"

SECRET_RE = re.compile(r"(adspower_key|bitbrowser_key)\"?\s*[:=]\s*\"?([A-Za-z0-9_\-]{16,})")
MAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+")
PLACEHOLDER = ("KEEP", "TEST", "FAKE", "XXX", "EXAMPLE", "COLLEAGUE",
               "PLACEHOLDER", "DUMMY", "YOUR_", "CHANGEME", "MINE")

# 一个 .bat: 同事双击就生成检查结果
# ★ 必须【纯 ASCII】: .bat 里写中文会让 cmd 按字节偏移回读时错位,
#   报 'elayedExpansion' is not recognized。中文放 msg_check.txt, 用 type 打。
CHECK_BAT = r'''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Strava - Check
cd /d "%~dp0"

type "%~dp0msg_check.txt"
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

echo  Running check, please wait ...
echo.
!PYCMD! "%~dp0check.py"
echo.
echo ============================================================
echo    A file was created on your Desktop:  CheckResult_<machine>_<time>.txt
echo    Please send that file to the admin.
echo ============================================================
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
'''

README = """========================================================
 Strava 脚本包 —— 使用说明（同事请照这个做）
========================================================

一、怎么安装
--------------------------------------------------------
  1) 把整个文件夹解压到【桌面】（或任何你喜欢的位置，别放中文路径以外的地方）
  2) 如果你之前已经有脚本文件夹，把这里的文件【全部覆盖】过去
     （你的账号、成果、浏览器 key 都在 config.json 里，覆盖不会丢）

二、怎么用
--------------------------------------------------------
  双击  启动.bat        ← 正常干活就用这个
  （或者 Start_AdsPower.bat / Start_BitBrowser.bat）

三、出问题了怎么办
--------------------------------------------------------
  ★ 双击  一键检查.bat

  它会自己检查:
     · 脚本是不是最新版
     · 成果文档写到哪了
     · 为什么没采到人
  跑完会在【桌面】生成一个文件:
     check_result_<你的机器名>_<时间>.txt
  把这个文件发回给管理员即可。

四、你采到的链接存在哪
--------------------------------------------------------
  就在【这个文件夹里】，文件名是:

      链接-日期.txt         例如  链接-20260920.txt

  · 每天的链接都写进同一个文件
  · 里面只有链接，一行一个
  · 文件是【追加】的，当天多跑几次也在同一个文件里
  · 不是写在什么子文件夹里 —— 就在脚本所在的这个文件夹

五、注意
--------------------------------------------------------
  · 让脚本跑完再关！中途关掉当前批次就不保存了
  · 界面上那行「采集地区 / 每段≥ / 性别 / 时间范围 / 年纪」都能点开选
"""


def main():
    print("=" * 78)
    print("打包给同事的脚本包")
    print("=" * 78)

    if not PKG.is_dir():
        print("★ 找不到分发包目录 %s" % PKG)
        return 1

    if OUTDIR.exists():
        shutil.rmtree(OUTDIR)
    OUTDIR.mkdir(parents=True)
    OUTROOT.mkdir(parents=True, exist_ok=True)

    # ---- 1. 复制分发包全部文件 ----
    n = 0
    for f in sorted(PKG.iterdir()):
        if f.is_file() and not f.name.startswith("._pkg_version"):
            shutil.copy2(f, OUTDIR / f.name)
            n += 1
    print("  复制分发包文件: %d 个" % n)

    # ---- 2. 放检查工具 ----
    chk = ROOT / "检查.py"
    if chk.is_file():
        shutil.copy2(chk, OUTDIR / "check.py")
        print("  + check.py（一键检查脚本）")
    # 一键检查.bat
    bat = OUTDIR / "一键检查.bat"
    bat.write_bytes(CHECK_BAT.replace("\r\n", "\n")
                    .replace("\n", "\r\n").encode("ascii"))
    print("  + 一键检查.bat")

    # ---- 3. 修 bug 的兜底工具也带上 ----
    for name in ("fix_update.py",):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, OUTDIR / name)

    # ---- 4. 说明 ----
    (OUTDIR / "使用说明_先看这个.txt").write_text(README, encoding="utf-8")
    print("  + 使用说明_先看这个.txt")

    # ---- 5. 体检 ----
    print()
    print("=" * 78)
    print("体检")
    print("=" * 78)
    bad = []
    TXT = (".py", ".json", ".txt", ".bat", ".md")
    for p in OUTDIR.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TXT:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        is_lic = p.name.lower().startswith("license")
        for m in SECRET_RE.finditer(t):
            v = m.group(2) or ""
            if len(v) >= 16 and not any(h in v.upper() for h in PLACEHOLDER):
                bad.append("密钥 %s: %s" % (p.name, m.group(1)))
        if not is_lic:
            for m in MAIL_RE.finditer(t):
                if not any(a in m.group(0) for a in ("example.com", "test.com")):
                    bad.append("邮箱 %s: %s" % (p.name, m.group(0)))
    if bad:
        print("  ★ 发现问题 %d 处:" % len(bad))
        for b in bad[:15]:
            print("     " + b)
    else:
        print("  干净: 无真实密钥、无邮箱 ✓")

    # 关键文件齐不齐
    NEED = ["启动.bat", "strava_ads.py", "strava_bit.py", "_gui_ads.py",
            "_gui_bit.py", "claim_client.py", "update.py", "config.json",
            "geo_cities.py", "check.py", "一键检查.bat",
            # ★ 名字库: 引擎 `from name_bank import NAMES` 读它。
            #   缺了会【静默】退回内置 50 个名字(不报错), 从包里就能挡掉。
            "name_bank.py",
            # ★ 2026-09-24 版本号唯一真源: 界面标题栏显示它。
            #   缺了会【静默】兜底成 "v?"(标题栏空白), 所以从包里就挡掉。
            "app_version.py",
            # ★ 中文提示文件: .bat 用 type 引用它们, 少一个同事就看到空白
            "msg_setup.txt", "msg_ads.txt", "msg_bit.txt", "msg_update.txt",
            "msg_repair.txt", "msg_test.txt", "msg_check.txt",
            "msg_nopython.txt", "msg_running.txt", "msg_done.txt",
            "msg_fail.txt", "msg_setup_ok.txt", "msg_setup_fail.txt",
            # ★ 隐藏窗口用的两个小工具 + 隐藏模式专用文案
            #   少一个: Start_*.bat 藏不掉窗口, 或者出错时弹不出中文提示
            "_hide.ps1", "_msgbox.vbs",
            "msg_hidden_fail.txt", "msg_hidden_nopython.txt"]
    missing = [x for x in NEED if not (OUTDIR / x).is_file()]
    print("  必需文件: %s" % ("齐全 ✓" if not missing else "★ 缺 %s" % missing))

    # config.json 的 key 必须是空的(不能把管理员的 key 发出去)
    try:
        c = json.loads((OUTDIR / "config.json").read_text(encoding="utf-8"))
        k = str(c.get("adspower_key") or "")
        print("  config.json 里 adspower_key: %s"
              % ("已清空 ✓" if not k else "★ 还有值(长度%d)!" % len(k)))
        print("  采集口径: 地区=%s 每段>=%s 时间=%s 年龄=%s"
              % (c.get("collect_regions"), c.get("min_athletes"),
                 c.get("collect_date_range"), c.get("collect_age_groups")))
    except Exception as e:
        print("  ★ config.json 读不了: %s" % str(e)[:60])

    # ---- 6. 压缩 ----
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUTDIR.rglob("*")):
            if p.is_file():
                z.write(p, pathlib.Path(OUTDIR.name) / p.relative_to(OUTDIR))
    print()
    print("=" * 78)
    print("✓ 打包完成")
    print("  压缩包: %s  (%.0f KB)" % (ZIP, ZIP.stat().st_size / 1024))
    tot = sum(1 for p in OUTDIR.rglob("*") if p.is_file())
    print("  共 %d 个文件" % tot)
    # ★ 中间目录在系统临时目录里, 打完就删掉 —— 不给桌面留垃圾
    shutil.rmtree(OUTDIR, ignore_errors=True)
    print("  (这份永远叫「最新」, 直接覆盖上一份; 想留旧版自己复制改名)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
