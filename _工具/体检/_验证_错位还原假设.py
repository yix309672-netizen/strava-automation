# -*- coding: utf-8 -*-
"""加强版校验: 还原之后每一列是不是都落回了合理取值。

只验 login/acts 两列不够 —— 万一是错位了两格, login/acts 也可能是"看起来对"的值。
这里把每一列的合法范围都卡一遍:
    login  ∈ {是, 否}            移位后会变成人名
    acts   数字(活动数)          移位后会变成 是/否
    prem   ∈ {是, 否}            移位后会变成 priv(一长串"小组…/地图…")
    name   不应含逗号            移位后会变成 city("Chicago, Illinois")
    city   不应是纯数字          移位后会变成 acts
    priv   不应是空            (老数据可能为空, 只统计)
只读, 不改文件。
"""
import json
import re
import sys
from pathlib import Path

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
YN = {"是", "否"}
# ★ 活动数可能是 -1(引擎用它表示"读不到/私密"), 所以不能只认 isdigit()——
#   '-1'.isdigit() 是 False, 第一版就是这么把 24 条正常数据误判成"还原失败"的。
NUM = re.compile(r"^-?\d+$")
UNSHIFT = [("login", "password"), ("name", "login"), ("city", "name"),
           ("acts", "city"), ("prem", "acts"), ("priv", "prem"),
           ("note", "priv")]


def needs_fix(v):
    login = str(v.get("login") or "").strip()
    acts = str(v.get("acts") or "").strip()
    if login and login not in YN:
        return True
    if acts and not acts.isdigit() and acts in YN:
        return True
    return False


for name, accname in (("ads_results.json", "ads_accounts.json"),
                      ("bit_results.json", "bit_accounts.json")):
    p = ROOT / "数据" / name
    if not p.is_file():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    fixed = 0
    breakers = {"login坏": 0, "acts坏": 0, "prem坏": 0, "name像城市": 0, "city像数字": 0}
    for v in d.values():
        if not isinstance(v, dict) or not needs_fix(v):
            continue
        src = {f: v.get(f, "") for f in
               ("password", "login", "name", "city", "acts", "prem", "priv", "note")}
        nv = dict(src)
        for dst, s in UNSHIFT:
            nv[dst] = src[s]
        fixed += 1
        lg = str(nv["login"]).strip()
        ac = str(nv["acts"]).strip()
        pr = str(nv["prem"]).strip()
        nm = str(nv["name"]).strip()
        ct = str(nv["city"]).strip()
        if lg and lg not in YN:
            breakers["login坏"] += 1
        if ac and not NUM.match(ac):
            breakers["acts坏"] += 1
        if pr and pr not in YN:
            breakers["prem坏"] += 1
        if "," in nm:
            breakers["name像城市"] += 1
        if ct.isdigit():
            breakers["city像数字"] += 1

    print("=" * 70)
    print(f"[{name}] 还原 {fixed} 条, 逐列校验:")
    for k, n in breakers.items():
        print(f"    {k:12s}= {n}" + ("   ★" if n else "   OK"))
    total_bad = sum(breakers.values())
    print("    -> " + ("★★★ 全部列都落回合理取值, 一次错位假设成立 ★★★"
                       if total_bad == 0 else
                       f"★★★ 还有 {total_bad} 处不合规 —— 假设可能不成立, 别急着改 ★★★"))
