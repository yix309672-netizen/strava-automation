# -*- coding: utf-8 -*-
"""在【解压出来的同事包】里实跑一遍落盘, 看文件到底写到哪。

针对用户报的症状: "采集下来的链接生成了文档却不在文件夹里面"。
不猜, 直接跑出来看路径。
"""
import importlib.util
import os
import sys
from pathlib import Path


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

PKG = Path(sys.argv[1])
os.chdir(PKG)
sys.path.insert(0, str(PKG))

spec = importlib.util.spec_from_file_location("strava_ads", PKG / "strava_ads.py")
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = SA
spec.loader.exec_module(SA)

print("=" * 70)
print(f"包目录        ROOT        = {SA.ROOT}")
print(f"配置来源      _CFG_P      = {SA._CFG_P}")
print(f"数据目录      DATA_DIR    = {SA.DATA_DIR}")
print(f"历史总表      COLLECT_OUT = {SA.COLLECT_OUT}")
print(f"当天文件目录  _task_dir() = {SA._task_dir()}")
print(f"当天文件      _daily_path = {SA._daily_path()}")
print(f"配置键数量    len(CFG)    = {len(SA.CFG)}")
print(f"min_athletes  CFG         = {SA.CFG.get('min_athletes')}")
print(f"collect_regions CFG       = {SA.CFG.get('collect_regions')}")

# ---- 真的写一条, 看落哪儿 ----
task = SA.new_task_ctx(target="__probe__", mode="probe", worker="probe")
url = "https://www.strava.com/athletes/999999999"
# ★ 生产里所有调用方传的都是【号级 ctx】(new_account_ctx), 不是 task
sub = SA.new_account_ctx(task, "probe")
ok = SA.append_task_url(sub, url)
p = sub.get("path")

# 另外单独验一下: 误传 task 级 ctx 会怎样(潜在缺陷, 不影响生产调用方)
task2 = SA.new_task_ctx(target="__probe2__", mode="probe", worker="probe")
try:
    SA.append_task_url(task2, "https://www.strava.com/athletes/888888888")
    print("[误传 task ctx] 没报错")
except Exception as e:
    print(f"[误传 task ctx] {type(e).__name__}: {e}")
print("-" * 70)
print(f"append_task_url 返回 = {ok}")
print(f"ctx['path']          = {p}")
if p:
    pp = Path(p)
    print(f"  文件存在           = {pp.exists()}")
    print(f"  父目录存在         = {pp.parent.exists()}")
    print(f"  是否在包目录里     = {PKG in pp.resolve().parents or pp.resolve().parent == PKG.resolve()}")
    if pp.exists():
        print(f"  内容               = {pp.read_text(encoding='utf-8').strip()!r}")
print("=" * 70)

# ---- 包目录实际长什么样 ----
print("包目录下的文件:")
for f in sorted(PKG.iterdir()):
    print(f"   {'[D]' if f.is_dir() else '   '} {f.name}")
