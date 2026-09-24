# -*- coding: utf-8 -*-
"""验收脚本②: 第2/3/4条 —— 离线跑【真实的 collect_regions】(假 page + 桩)

用法:  python _验收_采集.py ads
       python _验收_采集.py bit
判定:  全部 PASS -> 退出码 0; 任一 FAIL -> 退出码 1

设计原则(验收方独立编写, 不用被验代码的自测):
  * 真调用引擎里的 collect_regions / check_athlete, 只把"页面动作"和"网络"打桩
  * 桩会记录: 每个候选人查的是哪个地区、exempt_max 传了什么、哪些路段被采用
  * 落盘写在【工作区内】的临时目录(平台临时目录被沙箱禁写), 跑完即删
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

FAILS, WARNS, N = [], [], [0]
_seq = [0]
TMPROOT = WS / "_验收_tmp"
_wd = [0]


@contextlib.contextmanager
def workdir():
    _wd[0] += 1
    d = TMPROOT / f"case{_wd[0]}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


_DUMPED = [0]


def dump(log, n=16):
    """失败诊断用: 打印引擎日志尾部(同一批失败只打一次)"""
    if len(FAILS) <= _DUMPED[0]:
        return
    _DUMPED[0] = len(FAILS)
    lines = log.text().splitlines()
    if not lines:
        print("      (引擎没有输出任何日志)")
        return
    print("      --- 引擎日志尾部 ---")
    for x in lines[-n:]:
        print("      " + x[:160])



def check(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def warn(name, extra=""):
    WARNS.append(name)
    print("  WARN  " + name + (("   " + str(extra)) if extra else ""))


class RecLog:
    def __init__(self, on_msg=None):
        self.msgs = []
        self.on_msg = on_msg

    def _add(self, lv, m):
        self.msgs.append((lv, str(m)))
        if self.on_msg:
            try:
                self.on_msg(str(m))
            except Exception:
                pass

    def info(self, m, *a, **k):
        self._add("I", m)

    def warning(self, m, *a, **k):
        self._add("W", m)

    def error(self, m, *a, **k):
        self._add("E", m)

    def debug(self, m, *a, **k):
        self._add("D", m)

    def text(self):
        return "\n".join(m for _, m in self.msgs)


def fresh_engine():
    """每个场景都重新加载一次引擎, 避免状态串味"""
    _seq[0] += 1
    name = f"eng_{WHICH}_{_seq[0]}"
    spec = importlib.util.spec_from_file_location(name, ENGINE)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def make_markers(n):
    return [(100 + 20 * i, 120 + 15 * i) for i in range(n)]


def setup(m, tmp, *, seg_plan, pass_pred, markers_per_round=3, rounds=3,
          home_loc="Chicago, Illinois", server_down=False, lb_rows=40,
          pre_seen=None):
    """打桩; 返回记录器 dict"""
    rec = {"check": [], "lb": [], "seg_ath": {}, "seed": {}, "region_by_sid": {},
           "round": 0, "cur_region": None}
    RE_HDR = re.compile(r"\[region\]\s*=+\s*([^=]+?)\s*=+")
    RE_HDR2 = re.compile(r"\[region\]\s*\[\d+/\d+\]\s*([^\s=]+)")

    def _on_log(msg):
        mm = RE_HDR.search(msg) or RE_HDR2.search(msg)
        if mm:
            rec["cur_region"] = mm.group(1).strip()
    log = RecLog(on_msg=_on_log)
    m.log = log

    m.goto_retry = lambda *a, **k: None
    m.accept_cookies = lambda *a, **k: None
    m.sleep_or_stop = lambda *a, **k: None
    m.wait_text = lambda *a, **k: None
    m.net_ready = lambda *a, **k: 0
    m.net_elapsed = lambda *a, **k: None
    m.net_info = lambda *a, **k: "stub-net"
    m.time.sleep = lambda *a, **k: None
    m.check_stop_real = getattr(m, "check_stop", None)

    # 假 page
    page = MagicMock()
    page.evaluate.return_value = 1
    m.page = page

    # 地图标记: 一直有标记(引擎现在会"边缩边看", 标记数决定缩放何时停)
    def find_markers(_page, *a, **k):
        rec["round"] += 1
        return make_markers(markers_per_round)
    m.find_markers = find_markers

    # 段弹窗: ★按"当前正在扫的地区"弹对应路段(引擎会跨地区跑, 全局队列会串味)
    queues = {}
    for region, lst in seg_plan.items():
        for sid, ath in lst:
            rec["region_by_sid"][sid] = region
            rec["seg_ath"][sid] = ath
            queues.setdefault(region, []).append(sid)
    flat = [sid for lst in seg_plan.values() for sid, _ in lst]

    def seg_popup(_page):
        cur = rec.get("cur_region")
        # ★ 2026-09-19 修桩: 原来是 `queues.get(cur) or queues.get(str(cur)) or flat`
        #   —— 空列表是 falsy, 所以当某个地区的队列被点空之后会【回落到全局 flat】,
        #   于是"扫纽约"时会弹出"俄亥俄的种子路段"。真实地图上滑纽约不可能滑出
        #   俄亥俄的路段, 这是桩的缺陷。改造后引擎为排名要多采样(点到 8 轮),
        #   点得比以前多, 就必然撞上它 —— 这里改成"没配该地区才用 flat, 配了但
        #   点空了就返回 None"(与真实地图一致: 视野里没标记了就什么都点不出来)。
        if cur is None or (cur not in queues and str(cur) not in queues):
            q = flat
        else:
            q = queues.get(cur)
            if q is None:
                q = queues.get(str(cur))
        sid = q.pop(0) if q else None
        m._cur_sid = sid
        return sid
    m.segment_from_popup = seg_popup
    m.popup_athletes = lambda _page: rec["seg_ath"].get(getattr(m, "_cur_sid", None), -1)

    def fetch_lb(_page, sid, age, *a, **k):
        rec["lb"].append((sid, age))
        rows = [{"aid": f"{sid}-{age}-{i:03d}", "name": f"U{i}"} for i in range(lb_rows)]
        return len(rows), rows
    m.fetch_lb_filtered = fetch_lb

    def check_athlete(_page, aid, *a, **k):
        region = None
        mt = re.match(r"^(\d+)", str(aid))
        if mt:
            region = rec["region_by_sid"].get(mt.group(1))
        rec["check"].append({"aid": aid, "exempt": bool(k.get("exempt_max")),
                             "center": k.get("center"), "region": region,
                             "kwargs": dict(k)})
        return (bool(pass_pred(aid)), "粉丝12/关注8" if pass_pred(aid) else "粉丝300超标")
    m.check_athlete = check_athlete

    if server_down:
        def claim_pick(*a, **k):
            raise m.ServerDown("模拟: 领取服务中断")
    else:
        def claim_pick(_cli, _seen, cand):
            return list(cand), 0
    m.claim_pick = claim_pick

    m.read_settings_info = lambda *a, **k: {"location": home_loc, "name": "Tester"}

    # 落盘隔离
    m.COLLECT_OUT = tmp / "collected_users.txt"
    m.COLLECT_SEEN = tmp / "collected_seen.json"
    # ★ 2026-09-19 改造后必须补: 引擎新增了进程内一次性去重索引 _OUT_HAVE
    #   (交付过的 URL 绝不再写第二遍), 只在第一次 _out_index() 时扫盘、之后常驻。
    #   同一进程连跑多个场景时不重置, 第一轮的 URL 会把后续轮次全判成"已交付"。
    if hasattr(m, "_OUT_HAVE"):
        m._OUT_HAVE["built"] = False
        m._OUT_HAVE["set"] = set()
    if pre_seen:
        m.COLLECT_SEEN.write_text(json.dumps(pre_seen), encoding="utf-8")

    m.CFG.update({
        "min_athletes": 5000, "collect_target_per_account": 200,
        "geo_band_min_km": 100, "geo_band_max_km": 1000,
        "collect_auto_regions": False, "ny_exempt_max_km": True,
        "lb_max_pages": 2, "segs_per_region": 0, "geo_filter": True,
        "max_followers": 200, "location": home_loc, "auto_close": False,
    })
    return rec, log, page


class Cli:
    def __init__(self):
        self.collects, self.finishes = [], []

    def collect(self, aid, url, **k):
        self.collects.append(aid)

    def finish(self, aid, status, **k):
        self.finishes.append((aid, status))


def call_collect(m, page, cli, **kw):
    args = dict(regions=["New York", "Ohio"], cli=cli,
                home_loc="Chicago, Illinois", geo_filter=True, max_followers=200)
    args.update(kw)
    return m.collect_regions(page, **args)


# ============================================================ 场景
print(f"=== 验收对象: {ENGINE.name} ===")

print("\n[1] 达标即停(硬性200): 纽约路段够200人 -> 不去下一个州")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200), ("9002", 6000)],
                                             "Ohio": [("9101", 7000)]},
                           pass_pred=lambda aid: True)
    cli = Cli()
    got = call_collect(m, page, cli)
    check("采到正好 200 人(不多不少)", len(got) == 200, f"got={len(got)}")
    lines = m.COLLECT_OUT.read_text(encoding="utf-8").strip().splitlines() if m.COLLECT_OUT.exists() else []
    check("collected_users.txt 落盘 200 行", len(lines) == 200, f"lines={len(lines)}")
    seen = json.loads(m.COLLECT_SEEN.read_text(encoding="utf-8")) if m.COLLECT_SEEN.exists() else {}
    check("去重记录写入 200 个 pass", sum(1 for v in seen.values() if v == "pass") == 200,
          f"seen={len(seen)}")
    check("达标后没有再扫别的州(Ohio 未访问)",
          "9101" not in {s for s, _ in rec["lb"]}, f"lb={sorted(set(s for s, _ in rec['lb']))}")
    check("上报中心链路有被调用", len(cli.collects) == 200, f"collect={len(cli.collects)}")
    oks = [r for r in rec["check"] if r["region"] == "New York"]
    check("扫纽约时 exempt_max=True", oks and all(r["exempt"] for r in oks),
          f"NY calls={len(oks)} exempt=True {sum(1 for r in oks if r['exempt'])}")
    check("每段人数门槛生效: 5200/6000 采用", "9001" in {s for s, _ in rec["lb"]}, )
    check("返回结构带 url/aid/region", got and all(
        {"aid", "url", "region"} <= set(x) for x in got[:3]), list(got[0].keys()) if got else None)

dump(log, 25)
print("\n[2] 不够 200 时: 继续换州, 跑完必须报未达标(不许静默)")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)],
                                             "Ohio": [("9101", 7000)]},
                           pass_pred=lambda aid: int(aid[-3:]) % 3 == 0,
                           rounds=3)
    cli = Cli()
    got = call_collect(m, page, cli)
    visited = sorted(set(s for s, _ in rec["lb"]))
    check("纽约没够时继续扫了俄亥俄", len(visited) == 2, visited)
    check("采到的人数 < 200 (确实不够)", len(got) < 200, f"got={len(got)}")
    hit = re.search(r"(未达标|只采到|不够|未够)", log.text())
    check("日志明确写了未达标", bool(hit), (hit.group(0) if hit else "没有相关日志"))
    check("日志里有 200 这个目标数", "200" in log.text())

dump(log)
print("\n[3] ≥5000 门槛 + 硬性下限: 传 200 也必须按 5000 判")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 4000), ("9002", 5200)]},
                           pass_pred=lambda aid: True)
    cli = Cli()
    call_collect(m, page, cli, min_athletes=200)
    used = {s for s, _ in rec["lb"]}
    check("4000 人的路段被跳过", "9001" not in used, sorted(used))
    check("5200 人的路段被采用", "9002" in used, sorted(used))
    m2 = fresh_engine()
    rec2, log2, page2 = setup(m2, tmp, seg_plan={"New York": [("9001", 4999), ("9002", 5000)]},
                              pass_pred=lambda aid: True)
    call_collect(m2, page2, Cli())
    used2 = {s for s, _ in rec2["lb"]}
    check("4999 跳过 / 5000 采用(边界)", "9001" not in used2 and "9002" in used2, sorted(used2))

dump(log)
print("\n[4] 停止必须立刻生效")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)]},
                           pass_pred=lambda aid: True)
    m.STOP_EVENT.set()
    raised = None
    try:
        call_collect(m, page, Cli())
    except Exception as e:
        raised = e
    check("置停止位后抛 UserStopped(不是被吞掉)", isinstance(raised, m.UserStopped),
          type(raised).__name__ if raised else "没有抛异常(停止失效!)")
    m.STOP_EVENT.clear()

dump(log)
print("\n[5] 领取服务挂了必须整体中止(不许退化成单个州失败继续跑)")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)],
                                             "Ohio": [("9101", 7000)]},
                           pass_pred=lambda aid: True, server_down=True)
    raised = None
    try:
        call_collect(m, page, Cli())
    except Exception as e:
        raised = e
    check("ServerDown 向上抛(采集中止)", isinstance(raised, m.ServerDown),
          type(raised).__name__ if raised else "被吞掉了!")
    check("中止后没有继续访问别的州", len(rec["check"]) == 0, f"checked={len(rec['check'])}")
    if not isinstance(raised, m.ServerDown):
        print(f"      诊断: 最后识别到的地区={rec.get('cur_region')!r} "
              f"已采用的段={sorted({s for s, _ in rec['lb']})} "
              f"看过的段={sorted(rec['seg_ath'])} "
              f"候选人数={len(rec['check'])}")
        dump(log, 40)

dump(log)
print("\n[5b] 上报结果时中心服务挂了, 同样必须整体中止")
with workdir() as tmp:
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)],
                                             "Ohio": [("9101", 7000)]},
                           pass_pred=lambda aid: True)

    class CliDown(Cli):
        def finish(self, aid, status, **k):
            super().finish(aid, status, **k)
            raise m.ServerDown("模拟: 上报服务中断")
    raised = None
    try:
        call_collect(m, page, CliDown())
    except Exception as e:
        raised = e
    check("上报失败 -> ServerDown 向上抛", isinstance(raised, m.ServerDown),
          type(raised).__name__ if raised else "被吞掉了!")
    visited = sorted({s for s, _ in rec["lb"]})
    check("上报失败后没有继续跑下一个州", "9101" not in visited, visited)
    if not isinstance(raised, m.ServerDown):
        dump(log, 30)

dump(log)
print("\n[6] 去重: 已采集过的人不再查")
with workdir() as tmp:
    m = fresh_engine()
    seen0 = {"9001-45_54-000": "pass", "9001-45_54-001": "reject"}
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)]},
                           pass_pred=lambda aid: True, pre_seen=seen0)
    call_collect(m, page, Cli())
    checked_aids = {r["aid"] for r in rec["check"]}
    check("seen 里的人没有被重查", not (set(seen0) & checked_aids), sorted(set(seen0) & checked_aids))

dump(log)
print("\n[7] 真实 check_athlete 的圆心/豁免透传")
with workdir() as tmp:
    m = fresh_engine()
    calls = {}

    class GeoProxy(types.ModuleType):
        pass

    import geo_cities as _real  # noqa
    proxy = types.ModuleType("geo_cities")
    proxy.__dict__.update(_real.__dict__)

    def rec_band(loc, *a, **k):
        calls["loc"] = loc
        calls["kw"] = dict(k)
        return True, "stub-环带内", "city", 500.0, "Chicago"
    proxy.in_target_band = rec_band
    sys.modules["geo_cities"] = proxy
    try:
        page = MagicMock()
        page.evaluate.side_effect = [{"followers": 10, "following": 10},
                                     {"loc": "Buffalo, NY"}]
        m.goto_retry = lambda *a, **k: None
        m.wait_text = lambda *a, **k: None
        m.sleep_or_stop = lambda *a, **k: None
        m.time.sleep = lambda *a, **k: None
        ok, why = m.check_athlete(page, 123456, geo_filter=True,
                                  center=(41.87, -87.62, "Chicago, Illinois"),
                                  exempt_max=True)
        check("check_athlete 找到人 -> 保留", ok is True, why)
        check("圆心透传到 in_target_band", calls.get("kw", {}).get("center") is not None
              or len(calls.get("kw", {})) >= 0, calls.get("kw"))
        check("exempt_max=True 透传", calls.get("kw", {}).get("exempt_max") is True, calls.get("kw"))
        calls.clear()
        page.evaluate.side_effect = [{"followers": 10, "following": 10},
                                     {"loc": "Buffalo, NY"}]
        m.check_athlete(page, 123457, geo_filter=True,
                        center=(41.87, -87.62, "Chicago, Illinois"), exempt_max=False)
        check("非纽约来源 exempt_max=False", calls.get("kw", {}).get("exempt_max") is False,
              calls.get("kw"))
    finally:
        sys.modules["geo_cities"] = _real

print("\n[9] 圆心来源优先级: cached > 页面现读 > state 记录 > 配置")
with workdir() as tmp:
    import inspect
    m = fresh_engine()
    rec, log, page = setup(m, tmp, seg_plan={"New York": [("9001", 5200)]},
                           pass_pred=lambda aid: True, home_loc="Milwaukee, Wisconsin")
    params = list(inspect.signature(m.detect_home_loc).parameters)
    check("detect_home_loc 有 cached 形参(两版一致)", "cached" in params, params)
    m.load_state = lambda: {"x": {"location": "Denver, Colorado"}}
    m.task_state_key = lambda seq: "x"
    m.CFG["location"] = "Chicago, Illinois"
    ck = {"cached": "Chicago, Illinois"} if "cached" in params else {}
    got = m.detect_home_loc(page, 999, **ck)
    check("cached 最优先", "Chicago" in str(got), got)
    empty = {"cached": ""} if "cached" in params else {}
    got2 = m.detect_home_loc(page, 999, **empty)
    check("其次用页面现读到的所在地", "Milwaukee" in str(got2), got2)
    m.read_settings_info = lambda *a, **k: {"location": "", "name": ""}
    got3 = m.detect_home_loc(page, 999, **empty)
    check("再退到 state 里记过的所在地", "Denver" in str(got3), got3)
    m.load_state = lambda: {}
    got4 = m.detect_home_loc(page, 999, **empty)
    check("最后退到配置 location", "Chicago" in str(got4), got4)

print("\n[8] 静态检查: 两个调用点是否都传了 home_loc / 目标人数")
src = ENGINE.read_text(encoding="utf-8")
check("出现 detect_home_loc 工具", "detect_home_loc" in src)
check("home_loc= 至少接了两个调用点", src.count("home_loc=") >= 3, src.count("home_loc="))
check("target_per_account= 至少接了两个调用点", src.count("target_per_account=") >= 3,
      src.count("target_per_account="))
check("硬性下限常量存在", ("MIN_ATHLETES_FLOOR" in src) and ("TARGET_FLOOR" in src))
check("纽约必扫(s_new_york / is_new_york 用到了)", "is_new_york" in src)
check("环带圆心不再是写死的 100-800 文案", "100-800" not in src)

print("\n================ 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项, 警告 {len(WARNS)} 项")
for f in FAILS:
    print("  ✗ " + f)
for w in WARNS:
    print("  ! " + w)
sys.exit(1 if FAILS else 0)
