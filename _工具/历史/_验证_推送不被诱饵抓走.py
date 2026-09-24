# -*- coding: utf-8 -*-
"""验证: 桌面多出别的 .py 时, 推送更新.bat 仍然只跑推送工具。

红(改之前): for %%F in (*.py) 取【最后一个】-> 放个 zzz_decoy.py 就会被抓去跑
绿(改之后): 用 findstr 找内容含 SYNC_MAP 的那个 -> 免疫

★ 用完必删 decoy, 在 finally 里保证。
"""
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

DESK = Path(r"C:\Users\1\Desktop")
DECOY = DESK / "zzz_decoy.py"          # 名字排最后 -> 旧逻辑必然选中它
BAT = DESK / "推送更新.bat"

print("=" * 74)
print(f"放一个诱饵: {DECOY.name}  (内容里没有 SYNC_MAP)")
print(f"旧逻辑 for %%F in (*.py) 取最后一个 -> 会选中它")
print("=" * 74)

try:
    DECOY.write_text("# decoy, no marker here\nprint('I am the decoy')\n",
                     encoding="utf-8")
    r = subprocess.run(["cmd", "/c", str(BAT), "check"], cwd=str(DESK),
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=300)
    out = r.stdout.decode("utf-8", errors="replace")
    script_line = next((l for l in out.splitlines() if l.strip().startswith("Script")), "")
    note_line = next((l for l in out.splitlines() if "[note]" in l), "")
    print("实际输出:")
    print("   ", script_line.strip())
    print("   ", note_line.strip())
    print()
    if "decoy" in script_line:
        print("★★★ 红: 真的被诱饵抓走了 —— 选了 decoy ★★★")
        rc = 1
    elif "一键推送更新.py" in script_line:
        print("★★★ 绿: 仍然选中推送工具, 没被诱饵影响 ★★★")
        rc = 0
    else:
        print("★ 没识别出选了哪个")
        rc = 1
    if "SYNC_MAP" not in out:
        print("   (提示: 这次运行似乎没走到推送工具内部)")
finally:
    DECOY.unlink(missing_ok=True)
    print()
    print("诱饵已删除:", not DECOY.exists())

sys.exit(rc)
