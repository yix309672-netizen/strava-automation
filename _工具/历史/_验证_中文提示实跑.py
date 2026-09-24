# -*- coding: utf-8 -*-
"""实跑每个 .bat, 确认中文真的显示出来。

★ 在【临时副本】里跑, 不动 _分发给同事/ 原件。
★ update.py / fix_update.py 改名 -> 断掉自动更新,
   否则 Start_*.bat 会从服务器拉【旧版】把刚改好的中文 bat 覆盖掉。
★ open_app.py 换成空壳 -> 否则 Start_*.bat 会真的弹出 Tk 界面并一直挂着。

★★ 两个踩过的坑(上一版就是这么挂死的) ★★
   1) capture_output=True 用管道收输出: 超时只杀掉 cmd, 它派生的 python
      还攥着管道写端不放 -> communicate() 永远等不到 EOF -> 整个测试挂死。
      改成【输出重定向到文件】, 没有管道就没有 EOF 可等。
   2) 超时必须连【整棵进程树】一起杀 -> taskkill /F /T。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else
           r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")
TMP = Path(tempfile.mkdtemp(prefix="_battest_"))
for f in SRC.iterdir():
    if f.is_file():
        shutil.copy2(f, TMP / f.name)
for n in ("update.py", "fix_update.py"):
    if (TMP / n).exists():
        (TMP / n).rename(TMP / (n + ".disabled"))
(TMP / "open_app.py").write_text("import sys\nsys.exit(0)\n", encoding="ascii")

print(f"临时副本: {TMP}")
print("=" * 74)

EXPECT = {
    "启动.bat": ["环境安装", "装完之后怎么用"],
    "Start_AdsPower.bat": ["AdsPower 版", "黑窗口"],
    "Start_BitBrowser.bat": ["比特浏览器版", "黑窗口"],
    "更新.bat": ["更新脚本到最新版", "绝对不会"],
    "修复更新.bat": ["修复更新", "只在一种情况下"],
    "Test_Server.bat": ["服务器连接测试", "共享去重服务器"],
    "一键检查.bat": ["一键检查", "桌面"],
}
PER_BAT = 45
ok_all = True

for name, keys in EXPECT.items():
    bat = TMP / name
    if not bat.is_file():
        print(f"★ {name} 不存在")
        ok_all = False
        continue
    log = TMP / "_out.txt"
    log.write_bytes(b"")
    with open(log, "wb") as fh:
        p = subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(TMP),
                             stdin=subprocess.DEVNULL,
                             stdout=fh, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=PER_BAT)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True)
            try:
                p.wait(timeout=10)
            except Exception:
                pass
    raw = log.read_bytes()
    # 控制台是 UTF-8(chcp 65001) -> 按 UTF-8 解
    text = raw.decode("utf-8", errors="replace")

    hit = [k for k in keys if k in text]
    good = len(hit) == len(keys) and "is not recognized as an internal" not in text
    if not good:
        ok_all = False
    print(f"{'OK ' if good else '★  '} {name:22s} 中文命中 {len(hit)}/{len(keys)}")
    if not good:
        miss = [k for k in keys if k not in text]
        print(f"     缺: {miss}")
        print("     实际输出(前 500 字):")
        print("       " + text[:500].replace("\n", "\n       "))
        if "is not recognized as an internal" in text:
            print("     ★★ cmd 解析错误 —— bat 里混进了非 ASCII!")
    print("-" * 74)

shutil.rmtree(TMP, ignore_errors=True)
print("★ 全部通过" if ok_all else "★ 有失败项, 见上")
sys.exit(0 if ok_all else 1)
