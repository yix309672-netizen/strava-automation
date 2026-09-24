# -*- coding: utf-8 -*-
"""验收v2(干净版, 亲写): 第2/3/4条 —— 独立打桩, 不复用被改过的 _验收_采集.py

用法: python _验收_采集_v2.py ads|bit
桩的两条关键设计(踩过坑):
  1. 弹窗人数用【常量】, 不依赖"先读人数还是先取路段号"的调用顺序
  2. 路段号按【引擎日志里的当前地区】发, 否则纽约阶段会把俄亥俄的路段号吃掉
"""
import contextlib
import importlib.util
import json
import re
import shutil
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

WS = Path(__file__).resolve().parent
sys.path.insert(0, str(WS))
WHICH = (sys.argv[1] if len(sys.argv) > 1 else "ads").lower()
ENGINE = WS / "主脚本" / ("strava_ads.py" if WHICH == "ads" else "strava_bit.py")

FAILS, N, K = [], [0], [0]
RE_REGION = re.compile(r"\[region\]\s*=+\s*(?:\[\d+/\d+\]\s*)?(.+?)\s*=+")


def ck(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


class Log:
    def __init__(self, on_msg=None):
        self.lines = []
        self.on_msg = on_msg

    def _p(self, m, *a, **k):
        s = str(m)
        self.lines.append(s)
        if self.on_msg:
            self.on_msg(s)

    info = warning = error = debug = _p

    def text(self):
        return "\n".join(self.lines)


@contextlib.contextmanager
def tmpdir():
    base = WS / "_验收_tmp"
    base.mkdir(exist_ok=True)
    K[0] += 1
    d = base / f"case{K[0]}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def load():
    K[0] += 1
    name = f"v2_{WHICH}_{K[0]}"
    spec = importlib.util.spec_from_file_location(name, ENGINE)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def build(tmp, *, pass_fn, seg_plan, min_ath=None, ath_const=6000,
          dead_claim=False, dead_report=False):
    """seg_plan: {"New York": ["9001","9002"], "Ohio": ["9101"]}"""
    m = load()
    region_of = {}
    queues = {}
    for reg, sids in seg_plan.items():
        queues[reg] = list(sids)
        for s in sids:
            region_of[s] = reg
    rec = {"checked": [], "lb": [], "region": None, "queues": queues}

    def on_msg(s):
        mm = RE_REGION.search(s)
        if mm:
            rec["region"] = mm.group(1).strip()
    m.log = Log(on_msg=on_msg)

    for nm in ("goto_retry", "accept_cookies", "sleep_or_stop", "wait_text", "net_elapsed"):
        setattr(m, nm, lambda *a, **k: None)
    m.net_ready = lambda *a, **k: 0
    m.net_info = lambda *a, **k: "stub"
    m.time.sleep = lambda *a, **k: None

    page = MagicMock()
    page.evaluate.return_value = 1
    m.find_markers = lambda _p, *a, **k: [(120, 140), (200, 180), (260, 220)]

    def seg_popup(_p):
        cur = rec["region"] or ""
        q = None
        for reg, qq in queues.items():
            if reg.lower() in cur.lower():
                q = qq
                break
        if q is None:
            return None
        return q.pop(0) if q else None
    m.segment_from_popup = seg_popup
    m.popup_athletes = lambda _p: ath_const          # ★ 常量

    def fetch_lb(_p, sid, age, *a, **k):
        rec["lb"].append(str(sid))
        rec.setdefault("evt", []).append("lb")
        return 40, [{"aid": f"{sid}-{age}-{i:03d}", "name": f"u{i}"} for i in range(40)]
    m.fetch_lb_filtered = fetch_lb

    def check_ath(_p, aid, *a, **k):
        sid = str(aid).split("-")[0]
        rec.setdefault("evt", []).append("check")
        rec["checked"].append({"aid": aid, "sid": sid, "region": region_of.get(sid, "?"),
                               "exempt": bool(k.get("exempt_max")), "kw": dict(k)})
        return bool(pass_fn(aid)), ("粉丝10/关注10" if pass_fn(aid) else "粉丝500超标")
    m.check_athlete = check_ath

    if dead_claim:
        def _boom(*a, **k):
            raise m.ServerDown("模拟领取挂了")
        m.claim_pick = _boom
    else:
        def _claim(_c, _s, cand):
            rec.setdefault("evt", []).append("claim")
            return (list(cand), 0)
        m.claim_pick = _claim

    m.read_settings_info = lambda *a, **k: {"location": "Chicago, Illinois", "name": "T"}

    cli = MagicMock()

    def _collect(*a, **k):
        rec.setdefault("evt", []).append("collect")
        return None

    def _finish(*a, **k):
        rec.setdefault("evt", []).append("finish")
        return None

    cli.collect.side_effect = _collect if not dead_report else m.ServerDown("模拟上报挂了")
    cli.finish.side_effect = _finish

    m.COLLECT_OUT = tmp / "out.txt"
    m.COLLECT_SEEN = tmp / "seen.json"
    # ★ 2026-09-19 改造后必须补: 引擎新增进程内一次性去重索引 _OUT_HAVE
    #   (交付过的 URL 绝不再写第二遍), 只在第一次 _out_index() 时扫盘、之后常驻。
    #   同一进程连跑多个场景时不重置, 第一轮的 URL 会把后续轮次全判成"已交付"。
    if hasattr(m, "_OUT_HAVE"):
        m._OUT_HAVE["built"] = False
        m._OUT_HAVE["set"] = set()
    m.CFG.update({"min_athletes": 5000, "collect_target_per_account": 200,
                  "collect_auto_regions": False, "geo_filter": True, "lb_max_pages": 2,
                  "segs_per_region": 0, "location": "Chicago, Illinois",
                  "max_followers": 200})
    kw = {"regions": list(seg_plan.keys()), "home_loc": "Chicago, Illinois", "cli": cli,
          "geo_filter": True, "max_followers": 200}
    if min_ath is not None:
        kw["min_athletes"] = min_ath
    return m, page, rec, cli, kw


PLAN2 = {"New York": ["9001", "9002"], "Ohio": ["9101"]}
print(f"=== 验收v2: {ENGINE.name} ===")

print("\n[1] 硬性200: 达标即停 + 落盘/上报")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True, seg_plan=PLAN2)
    got = m.collect_regions(page, **kw)
    ck("正好采到 200 人", len(got) == 200, len(got))
    ck("这 200 人不重复", len({x["aid"] for x in got}) == 200)
    ck("落盘 200 行", m.COLLECT_OUT.exists()
       and len(m.COLLECT_OUT.read_text(encoding="utf-8").strip().splitlines()) == 200)
    ck("去重记录 200 个 pass",
       sum(1 for v in json.loads(m.COLLECT_SEEN.read_text(encoding="utf-8")).values()
           if v == "pass") == 200)
    ck("达标后没再扫俄亥俄", "9101" not in rec["lb"], sorted(set(rec["lb"])))
    ck("上报中心收到 200 次", cli.collect.call_count == 200, cli.collect.call_count)
    evt = rec.get("evt", [])
    firsts, seen_e = [], set()
    for e in evt:
        if e not in seen_e:
            seen_e.add(e)
            firsts.append(e)
    ck("运行时顺序: 先翻排行榜→再领取→再查资料→再上报",
       firsts[:4] == ["lb", "claim", "check", "collect"], firsts[:6])
    ck("每个候选人都是领取后才查(没有先查后领)",
       evt.index("claim") < evt.index("check") if "claim" in evt and "check" in evt else False)

print("\n[2] 不够200: 换州继续 + 必须报未达标")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: int(a[-3:]) % 5 == 0, seg_plan=PLAN2)
    got = m.collect_regions(page, **kw)
    ck("纽约不够时真的去了俄亥俄", "9101" in rec["lb"], sorted(set(rec["lb"])))
    ck("确实没采满", 0 < len(got) < 200, len(got))
    ck("日志报了未达标", bool(re.search(r"(未达标|只采到)", m.log.text())), m.log.text()[-90:])

print("\n[3] 每段≥5000 是硬性下限")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True,
                                  seg_plan={"New York": ["9001"]}, ath_const=4999)
    got = m.collect_regions(page, **kw)
    ck("4999 人的路段一个都不采用", not rec["lb"] and not got, f"lb={rec['lb']} got={len(got)}")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True,
                                  seg_plan={"New York": ["9001"]}, ath_const=5000)
    got = m.collect_regions(page, **kw)
    ck("5000 人的路段被采用", bool(rec["lb"]) and len(got) > 0, sorted(set(rec["lb"])))
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True, seg_plan=PLAN2, min_ath=200)
    got = m.collect_regions(page, **kw)
    ck("调用方传 200 也照样按 ≥5000 跑(硬性下限)", len(got) == 200, len(got))

print("\n[4] 纽约来源豁免上限 / 非纽约不豁免")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: int(a[-3:]) % 20 == 0, seg_plan=PLAN2)
    m.collect_regions(page, **kw)
    ny = [c for c in rec["checked"] if c["region"] == "New York"]
    oh = [c for c in rec["checked"] if c["region"] == "Ohio"]
    ck("查了纽约的人", bool(ny), len(ny))
    ck("纽约来源 exempt_max=True", ny and all(c["exempt"] for c in ny))
    ck("圆心有传下去", ny and ny[0]["kw"].get("center") is not None,
       ny[0]["kw"].get("center") if ny else None)
    ck("查了俄亥俄的人", bool(oh), len(oh))
    ck("非纽约 exempt_max=False", oh and not any(c["exempt"] for c in oh),
       sorted({c["exempt"] for c in oh}))

print("\n[5] 停止 / 领取挂 / 上报挂 必须立刻中断")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True, seg_plan=PLAN2)
    m.STOP_EVENT.set()
    r = None
    try:
        m.collect_regions(page, **kw)
    except Exception as e:
        r = e
    m.STOP_EVENT.clear()
    ck("停止位 -> UserStopped", isinstance(r, m.UserStopped), type(r).__name__ if r else "没抛")
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True, seg_plan=PLAN2, dead_claim=True)
    r = None
    try:
        m.collect_regions(page, **kw)
    except Exception as e:
        r = e
    ck("领取挂 -> ServerDown 上抛", isinstance(r, m.ServerDown), type(r).__name__ if r else "没抛")
    ck("中止后没继续查人", not rec["checked"], len(rec["checked"]))
with tmpdir() as tmp:
    m, page, rec, cli, kw = build(tmp, pass_fn=lambda a: True, seg_plan=PLAN2, dead_report=True)
    r = None
    try:
        m.collect_regions(page, **kw)
    except Exception as e:
        r = e
    ck("上报挂 -> ServerDown 上抛", isinstance(r, m.ServerDown), type(r).__name__ if r else "没抛")

print("\n[6] 真实 check_athlete 把 center/exempt_max 送进 in_target_band")
with tmpdir():
    m = load()
    box = {}
    import geo_cities as real
    proxy = types.ModuleType("geo_cities")
    proxy.__dict__.update(real.__dict__)

    def rec_band(loc, *a, **k):
        box["loc"], box["kw"] = loc, k
        return True, "stub", "city", 500.0, "Chicago"
    proxy.in_target_band = rec_band
    sys.modules["geo_cities"] = proxy
    try:
        page = MagicMock()
        page.evaluate.side_effect = [{"followers": 9, "following": 8}, {"loc": "Buffalo, NY"}]
        m.goto_retry = lambda *a, **k: None
        m.wait_text = lambda *a, **k: None
        m.sleep_or_stop = lambda *a, **k: None
        m.time.sleep = lambda *a, **k: None
        ok, why = m.check_athlete(page, 555, geo_filter=True,
                                  center=(41.87, -87.62, "Chicago, Illinois"), exempt_max=True)
        ck("保留", ok is True, why)
        ck("center 透传", box.get("kw", {}).get("center") == (41.87, -87.62, "Chicago, Illinois"),
           box.get("kw"))
        ck("exempt_max 透传", box.get("kw", {}).get("exempt_max") is True, box.get("kw"))
    finally:
        sys.modules["geo_cities"] = real

print("\n[7] 静态接线")
src = ENGINE.read_text(encoding="utf-8")
ck("MIN_ATHLETES_FLOOR=5000", re.search(r"MIN_ATHLETES_FLOOR\s*=\s*5000", src) is not None)
ck("TARGET_FLOOR=200", re.search(r"TARGET_FLOOR\s*=\s*200", src) is not None)
ck("两个调用点都传 target_per_account", src.count("target_per_account=") >= 3,
   src.count("target_per_account="))
ck("两个调用点都传 home_loc", src.count("home_loc=") >= 3, src.count("home_loc="))
ck("没有残留 100-800 旧口径", "100-800" not in src)

print("\n================ v2 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for x in FAILS:
    print("  ✗ " + x)
sys.exit(1 if FAILS else 0)
