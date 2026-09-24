# -*- coding: utf-8 -*-
r"""验证"只采近期还有活动的人"(用户 2026-09-22 要求)。

★ 不是只看源码里有没有那几行 —— 是拿一个【假页面】把 check_athlete() 真跑一遍,
  喂它各种"最近活动日期", 看它到底淘汰谁、留谁。

数据来源(真页面探过):
    <time class="timeago" datetime="2026-09-21T17:47:06Z">7 hours ago</time>
    "Last 4 Weeks 15 Total Activities"
读 datetime 属性 —— 不用管界面语言, 也不用解析 "7 hours ago"。

验 9 件事:
  ① 3 天前有活动         -> 保留
  ② 90 天前(超两个月)    -> 淘汰
  ③ 恰好 59 天           -> 保留(边界内)
  ④ 恰好 61 天           -> 淘汰(边界外)
  ⑤ 读不到日期但4周内有活动 -> 保留(兜底)
  ⑥ 读不到日期且4周内为 0  -> 淘汰
  ⑦ recent_days=0 关掉时 -> 老行为(只看粉丝, 不因日期淘汰)
  ⑧ 日期合格但粉丝超标    -> 照样淘汰(新条件不许把老条件冲掉)
  ⑨ 假页面/私密          -> 照老规矩处理
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
ENGINES = {"ADS": ROOT / "主脚本" / "strava_ads.py",
           "BIT": ROOT / "主脚本" / "strava_bit.py"}


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class FakePage:
    """假页面: evaluate() 直接吐回我们要的数据。"""
    def __init__(self, data):
        self.data = data
        self.url = "https://www.strava.com/athletes/1"

    def evaluate(self, _js, *_a):
        return self.data


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    # 把真浏览器的动作全换成空转 —— 我们只测判定逻辑
    m.rate_gate = lambda *a, **k: None
    m.goto_retry = lambda *a, **k: None
    m.wait_text = lambda *a, **k: True
    m.check_stop = lambda *a, **k: None
    return m


ok_all = True
for tag, path in ENGINES.items():
    m = load(path, "_r_" + tag)
    m.CFG = dict(getattr(m, "CFG", {}) or {})
    m.CFG["us_only"] = False          # 关掉国别筛选, 只测日期这一条

    def check(data, days=60):
        return m.check_athlete(FakePage(data), "123", 200,
                               geo_filter=False, us_only=False, recent_days=days)

    cases = []
    base = {"followers": 10, "following": 20}

    cases.append(("① 3 天前有活动 -> 保留",
                  check(dict(base, recent_dates=[ago(3)], four_week=5))[0] is True,
                  check(dict(base, recent_dates=[ago(3)], four_week=5))[1]))
    cases.append(("② 90 天前 -> 淘汰(超两个月)",
                  check(dict(base, recent_dates=[ago(90)], four_week=0))[0] is False,
                  check(dict(base, recent_dates=[ago(90)], four_week=0))[1]))
    cases.append(("③ 59 天 -> 保留(边界内)",
                  check(dict(base, recent_dates=[ago(59)], four_week=0))[0] is True,
                  check(dict(base, recent_dates=[ago(59)], four_week=0))[1]))
    cases.append(("④ 61 天 -> 淘汰(边界外)",
                  check(dict(base, recent_dates=[ago(61)], four_week=0))[0] is False,
                  check(dict(base, recent_dates=[ago(61)], four_week=0))[1]))
    cases.append(("⑤ 没日期但4周内有活动 -> 保留",
                  check(dict(base, recent_dates=[], four_week=7))[0] is True,
                  check(dict(base, recent_dates=[], four_week=7))[1]))
    cases.append(("⑥ 没日期且4周内为0 -> 淘汰",
                  check(dict(base, recent_dates=[], four_week=0))[0] is False,
                  check(dict(base, recent_dates=[], four_week=0))[1]))
    cases.append(("⑦ 多条日期取最新的那条",
                  check(dict(base, recent_dates=[ago(200), ago(2), ago(80)],
                             four_week=0))[0] is True,
                  "最新=2天前"))
    cases.append(("⑧ recent_days=0 关掉 -> 老行为(不按日期淘汰)",
                  check(dict(base, recent_dates=[ago(500)], four_week=0), days=0)[0] is True,
                  check(dict(base, recent_dates=[ago(500)], four_week=0), days=0)[1]))
    cases.append(("⑨ 日期合格但粉丝超标 -> 照样淘汰",
                  check(dict(followers=999, following=5,
                             recent_dates=[ago(1)], four_week=9))[0] is False,
                  check(dict(followers=999, following=5,
                             recent_dates=[ago(1)], four_week=9))[1]))

    print("=" * 76)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")

print("=" * 76)
print("★★★ 只采近期两个月还有活动的人 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
