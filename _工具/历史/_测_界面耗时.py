# -*- coding: utf-8 -*-
"""量界面本身的耗时: 启动、填 200 行、单行更新 —— 分别测 有主题 / 无主题。

不猜, 直接跑。若 sv-ttk 明显更慢, 就把主题改成"可选、默认关"。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

PROBE = r'''
import importlib.util, json, pathlib, sys, time, shutil
tmp = pathlib.Path(sys.argv[1]); src = pathlib.Path(sys.argv[2])
use_sv = sys.argv[3] == "1"
gui = tmp / "gui.py"
shutil.copy2(src / "界面" / "ADS自动化.py", gui)
if use_sv:
    shutil.copytree(src / "sv_ttk", tmp / "sv_ttk", dirs_exist_ok=True)
(tmp / "config.json").write_text(json.dumps({"ui_theme": "light"}),
                                 encoding="utf-8")
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec); sys.modules["gm"] = m
spec.loader.exec_module(m)

out = {}
t0 = time.time()
app = m.App(); app.update()
out["startup_ms"] = (time.time() - t0) * 1000
out["theme"] = getattr(app, "_ui_theme", "?")
F = list(m.FIELDS)
rows = []
for i in range(200):
    d = {k: "" for k in F}
    d["seq"] = i + 1; d["win"] = str(i + 1)
    d["login"] = "是" if i % 2 else "否"
    d["email"] = "u%d@mail.com" % i
    d["note"] = "账号：u%d@mail.com" % i
    d["name"] = "Name %d" % i; d["city"] = "Chicago, Illinois"
    d["acts"] = str(50 + i); d["prem"] = "是"
    d["priv"] = "小组True/地图True/时间True"
    rows.append(tuple(d[k] for k in F))

t0 = time.time(); app._fill(rows); app.update()
out["fill200_ms"] = (time.time() - t0) * 1000

# 扫描回填走的就是 _set(每行一次)
t0 = time.time()
for i in range(50):
    app._set(i + 1, "login", "否"); app.update()
out["set50_ms"] = (time.time() - t0) * 1000
app.destroy()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 78)
    print("界面耗时对比: 带 sv-ttk 主题 vs 不带")
    print("=" * 78)
    print("  %-14s %-12s %-12s %-12s %s"
          % ("配置", "启动(ms)", "填200行(ms)", "更新50行(ms)", "主题"))
    print("  " + "-" * 72)
    for use_sv in ("0", "1"):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="perf_"))
        pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), str(tmp), str(ROOT), use_sv],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            print("  失败: %s" % ((r.stdout or "") + (r.stderr or ""))[-300:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        print("  %-14s %-12.0f %-12.0f %-12.0f %s"
              % ("带主题" if use_sv == "1" else "不带主题",
                 res["startup_ms"], res["fill200_ms"], res["set50_ms"],
                 res["theme"]))
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("  说明: 这些是【本机】数字。若两者差不多, 说明'卡'不是主题造成的,")
    print("        更可能是【窗口重绘】本身(比如在子线程里频繁 update)。")


if __name__ == "__main__":
    raise SystemExit(main())
