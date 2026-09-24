# -*- coding: utf-8 -*-
"""死磕: 界面「每段≥」为什么显示 5000 而不是配置里的 2000。

不猜了 —— 直接把 __init__ 跑一遍, 在每一步打印 _min_ath 和 _rc 的值,
看它是在哪一步被改成 5000 的。
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
zips = sorted((pathlib.Path.home() / "Desktop").glob("发给同事_脚本包_*.zip"))
ZIP = zips[-1]
tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbg_"))
with __import__("zipfile").ZipFile(ZIP) as z:
    z.extractall(tmp)
base = next(d for d in tmp.iterdir() if d.is_dir())

PROBE = r'''
import importlib.util, json, pathlib, sys, os

gui = pathlib.Path(sys.argv[1]); here = gui.parent
sys.path.insert(0, str(here))

# ---- 手工复刻 __init__ 里读配置那一段, 每步都打印 ----
ROOT = here
print("ROOT =", ROOT)
_rc = {}
_c = None
for cand in (ROOT / "config.json", ROOT / "配置" / "config.json",
             ROOT.parent / "配置" / "config.json", ROOT.parent / "config.json"):
    try:
        if cand.exists():
            _c = cand
            _rc = json.loads(cand.read_text(encoding="utf-8"))
            break
    except Exception as e:
        print("  读 %s 失败: %s" % (cand, e))
print("用了配置:", _c)
print("  里面的 min_athletes =", repr(_rc.get("min_athletes")))
print("  里面的 _policy_rev  =", repr(_rc.get("_policy_rev")))

_min_ath = int(_rc.get("min_athletes") or 5000)
print("  初始化后 _min_ath =", _min_ath)

# ---- 看界面模块里的 _ADMIN_POLICY_REV 是多少 ----
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec); sys.modules["gm"] = m
spec.loader.exec_module(m)
print("  界面模块 _ADMIN_POLICY_REV =", getattr(m, "_ADMIN_POLICY_REV", "?"))
print("  界面模块 _ADMIN_POLICY =", json.dumps(
    getattr(m, "_ADMIN_POLICY", {}), ensure_ascii=False)[:200])
print("  MIN_ATH_CHOICES[0] =", m.MIN_ATH_CHOICES[0])
print("  _label_of(2000) =", m._label_of(m.MIN_ATH_CHOICES, 2000))

# ---- 真起界面, 看它最终显示什么、以及 _min_ath 变成什么 ----
app = m.App(); app.withdraw(); app.update()
print("  起完之后 app._min_ath =", app._min_ath)
print("  var_minath   =", repr(app.var_minath.get()))
# 再读一次磁盘上的 config(看界面有没有把它改写)
_after = json.loads(_c.read_text(encoding="utf-8")) if _c else {}
print("  运行后磁盘 min_athletes =", repr(_after.get("min_athletes")))
print("  运行后磁盘 _policy_rev  =", repr(_after.get("_policy_rev")))
app.destroy()
'''
pf = tmp / "_p.py"
pf.write_text(PROBE, encoding="utf-8")
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
r = subprocess.run([sys.executable, str(pf), str(base / "_gui_ads.py")],
                   cwd=str(base), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=240, env=env)
print("=" * 78)
print("运行时真相")
print("=" * 78)
for line in (r.stdout or "").splitlines():
    print("  " + line)
if r.returncode != 0:
    print("  ★ 出错:")
    print((r.stderr or "")[-800:])
shutil.rmtree(tmp, ignore_errors=True)
