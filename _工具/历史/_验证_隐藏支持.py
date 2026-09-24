# -*- coding: utf-8 -*-
"""验证隐藏支持的两个小工具。

1) _msgbox.vbs 的关键是【能不能按 UTF-8 读出中文】—— 弹框本身是阻塞的,
   没法自动点确定, 所以把 Popup 换成写文件来验证读取那一段;
   再单独确认真正的 _msgbox.vbs 能起来(起一个, 2 秒后杀掉)。
2) _hide.ps1 能不能成功隐藏当前控制台(返回码 0)。
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

PKG = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")
TMP = Path(tempfile.mkdtemp(prefix="_hidtest_"))
ok = True

# ---------------- 1. VBS 能否按 UTF-8 读出中文 ----------------
src = (PKG / "_msgbox.vbs").read_text(encoding="ascii")
probe = src.replace(
    "sh.Popup text, 0, title, 4160",
    'Dim o: Set o = fso.CreateTextFile(WScript.Arguments(1), True, True)\n'
    "o.Write text\n"
    "o.Close")
(TMP / "probe.vbs").write_text(probe, encoding="ascii")
shutil.copy2(PKG / "msg_hidden_fail.txt", TMP / "m.txt")
outfile = TMP / "out.txt"

r = subprocess.run(["cscript", "//nologo", str(TMP / "probe.vbs"),
                    str(TMP / "m.txt"), str(outfile)],
                   capture_output=True, timeout=60)
print("1) VBS 读 UTF-8 中文")
print("   cscript 返回码:", r.returncode)
if r.stdout:
    print("   输出:", r.stdout.decode("utf-8", "replace").strip()[:200])
if r.stderr:
    print("   错误:", r.stderr.decode("utf-8", "replace").strip()[:200])
if outfile.is_file():
    # ★ fso.CreateTextFile(..., True) 的第三个参数 True = Unicode(UTF-16LE),
    #   所以要按 utf-16 读回来; 按 utf-8 读会得到一片乱码(第一次就是这么误判的)。
    got = outfile.read_text(encoding="utf-16", errors="replace")
    want = "采集界面没能启动"
    hit = want in got
    print("   读出的前 40 字:", got.strip().replace("\r\n", " / ")[:40])
    print("   含关键词 %r: %s" % (want, hit))
    if not hit:
        ok = False
else:
    print("   ★ 没能生成输出文件")
    ok = False

# ---------------- 2. 真正的 _msgbox.vbs 能不能起来 ----------------
print()
print("2) 真 _msgbox.vbs 能否启动(弹出后 2 秒杀掉)")
p = subprocess.Popen(["wscript", str(PKG / "_msgbox.vbs"),
                      str(PKG / "msg_hidden_fail.txt"), "Strava"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
alive = p.poll() is None
print("   2 秒后仍在运行(说明弹框出来了):", alive)
if alive:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)
else:
    print("   ★ 立刻退出了, 返回码 =", p.returncode, " (1/2 表示参数或文件有问题)")
    ok = False

# ---------------- 3. _hide.ps1 返回码 ----------------
print()
print("3) _hide.ps1 隐藏当前控制台")
# ★ 必须把 _hide.ps1 拷进临时目录, 用【相对名】调用。
#   直接把带中文的项目路径写进 .bat 会变成非 ASCII 字面量 —— 那正是
#   我们反复强调会让 cmd 解析崩的东西(第一次写这个测试就踩了)。
shutil.copy2(PKG / "_hide.ps1", TMP / "_hide.ps1")
bat = TMP / "t.bat"
bat.write_text(
    "@echo off\r\n"
    'cd /d "%~dp0"\r\n'
    'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_hide.ps1" >rc.txt 2>&1\r\n'
    "echo RC=%errorlevel% >> rc.txt\r\n",
    encoding="ascii")
pp = subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(TMP),
                      stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      # ★ 必须给子进程一个【真的控制台窗口】, 否则
                      #   GetConsoleWindow() 返回 0 -> _hide.ps1 返回 3。
                      #   这不是隐藏失败, 是测试环境没给窗口:
                      #   同事双击 .bat 时 cmd 一定有自己的控制台。
                      creationflags=subprocess.CREATE_NEW_CONSOLE)
pp.wait(timeout=60)
rcf = TMP / "rc.txt"
txt = rcf.read_text(encoding="utf-8", errors="replace") if rcf.is_file() else ""
print("   ", txt.strip().replace("\r\n", " | ") or "(无输出)")
if "RC=0" not in txt:
    print("   ★ 隐藏失败(期望 RC=0)")
    ok = False

shutil.rmtree(TMP, ignore_errors=True)
print()
print("★★★ 全部通过 ★★★" if ok else "★★★ 有失败项 ★★★")
sys.exit(0 if ok else 1)
