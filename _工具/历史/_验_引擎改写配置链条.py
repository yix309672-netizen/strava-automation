# -*- coding: utf-8 -*-
"""确认: 引擎 import 时会不会把 config.json 改写掉 —— 这就是"5000"的来源。

链条推断:
  ① 包里 config.json: min_athletes=2000, _policy_rev 缺失
  ② 验证脚本第 3 节用 cwd=base 跑了一次引擎 import
  ③ 引擎的 enforce_admin_policy() 发现 _policy_rev 落后 -> 写回配置
     ★ 而 _ADMIN_POLICY 里写死的是 min_athletes=5000!
  ④ 于是 config.json 被改成 5000, 还写上了 _policy_rev=2
  ⑤ 第 4 节再起界面, 读到的已经是 5000

如果推断成立, 那【同事拿到包、第一次跑启动.bat, 配置就会被改成 5000】——
这正是"我改了 2000, 同事那边却是 5000"的真凶!
"""
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
tmp = pathlib.Path(tempfile.mkdtemp(prefix="chain_"))
with zipfile.ZipFile(ZIP) as z:
    z.extractall(tmp)
base = next(d for d in tmp.iterdir() if d.is_dir())

cfg_p = base / "config.json"
print("=" * 78)
print("链条验证")
print("=" * 78)
c0 = json.loads(cfg_p.read_text(encoding="utf-8"))
print()
print("① 解压后:")
print("     min_athletes = %r" % c0.get("min_athletes"))
print("     _policy_rev  = %r" % c0.get("_policy_rev"))

print()
print("② 跑一次引擎 import (和同事双击启动时一样)")
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
code = ("import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('e', r'%s')\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['e']=m\n"
        "spec.loader.exec_module(m)\n" % (base / "strava_ads.py"))
r = subprocess.run([sys.executable, "-c", code], cwd=str(base),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=240, env=env)
for l in (r.stdout or "").splitlines():
    if "管理员口径" in l or "现在:" in l:
        print("     引擎日志 | " + l.strip())

print()
print("③ import 之后, config.json 变成:")
c1 = json.loads(cfg_p.read_text(encoding="utf-8"))
print("     min_athletes = %r" % c1.get("min_athletes"))
print("     _policy_rev  = %r" % c1.get("_policy_rev"))

print()
print("=" * 78)
if c0.get("min_athletes") != c1.get("min_athletes"):
    print("★ 确认: 引擎把 min_athletes 从 %r 改成了 %r"
          % (c0.get("min_athletes"), c1.get("min_athletes")))
    print()
    print("  根因: 界面/引擎里的 _ADMIN_POLICY 写死了 min_athletes=5000,")
    print("        而 _policy_rev 落后时会【把这些硬编码值写回 config.json】。")
    print("  => 你在管理员配置里改成 2000, 但同事第一次启动就被改回 5000。")
    print("  => 这就是「我这边 2000、同事那边 5000」的真凶。")
else:
    print("· 配置没被改写 —— 推断不成立, 要另找原因")
print("=" * 78)
shutil.rmtree(tmp, ignore_errors=True)
