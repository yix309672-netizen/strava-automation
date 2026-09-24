# -*- coding: utf-8 -*-
r"""
干净机器实测（真的把界面跑起来）。

覆盖：
  A. 全新机器（没有 Python）
  B. 已有旧版残缺 _python（embeddable，无 tkinter）-> 应自动替换
  C. 真正启动界面 _gui_bit.py 并确认窗口存活
  D. 通过 Start_BitBrowser.bat 启动（同事的操作路径）

注意：实际使用的 Python 可能在 _python\ 里，也可能是启动.bat 复用的
系统已装 Python（此时路径记在 python_path.txt）。
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
PKG = WS / "_分发给同事"
BASE = Path(r"C:\Users\1\Desktop\_测tk")
OLDPY = Path(r"C:\Users\1\Desktop\_tkcheck\x")
RESTRICTED = (r"C:\Windows\System32;C:\Windows;"
              r"C:\Windows\System32\Wbem;"
              r"C:\Windows\System32\WindowsPowerShell\v1.0")


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


def effective_python(d):
    p = d / "_python" / "python.exe"
    if p.exists():
        return p, "包内 _python"
    f = d / "python_path.txt"
    if f.exists():
        cand = Path(f.read_text(encoding="utf-8", errors="replace").strip())
        if cand.exists():
            return cand, "复用的系统 Python (python_path.txt)"
    return None, "无"


BASE.mkdir(parents=True, exist_ok=True)
PROBE = BASE / "_probe.ps1"
KILL = BASE / "_kill.ps1"
PROBE.write_text(
    '$n = @(Get-CimInstance Win32_Process -Filter "Name like \'%python%\'" | '
    'Where-Object { $_.CommandLine -like \'*_gui_*\' }).Count\n'
    'Write-Output $n\n', encoding="utf-8")
KILL.write_text(
    'Get-CimInstance Win32_Process -Filter "Name like \'%python%\'" | '
    'Where-Object { $_.CommandLine -like \'*_gui_*\' } | '
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force '
    '-ErrorAction SilentlyContinue }\n', encoding="utf-8")


def kill_gui():
    """用 .ps1 文件调用，避免 powershell -Command 的嵌套引号被吃掉"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(KILL)], capture_output=True)


def gui_count():
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy",
                        "Bypass", "-File", str(PROBE)],
                       capture_output=True, text=True, errors="replace")
    try:
        return int((r.stdout or "0").strip().splitlines()[-1] or 0)
    except (ValueError, IndexError):
        return 0


def make_tree(name, seed_old=False):
    d = BASE / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for f in PKG.iterdir():
        if f.is_file():
            shutil.copy2(f, d / f.name)
    if seed_old:
        shutil.copytree(OLDPY, d / "_python")
    return d


def run_setup(d):
    env = dict(os.environ)
    env["PATH"] = RESTRICTED
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    t0 = time.time()
    r = subprocess.run(["cmd", "/c", str(d / "启动.bat")],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(d), env=env,
                       timeout=2400)
    return r, time.time() - t0


def check_python(py, d, label):
    """返回 True/False，顺带打印"""
    good = True
    tests = [
        ("import tkinter", "import tkinter;print('tkinter',tkinter.TkVersion)"),
        ("真建窗口再销毁", "import tkinter;r=tkinter.Tk();r.withdraw();"
                          "print('Tk OK');r.destroy()"),
        ("4 个依赖", "import playwright,requests,numpy,PIL;print('deps OK')"),
    ]
    for name, code in tests:
        rr = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=str(d),
                            timeout=180)
        out = ((rr.stdout or "") + (rr.stderr or "")).strip()
        ok1 = rr.returncode == 0
        good &= ok1
        log("  %s %-16s %s" % ("OK  " if ok1 else "FAIL", name,
                               out.splitlines()[-1][:70] if out else ""))
    return good


ok = True
BASE.mkdir(exist_ok=True)
kill_gui()

for scen, seed, desc in (("A", False, "全新机器（没有 Python）"),
                         ("B", True, "已有旧版残缺 _python（无 tkinter）")):
    log("")
    log("=" * 64)
    log("场景 %s：%s" % (scen, desc))
    log("=" * 64)
    d = make_tree(scen, seed)
    if seed:
        rr = subprocess.run([str(d / "_python" / "python.exe"), "-c",
                             "import tkinter"], capture_output=True)
        log("  预置旧 _python 能 import tkinter: %s (期望 False)"
            % (rr.returncode == 0))

    r, el = run_setup(d)
    out = (r.stdout or "") + (r.stderr or "")
    log("  启动.bat 退出码=%d  耗时=%.0f 秒" % (r.returncode, el))
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(("[1/4]", "[2/4]", "[3/4]", "[4/4]")) or \
           any(k in s for k in ("incomplete", "reusing", "Missing",
                                "already has", "READY", "ERROR", "python_path")):
            log("   | " + s[:96])
    if "not recognized as an internal" in out:
        ok = False
        log("   ★ FAIL .bat 里有命令找不到（引号/路径拼接错误）")

    if r.returncode != 0 or "Environment is READY" not in out:
        ok = False
        log("   ★ FAIL 环境没装好")
        continue

    py, how = effective_python(d)
    log("  实际使用的 Python: %s  [%s]" % (py, how))
    if not py:
        ok = False
        log("   ★ FAIL 找不到可用的 Python")
        continue

    ok &= check_python(py, d, scen)

    # ---- 真正启动界面 ----
    log("")
    log("  ★ 直接启动 _gui_bit.py，看窗口能不能活下来 ...")
    p = subprocess.Popen([str(py), str(d / "_gui_bit.py")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=str(d), text=True, encoding="utf-8",
                         errors="replace")
    for _ in range(20):
        time.sleep(1)
        if p.poll() is not None:
            break
    if p.poll() is None:
        log("  OK  存活 20 秒 —— 窗口成功打开")
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
    else:
        ok = False
        log("  ★ FAIL 自己退出了 rc=%s" % p.returncode)
        log("     %s" % (p.stdout.read() or "")[:400])

    # ---- 走 Start_BitBrowser.bat ----
    log("")
    log("  ★ 走 Start_BitBrowser.bat（同事的操作路径）...")
    kill_gui()
    env = dict(os.environ)
    env["PATH"] = RESTRICTED
    b = subprocess.Popen(["cmd", "/c", str(d / "Start_BitBrowser.bat")],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, cwd=str(d), env=env,
                         text=True, encoding="utf-8", errors="replace")
    n = 0
    for _ in range(30):
        time.sleep(1)
        n = gui_count()
        if n:
            break
    if n:
        log("  OK  拉起了界面（%d 个界面进程）" % n)
    else:
        ok = False
        log("  ★ FAIL 没拉起界面")
        try:
            b.terminate()
            o = b.communicate(timeout=10)[0]
        except Exception:
            o = ""
        log("     bat 输出: %s" % (o or "")[:800])
    kill_gui()
    try:
        b.terminate()
    except Exception:
        pass

log("")
log("=" * 64)
log("  实测结论: %s" % ("全部通过 —— 界面真的能打开" if ok else "★ 有失败项"))
log("=" * 64)
sys.exit(0 if ok else 1)
