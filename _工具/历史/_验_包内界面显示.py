# -*- coding: utf-8 -*-
"""直接验: 解压出来的包里, 界面「每段≥」到底显示什么。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

zips = sorted((pathlib.Path.home() / "Desktop").glob("发给同事_脚本包_*.zip"))
ZIP = zips[-1]
print("验的是: %s" % ZIP.name)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="v3_"))
with zipfile.ZipFile(ZIP) as z:
    z.extractall(tmp)
base = next(d for d in tmp.iterdir() if d.is_dir())
cfg = json.loads((base / "config.json").read_text(encoding="utf-8"))
print("  包里 config.json 的 min_athletes = %r" % cfg.get("min_athletes"))
print("  包里 config.json 的 _policy_rev  = %r" % cfg.get("_policy_rev"))

CODE = r'''
import importlib.util, pathlib, sys, json
gui = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec); sys.modules["gm"] = m
spec.loader.exec_module(m)
print("MODULE ROOT =", m.ROOT)
app = m.App(); app.withdraw(); app.update()
print("RESULT=" + json.dumps({"min_ath": app._min_ath,
                              "shown": app.var_minath.get(),
                              "region": app.var_region.get()},
                             ensure_ascii=False))
app.destroy()
'''
pf = tmp / "_p.py"
pf.write_text(CODE, encoding="utf-8")
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
r = subprocess.run([sys.executable, str(pf), str(base / "_gui_ads.py")],
                   cwd=str(base), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=240, env=env)
print()
print("  --- 直接跑的结果 ---")
for l in (r.stdout or "").splitlines():
    print("    " + l.strip())
if r.returncode:
    print("    ★ stderr:")
    print((r.stderr or "")[-400:])
shutil.rmtree(tmp, ignore_errors=True)
