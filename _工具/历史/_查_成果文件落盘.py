# -*- coding: utf-8 -*-
"""排查: 同事采集到了但"没保存到文档"。

可能的原因, 逐个排:
  ① 文件写到别的地方去了(_find_data_dir 判断布局)
  ② 采集被中心服务拦了(领取服务不可用 -> 直接取消, 一条都不采)
  ③ append_task_url 落盘失败(权限/占用)
  ④ 旧版引擎还在跑(发的包没生效)

先在本机复现"平铺布局"下文件会落到哪 —— 同事的分发包就是平铺的。
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

print("=" * 80)
print("排查: 成果文件到底会写到哪")
print("=" * 80)

print()
print("1) 三种布局下 _find_data_dir() 的结果")
print("-" * 80)
PROBE = r'''
import importlib.util, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
eng = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("e", eng)
m = importlib.util.module_from_spec(spec); sys.modules["e"] = m
spec.loader.exec_module(m)
print("DATA_DIR=%s" % m.DATA_DIR)
print("COLLECT_OUT=%s" % m.COLLECT_OUT)
print("ROOT=%s" % m.ROOT)
print("DAILY=%s" % m._daily_path())
'''

CASES = [
    ("平铺(同事那种: config.json 和脚本同级)", {
        "config.json": "{}",
        "strava_ads.py": None,
    }),
    ("分层(开发目录: config.json 在 配置/)", {
        "配置/config.json": "{}",
        "主脚本/strava_ads.py": None,
        "数据/.keep": "",
    }),
]

for name, layout in CASES:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="layout_"))
    for rel, content in layout.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith("strava_ads.py") or content is None:
            shutil.copy2(ROOT / "主脚本" / "strava_ads.py", p)
        else:
            p.write_text(content, encoding="utf-8")
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-c", PROBE, str(tmp / "strava_ads.py")],
        cwd=str(tmp), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180, env=env)
    print("  【%s】" % name)
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, _v = line.split("=", 1)
            v = _v.replace(str(tmp), "<包目录>")
            print("     %-14s %s" % (k, v))
    if r.returncode != 0:
        print("     ★ 失败: %s" % ((r.stderr or "")[-200:]))
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("2) 采集时哪些情况会【一条都不写】")
print("-" * 80)
src = (ROOT / "主脚本" / "strava_ads.py").read_text(encoding="utf-8")
MARKERS = [
    ("领取服务不可用 -> 取消采集", "领取服务不可用"),
    ("fail-closed: 拿不到服务就不采", "fail-closed"),
    ("非会员跳过采集", "非会员,跳过采集"),
    ("浏览器被关 -> 取消", "浏览器/页面已关闭, 采集取消"),
    ("达标即停", "达标即停"),
    ("时间预算到 -> 停", "已达单号时间上限"),
]
for name, mark in MARKERS:
    print("  %s  %s" % ("有" if mark in src else "无", name))

print()
print("3) 落盘失败的日志长什么样(让同事照这个搜)")
print("-" * 80)
for line in src.splitlines():
    if "落盘失败" in line or "当天成果文件创建失败" in line:
        print("  " + line.strip()[:96])
