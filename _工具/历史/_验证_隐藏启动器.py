# -*- coding: utf-8 -*-
"""验证隐藏式启动器。

三件事必须成立:
  1) 隐藏模式下【进程自己能退出】。窗口藏起来之后就没人能按 pause,
     只要还留着 pause, cmd 就会永远挂在后台 —— 这是隐藏方案最大的坑。
  2) 隐藏模式下要留下 logs\\start_log.txt, 否则出错时管理员无从下手。
  3) 带 show 参数时要恢复"看得见 + 横幅"的老行为(排查用)。

★ 在临时副本里测, 不动 _分发给同事/。
★ open_app.py 换成空壳(否则真弹 Tk 界面); update.py 挪走(否则真去联网更新)。
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

PKG = Path(sys.argv[1] if len(sys.argv) > 1 else
           r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")
TMP = Path(tempfile.mkdtemp(prefix="_hidetest_"))
for f in PKG.iterdir():
    if f.is_file():
        shutil.copy2(f, TMP / f.name)
for n in ("update.py", "fix_update.py"):
    if (TMP / n).exists():
        (TMP / n).rename(TMP / (n + ".off"))
# 空壳 GUI: 打印一行然后退出 0
(TMP / "open_app.py").write_text(
    "import sys\nprint('stub gui ran')\nsys.exit(0)\n", encoding="ascii")

ok = True

# ---------------- 1+2. 隐藏模式 ----------------
print("1+2) 隐藏模式: 能否自己退出 + 是否留日志")
bat = TMP / "Start_AdsPower.bat"
p = subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(TMP),
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NEW_CONSOLE)
t0 = time.time()
try:
    rc = p.wait(timeout=75)
    dt = time.time() - t0
    print(f"   进程自己退出了: 是   返回码={rc}  用了 {dt:.1f}s")
    if rc != 0:
        ok = False
        print("   ★ 返回码非 0")
except subprocess.TimeoutExpired:
    ok = False
    print("   ★★ 75 秒还没退出 —— 很可能卡在 pause 上(隐藏模式绝不能 pause)")
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)

log = TMP / "logs" / "start_log.txt"
print("   logs\\start_log.txt 存在:", log.is_file())
if log.is_file():
    body = log.read_text(encoding="utf-8", errors="replace")
    print("   日志里有 'stub gui ran':", "stub gui ran" in body)
    if "stub gui ran" not in body:
        ok = False
        print("   日志内容:", body[:200])
else:
    ok = False

# ---------------- 3. show 模式 ----------------
print()
print("3) show 模式: 恢复看得见 + 中文横幅")
r = subprocess.run(["cmd", "/c", str(bat), "show"], cwd=str(TMP),
                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, timeout=90)
out = r.stdout.decode("utf-8", errors="replace")
has_banner = "AdsPower 版" in out
has_stub = "stub gui ran" in out
print("   返回码:", r.returncode)
print("   显示中文横幅:", has_banner)
print("   跑了 GUI:", has_stub)
# show 模式不该写启动日志(那是隐藏模式专用的)
print("   (show 模式走的是打印, 不是日志)")
if not (has_banner and has_stub):
    ok = False
    print("   输出前 400 字:", out[:400])

shutil.rmtree(TMP, ignore_errors=True)
print()
print("★★★ 全部通过 ★★★" if ok else "★★★ 有失败项 ★★★")
sys.exit(0 if ok else 1)
