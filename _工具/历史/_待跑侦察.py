# -*- coding: utf-8 -*-
"""跑之前：看这 5 个账号缺什么、要跑多久"""
import json
import sys
import time
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


ts = json.loads((WS / "数据" / "task_state.json").read_text(encoding="utf-8"))
acc = json.loads((WS / "配置" / "ads_accounts.json").read_text(encoding="utf-8"))
today = time.strftime("%Y-%m-%d")

log("=== 今天 = %s ===" % today)
log("")
log("=== 待跑的账号（只做过采集、没做过资料）===")
TODO = []
for k in sorted(ts, key=lambda x: (len(x), x)):
    if not k.startswith("ads_"):
        continue
    v = ts[k]
    seq = k.split("_", 1)[1]
    need = [x for x in ("name", "location", "avatar", "privacy", "units")
            if not v.get(x)]
    if not need:
        continue
    col = str(v.get("collected") or "")
    log("  %-10s 序号 %-4s 缺: %-46s collected=%s %s"
        % (k, seq, ",".join(need), col or "(空)",
           "→ 今天已采, 会跳过采集" if col == today else "→ 会跑采集"))
    TODO.append(seq)

log("")
log("  合计 %d 个: %s" % (len(TODO), TODO))

log("")
log("=== 这些序号的账号密码在不在 ===")
for s in TODO:
    a = acc.get(s) or {}
    log("  %-4s %s  %s" % (s, a.get("email") or "★没账号",
                           "有密码" if a.get("password") else "★没密码"))

log("")
log("=== AdsPower 里这些环境在不在 ===")
import requests
K = "50171bf3e16dc3d763f08a2adb6d41a7009b3abca0f09491"
try:
    r = requests.get("http://127.0.0.1:50325/api/v1/user/list",
                     params={"page": 1, "page_size": 200},
                     headers={"Authorization": "Bearer " + K}, timeout=20).json()
    lst = (r.get("data") or {}).get("list") or []
    have = set()
    for x in lst:
        for f in ("serial_number", "seq", "name"):
            v = str(x.get(f) or "").strip()
            if v:
                have.add(v)
    log("  接口返回 %d 个环境" % len(lst))
    for s in TODO:
        log("    序号 %-4s 在环境列表里: %s" % (s, s in have))
    if lst:
        log("  环境字段示例: %s" % list(lst[0].keys())[:14])
except Exception as e:
    log("  查询失败: %s" % str(e)[:100])

log("")
log("=== 轨迹目录（要传的话有多少个）===")
cfg = json.loads((WS / "配置" / "config.json").read_text(encoding="utf-8"))
g = Path(str(cfg.get("gpx_dir") or ""))
if g.is_dir():
    fs = [f for f in g.iterdir() if f.is_file()]
    log("  %s -> %d 个文件" % (g, len(fs)))
    log("  每批 %s 个, 每天上限 %s 个" % (cfg.get("per_batch"), cfg.get("daily_cap")))
else:
    log("  ★ 轨迹目录不存在: %s" % g)
a = Path(str(cfg.get("avatar_dir") or ""))
log("  头像目录 %s -> %s" % (a, "%d 个文件" % len(list(a.iterdir()))
                            if a.is_dir() else "★不存在"))
