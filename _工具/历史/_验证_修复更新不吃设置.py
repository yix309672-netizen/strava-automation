# -*- coding: utf-8 -*-
"""红/绿验证: 修复更新.bat 会不会把同事自己选的采集州吃掉。

红(改之前): fix_update.py 的 POLICY_KEYS 里有 collect_regions / min_athletes,
           而 update.py 早就把这两个【摘掉】了(注释写得很清楚: 它们现在是
           界面下拉框, 强制下发会把同事的选择抹掉)。
           -> 同事点了"修复更新", 采集州被打回 New York, 每段门槛打回服务器值。
绿(改之后): 两个文件的 POLICY_KEYS 一致, 都不含这两个键。

做法: 直接 import 两个真文件的 POLICY_KEYS, 再照抄 fix_update 第四节的
      "对齐"逻辑跑一遍, 看同事的 California/3000 还在不在。
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

PKG = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


fu = load("_fu", PKG / "fix_update.py")
up = load("_up", PKG / "update.py")

print("=" * 74)
print("update.py    POLICY_KEYS:", len(up.POLICY_KEYS), "个")
print("fix_update.py POLICY_KEYS:", len(fu.POLICY_KEYS), "个")
extra = sorted(set(fu.POLICY_KEYS) - set(up.POLICY_KEYS))
print()
print("★ fix_update 多出来的键(会被强制覆盖):", extra)
print("=" * 74)

# 同事自己的设置: 选了 California, 门槛 3000
local = {"collect_regions": ["California"], "min_athletes": 3000,
         "jobs": 3, "adspower_key": "my-own-key", "avatar_dir": "运动头像"}
# 服务器下发的 config.json(发布端归一化过)
remote = {"collect_regions": ["New York"], "min_athletes": 2000,
          "jobs": 3, "adspower_key": "", "claim_server": "http://x", "claim_key": "k"}

print("同事原本: 采集州 =", local["collect_regions"], " 每段门槛 =", local["min_athletes"])
print("服务器值: 采集州 =", remote["collect_regions"], " 每段门槛 =", remote["min_athletes"])
print()

# ---- 照抄 fix_update.py 第四节的逻辑 ----
def align(local, remote, policy_keys):
    out = dict(local)
    for k, v in remote.items():
        if k not in out:
            out[k] = v
    forced = []
    for k in policy_keys:
        if k in remote and out.get(k) != remote.get(k):
            out[k] = remote[k]
            forced.append(k)
    return out, forced


after, forced = align(local, remote, fu.POLICY_KEYS)
print("跑完 fix_update 的对齐逻辑:")
print("  被强制改掉的键:", forced)
print("  采集州 ->", after["collect_regions"])
print("  每段门槛 ->", after["min_athletes"])
print("  自己的 key 还在吗:", after.get("adspower_key"))
print()

ok_regions = after["collect_regions"] == ["California"]
ok_min = after["min_athletes"] == 3000
if ok_regions and ok_min:
    print("★★★ 绿: 同事自己的选择被保住了 ★★★")
    rc = 0
else:
    print("★★★ 红: 同事的选择被吃掉了 —— 修复更新会把它打回服务器值 ★★★")
    rc = 1

# 顺带确认 update.py 的行为(它应该一直是好的)
after2, forced2 = align(local, remote, up.POLICY_KEYS)
print()
print("对照 update.py 的对齐结果: 采集州=%s 门槛=%s (forced=%s)"
      % (after2["collect_regions"], after2["min_athletes"], forced2))
sys.exit(rc)
