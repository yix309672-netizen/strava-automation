#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自测: 比特浏览器引擎「区域采集」新口径(_自测_采集_BIT.py)

跑法:  python _自测_采集_BIT.py

完全离线: 不联网、不起指纹浏览器、不碰真实账号/真实去重文件。
真跑 strava_bit.collect_regions(), 只把"页面动作"和"网络请求"换成假实现。

断言:
  (a) 采到 200 个合格用户就停(不多查一个人)
  (b) 一个地区不够会继续下一个地区; 跑完仍不够会 log 未达标
  (c) 纽约地区传 exempt_max=True, 非纽约传 False; 圆心=该号所在地(3 元组)
  (d) 路段人数 4000 跳过 / 5000 采用 / 读不到(-1) 跳过; 旧配置值被抬到硬性地板
  (e) STOP_EVENT 能打断 —— UserStopped 一路抛出, 不被 except Exception 吞掉
  (g) 领取中心挂掉(ServerDown) -> 整体中止, 不许继续下一个地区
  (i)~(l) ★ 自适应缩放(真机缺陷修复): 标记变差就停并回退到最佳级别; None(截图失败)
          不被当成 0 个、不改变最佳级别、不提前回退; 全程 None 不崩且 8 轮平移照跑;
          回退后标记 <3 个也不跳过该地区; ZOOM_MAX_STEPS=8 / ZOOM_MIN_STEPS=6
  (m) 源码静态核查: 4 个 find_markers( 调用点都区分 None;
          timeout=8000 / 两轮都失败 return None; PAN_ROUNDS=8 / ENOUGH_SEGMENTS=4;
          "14 级 + 再多放 4 级"死代码清干净; 风控闸门 / 时间预算 / 空地区跳过都在
  (n) 真 find_markers(不桩, 造真 PNG): 5 个橙点->list(5); 无点->[]; 两轮超时->None;
      第一轮超时第 2 轮成功->取到标记
  (o) 风控闸门 rate_gate: nav/api/act 最小间隔 6.0/1.5/0.6 秒, 走 sleep_or_stop(可打断)
  (p) 单号时间预算 collect_max_minutes: 缺省 240 分钟 / 配置值生效, 到点 [quota] 已达…
  (q) 死地区跳过: 零标记 -> 跳过平移; 连续 4 个 -> 停止采集; mk is None 不算空地区
  (r) 任务文件: 任务成品 collected_users_<tid>.txt + 号级明细 _<号>.txt(首行 # 任务开始)
  (s) append_task_url: 写前判重(历史已有 -> False 不计数); 落盘失败设 ctx["write_err"]
      且不向中心报 pass
  (iso1)~(isoN) ★ 场景隔离: 每个场景一个独立空目录(引擎 _out_index 会扫 COLLECT_OUT.parent
          下的任务文件, 共用目录会让上一场景的成果把下一场景全判成"历史已有"), 场景末尾
          断言"本场景目录里的 collected_users_*.txt 只属于本场景 + 目录外零新建"

★ geo_cities 的新接口已经由另一个子代理改造完成(geo_cities.py, BAND_MAX_KM=1000),
  但为了让本自测【离线且可重复】, 仍然用 stub 顶替 sys.modules['geo_cities']。
  也就是说: 本自测验证的是 strava_bit 侧的逻辑, 不含 geo_cities 的真实联调。
"""
import inspect
import logging
import re
import shutil
import sys
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# ★ 临时目录放在项目内(沙箱只允许写工作区), 跑完删掉。
#   注意不能用 tempfile.mkdtemp: 它建的目录是 0o700, 在受限沙箱下反而写不进去。
TMP = ROOT / "_自测_tmp"
TMP.mkdir(parents=True, exist_ok=True)
RESULT = []

# ==========================================================================
# ★★ 场景隔离(2026-09-19 改造后必须做)
#   引擎新增的"极致去重"索引 _out_index() 扫的是 COLLECT_OUT 本身 **以及
#   COLLECT_OUT.parent 下所有 collected_users_*.txt 任务文件**。老自测让所有场景
#   共用 _自测_tmp/collected.txt, 于是上一场景留在同一目录里的任务成品/号级明细
#   会被下一场景重建索引时读进来 —— 同一批假 athlete id 立刻被判成"历史已有",
#   collected 恒为 0(实测 "本地已有, 跳过不计数" 刷满整份日志)。
#   生产上"交付过的绝不再交付"正是用户要的极致去重, 所以这【不是引擎 bug】——
#   是测试必须给每个场景一个干净目录: TMP/sc<N>/。
# ==========================================================================
TASK_GLOB = "collected_users_*.txt"
_SC = {"n": 0}


def _outside_task_files():
    """场景目录【之外】的任务文件: 临时根目录 / 项目根 / 数据目录"""
    got = []
    for d in (TMP, ROOT, ROOT / "数据"):
        try:
            if d.is_dir():
                got += sorted(d.glob(TASK_GLOB))
        except Exception:
            pass
    return got


_OUTSIDE_SNAP = {str(p) for p in _outside_task_files()}


# --------------------------------------------------------------------------
# 1) geo_cities stub —— 冻结接口的等价实现(只为离线自测)
# --------------------------------------------------------------------------
def _install_geo_stub():
    m = types.ModuleType("geo_cities")
    m.BAND_MIN_KM, m.BAND_MAX_KM = 100.0, 1000.0
    m.HUBS = {"Chicago": (41.8781, -87.6298), "LosAngeles": (34.0522, -118.2437)}
    # 距圆心(芝加哥 41.88,-87.63)的测试距离:
    #   New York 1145km(超 1000, 只有豁免才留) / New Jersey 1100km / Pennsylvania 900km
    m._DIST = {"New York": 1145.0, "New Jersey": 1100.0, "Pennsylvania": 900.0}

    def resolve_center(loc_text, state_hint=""):
        t = str(loc_text or "").strip().lower()
        if not t:
            return None, None, "", "none"
        if "chicago" in t or "illinois" in t or t.endswith(", il"):
            return 41.88, -87.63, "Chicago, IL", "city"
        if "new york" in t or t == "ny":
            return 40.71, -74.01, "New York, NY", "city"
        if "los angeles" in t or t.endswith(", ca"):
            return 34.05, -118.24, "Los Angeles, CA", "city"
        if t in ("iowa", "ia"):
            return 42.0, -93.5, "Iowa", "state"      # 只到州级 -> 引擎应回退
        return None, None, "", "none"

    def in_target_band(loc_text, state_hint="", min_km=None, max_km=None,
                       center=None, exempt_max=False):
        lo = m.BAND_MIN_KM if min_km is None else float(min_km)
        hi = m.BAND_MAX_KM if max_km is None else float(max_km)
        t = str(loc_text or "").strip()
        if not t:
            return None, "位置无法识别(空)", "none", None, None
        d = m._DIST.get(t)
        if d is None:
            return None, f"位置无法识别({t})", "none", None, None
        lab = (center[2] if isinstance(center, (tuple, list)) and len(center) > 2
               else "圆心")
        if d < lo:
            return False, f"距{lab}仅{d:.0f}km(<{lo:.0f} 太近)", "city", d, lab
        if d > hi and not exempt_max:
            return False, f"距{lab}{d:.0f}km(>{hi:.0f} 太远)", "city", d, lab
        if d > hi and exempt_max:
            return True, f"距{lab}{d:.0f}km(纽约豁免上限)", "city", d, lab
        return True, f"距{lab}{d:.0f}km(环带内)", "city", d, lab

    def states_in_band(center_lat, center_lon, min_km=None, max_km=None):
        # ★ 故意把 New York 也放进来: 验证"纽约必扫"去重后仍然只有一份且排第一
        return [("PA", "Pennsylvania", 900.0), ("NJ", "New Jersey", 1100.0),
                ("NY", "New York", 1145.0)]

    def state_center(abbr_or_name):
        return (43.0, -75.0, "New York")

    def is_new_york(text):
        t = str(text or "").strip().lower()
        return t in ("new york", "ny", "new york state", "纽约", "纽约州")

    m.resolve_center = resolve_center
    m.in_target_band = in_target_band
    m.states_in_band = states_in_band
    m.state_center = state_center
    m.is_new_york = is_new_york
    sys.modules["geo_cities"] = m


_install_geo_stub()

# --------------------------------------------------------------------------
# 2) 别污染真实日志: 把引擎 import 时的 FileHandler 引到临时目录
# --------------------------------------------------------------------------
_RealFileHandler = logging.FileHandler


class _TmpFileHandler(_RealFileHandler):
    def __init__(self, *a, **k):
        k.pop("filename", None)               # 引擎是位置参数传进来的
        # ★ 再兜一次 mkdir: 本文件从"建 TMP"到"装日志句柄"之间有个空窗, 若此刻
        #   有另一个自测进程(同一个 _自测_tmp 目录)正在收尾 rmtree, TMP 会消失,
        #   于是 FileHandler 打开日志文件时 FileNotFoundError 直接崩在 import 上
        #   (实测踩过一次)。补这一行就能扛住。
        TMP.mkdir(parents=True, exist_ok=True)
        _RealFileHandler.__init__(self, str(TMP / "selftest_run.log"),
                                  *(a[1:] if a else ()), **k)


logging.FileHandler = _TmpFileHandler
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "主脚本"))
import strava_bit as bit                                    # noqa: E402
logging.FileHandler = _RealFileHandler


# --------------------------------------------------------------------------
# 3) 日志捕获(只看, 不打印引擎的全量日志)
# --------------------------------------------------------------------------
class _Cap(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.lines = []

    def emit(self, rec):
        try:
            self.lines.append(rec.getMessage())
        except Exception:
            pass


CAP = _Cap()
bit.log.handlers = [CAP]
bit.log.propagate = False
bit.log.setLevel(logging.INFO)

# ★ 自测必须关掉停顿看门狗: 本自测把 time.sleep 换成空操作, 看门狗线程会变成忙等;
#   而"单号时间预算"用例要用假时钟把 time() 往前拨, 真看门狗会当场 os._exit(9)。
bit.STALL_EXIT_SEC = 0


def pick(lines, *keys, limit=3):
    """挑出含关键字的日志行(去重, 限条数)"""
    out = []
    for ln in lines:
        if any(k in ln for k in keys) and ln not in out:
            out.append(ln)
            if len(out) >= limit:
                break
    return out


def show(lines, *keys, limit=3):
    for ln in pick(lines, *keys, limit=limit):
        print("   ", ln)


# --------------------------------------------------------------------------
# 4) 假页面 / 假时钟
# --------------------------------------------------------------------------
class _FakeBtn:
    def count(self):
        return 0

    def is_visible(self):
        return False

    def click(self, *a, **k):
        pass

    @property
    def first(self):
        return self


class _FakeMouse:
    def move(self, *a, **k):
        pass

    def wheel(self, *a, **k):
        pass

    def click(self, *a, **k):
        pass

    def down(self):
        pass

    def up(self):
        pass


class _FakeKeyboard:
    def type(self, *a, **k):
        pass


class _FakePage:
    """假 page: 地图/按钮全部返回"没有", 流程全靠下面的 monkeypatch 驱动"""
    mouse = _FakeMouse()
    keyboard = _FakeKeyboard()

    def get_by_role(self, *a, **k):
        return _FakeBtn()

    def get_by_text(self, *a, **k):
        return _FakeBtn()

    def locator(self, *a, **k):
        return _FakeBtn()

    def evaluate(self, *a, **k):
        return 1                      # devicePixelRatio

    def screenshot(self, *a, **k):
        return b""


class _ZoomMouse:
    """★ 会记级别的假鼠标: wheel(0,-500)=放大1级, wheel(0,500)=缩小1级

    真机上一次滚轮 = 热力图一级; 自适应缩放用例就是靠它验证"最终停在哪一级"。
    """
    def __init__(self, page):
        self.page = page

    def move(self, *a, **k):
        pass

    def wheel(self, _x=0, dy=0):
        if dy < 0:
            self.page.zoom += 1
            self.page.zooms.append("in")
        else:
            self.page.zoom -= 1
            self.page.zooms.append("out")

    def click(self, *a, **k):
        pass

    def down(self):
        self.page.pans += 1           # 平移拖拽计次

    def up(self):
        pass


class _ZoomPage(_FakePage):
    """★ 带"当前缩放级别"的假页面(自适应缩放用例专用)"""
    def __init__(self, start_zoom=0):
        self.zoom = start_zoom        # 绝对缩放级别(模拟页面进来时的层级)
        self.zooms = []               # 滚轮顺序 ['in','in',...,'out']
        self.pans = 0                 # 平移(拖拽)次数
        self.mouse = _ZoomMouse(self)


_RealTime = bit.time


class _FastTime:
    """time.sleep 变空操作(其余照旧), 让 1.5~3 秒的采集节奏不拖慢自测

    step > 0 时进一步把 time() 变成"每读一次往前走 step 秒"的假时钟
    (单号时间预算用例); ★ 只对主线程生效 —— 引擎的停顿看门狗跑在子线程里
    (本自测已把它关掉, 这里再兜一层), 绝不能让它读到被拨快的假时钟而 os._exit(9)。
    """
    def __init__(self, step=0.0):
        self.step = float(step or 0.0)
        self._t = _RealTime.time()

    def __getattr__(self, k):
        return getattr(_RealTime, k)

    def sleep(self, _sec):
        pass

    def time(self):
        if not self.step or threading.current_thread() is not threading.main_thread():
            return _RealTime.time()
        v = self._t
        self._t += self.step
        return v


_BASE_CFG = {"geo_filter": True, "collect_auto_regions": True,
             "ny_exempt_max_km": True, "geo_band_min_km": 100,
             "geo_band_max_km": 1000, "location": "Chicago, Illinois"}


class _FakeCli:
    """假领取中心: 只实现引擎真正会调的三个方法

    raise_serverdown=True 时 claim_batch 抛 ServerDown —— 用来验证
    "领取中心挂掉 = 整体中止, 不许继续下一个地区"。
    """

    def __init__(self, raise_serverdown=False, mine_all=True):
        self.raise_serverdown = raise_serverdown
        self.mine_all = mine_all
        self.calls = {"claim": [], "collect": [], "finish": []}

    def claim_batch(self, aids):
        self.calls["claim"].append(list(aids))
        if self.raise_serverdown:
            raise bit.ServerDown("模拟: 领取服务中断")
        return {"mine": list(aids) if self.mine_all else [], "taken": []}

    def collect(self, *a, **k):
        self.calls["collect"].append((a, k))

    def finish(self, *a, **k):
        self.calls["finish"].append((a, k))


# --------------------------------------------------------------------------
# 5) 跑一次 collect_regions(monkeypatch 掉所有页面/网络动作)
# --------------------------------------------------------------------------
def run_case(*, target=200, min_athletes=None, max_segments=None,
             seg_ath=None, pass_fn=None, stop_after=None,
             regions=("New York",), auto_regions=None, cfg_extra=None,
             home_loc="Chicago, Illinois", rows_per_batch=40,
             claim_raises=False, markers_fn=None, start_zoom=0,
             cli=None, seq="7", clock_step=0.0, broken_write=False):
    seg_ath = seg_ath or {}
    # ★ 场景隔离: 每个场景一个全新的空目录(见文件头说明)
    _SC["n"] += 1
    sc = _SC["n"]
    sc_dir = TMP / f"sc{sc}"
    if sc_dir.exists():
        shutil.rmtree(sc_dir, ignore_errors=True)
    sc_dir.mkdir(parents=True, exist_ok=True)
    env = {"region": -1, "checks": [], "lb_calls": [], "markers": 0, "sc": sc}
    seg = {"ids": []}
    # ★ 缩放用例需要"跟着滚轮变级别"的假页面; 其余用例沿用原来那个无状态假页面
    page = _ZoomPage(start_zoom) if markers_fn is not None else _FakePage()

    def _goto(page, url, *a, **k):
        env["region"] += 1
        seg["ids"] = []                       # 新地区 -> 路段重新编号

    def _markers(page, min_area=60, max_area=900):
        env["markers"] += 1
        if markers_fn is not None:
            return markers_fn(page)           # 允许返回 None: 模拟截图失败(标记未知)
        b = env["markers"] * 1000
        return [(b + 50 + i * 37, b + 50 + i * 41) for i in range(6)]

    def _sfp(page):
        sid = f"R{env['region']}S{len(seg['ids'])}"
        seg["ids"].append(sid)
        return sid

    def _pa(page):
        return seg_ath.get(seg["ids"][-1], 6000)

    def _lb(page, sid, age, max_pages=None):
        env["lb_calls"].append((sid, age))
        # ★ 假 athlete id 带场景号: 于是"本场景任务文件里的 URL 只属于本场景"
        #   可以被真正断言出来(场景间不重号)。
        return 500, [{"aid": f"a{sc}_{sid}-{age}-{i}", "name": f"N{i}"}
                     for i in range(rows_per_batch)]

    def _chk(page, aid, max_followers=200, geo_filter=False, center=None,
             exempt_max=False):
        env["checks"].append({"aid": aid, "region": env["region"],
                              "exempt": exempt_max, "center": center,
                              "geo": geo_filter})
        n = len(env["checks"])
        if stop_after is not None and n >= stop_after:
            bit.STOP_EVENT.set()             # 模拟用户中途点停止
        return (bool(pass_fn(aid, env["region"], n)) if pass_fn else True), "自测判定"

    _patched = (("goto_retry", _goto), ("find_markers", _markers),
                ("segment_from_popup", _sfp), ("popup_athletes", _pa),
                ("fetch_lb_filtered", _lb), ("check_athlete", _chk),
                ("accept_cookies", lambda *a, **k: None),
                ("sleep_or_stop", lambda *a, **k: None),
                ("net_info", lambda: "selftest"),
                ("save_seen", lambda seen: None))
    if claim_raises and cli is None:
        # ★ 模拟领取中心挂掉: claim_pick 抛 ServerDown。
        #   正确行为 = 整体中止(绝不能被外层 except Exception 当成"这个地区出错")
        #   ★ 注意: 引擎只在 cli is not None 时才走领取这一步, 所以老写法
        #     (claim_raises=True 但 cli=None) 根本触发不到 —— 见下面 (g) 用真 cli。
        def _claim(cli, seen, aids):
            raise bit.ServerDown("模拟: 领取服务中断")
        _patched = _patched + (("claim_pick", _claim),)
    if broken_write:
        # ★ 落盘一定失败: 让 _open_task_file 返回一个【目录】, open(dir,"a") 必抛
        _bad_dir = sc_dir / "bad_target"
        _bad_dir.mkdir(parents=True, exist_ok=True)
        _patched = _patched + (("_open_task_file", lambda ctx, kind="acct": _bad_dir),)
    orig = {n: getattr(bit, n) for n, _ in _patched}
    _o = {"time": bit.time, "CFG": bit.CFG, "OUT": bit.COLLECT_OUT,
          "SEEN": bit.COLLECT_SEEN, "STOP": bit.STOP_EVENT}
    for n, v in _patched:
        setattr(bit, n, v)
    bit.time = _FastTime(clock_step)
    _cfg = dict(_BASE_CFG)
    _cfg.update(cfg_extra or {})
    bit.CFG = _cfg
    bit.COLLECT_OUT = sc_dir / "collected.txt"       # _task_dir() = 本场景目录
    bit.COLLECT_SEEN = sc_dir / "seen_not_exist.json"  # 不存在 -> seen 为空
    # ★ 2026-09-19 改造后必须补这一步: 引擎新增了进程内一次性去重索引 _OUT_HAVE
    #   (交付过的 URL 绝不再写第二遍), 只在第一次 _out_index() 时扫盘、之后常驻。
    #   本自测在同一进程连跑多个场景, 不重置的话第一轮采到的 URL 会把后续轮次
    #   全判成"已交付" —— 那是测试隔离问题, 不是引擎 bug。
    #   ★ 重置之外还必须配合上面的"每场景独立空目录": _out_index() 扫的是
    #     COLLECT_OUT.parent 下所有 collected_users_*.txt, 只重置内存索引而共用
    #     目录的话, 重建索引时照样会把上一场景的成果读回来。
    if hasattr(bit, "_OUT_HAVE"):
        bit._OUT_HAVE["built"] = False
        bit._OUT_HAVE["set"] = set()
    bit.STOP_EVENT = threading.Event()
    CAP.lines = []
    err = None
    try:
        res = bit.collect_regions(page, regions=list(regions),
                                  min_athletes=min_athletes, max_followers=200,
                                  target_per_account=target,
                                  max_segments_per_region=max_segments,
                                  cli=cli, geo_filter=None, home_loc=home_loc,
                                  auto_regions=auto_regions, seq=seq)
    except Exception as e:                                  # noqa: BLE001
        res, err = None, e
    finally:
        for n, v in orig.items():
            setattr(bit, n, v)
        bit.time, bit.CFG = _o["time"], _o["CFG"]
        bit.COLLECT_OUT, bit.COLLECT_SEEN = _o["OUT"], _o["SEEN"]
        bit.STOP_EVENT = _o["STOP"]
    out = {"collected": res, "err": err, "lines": list(CAP.lines),
           "page": page, "dir": sc_dir, **env}
    out["iso"] = _iso_check(sc, sc_dir, res)
    shutil.rmtree(sc_dir, ignore_errors=True)      # 场景结束清掉该子目录
    return out


def _iso_check(sc, sc_dir, res):
    """★ 场景隔离自检: 目录内只属于本场景 + 目录外零新建(每个场景末尾一条断言)"""
    tag = f"a{sc}_"
    files = sorted(sc_dir.glob(TASK_GLOB))
    urls, hdr_ok, end_ok = set(), True, False
    for p in files:
        txt = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if not txt or not txt[0].startswith("# 任务开始"):
            hdr_ok = False
        # ★ 2026-09-19 用户要求"只保留链接, 其他信息不需要":
        #   数据行必须是纯 URL(无制表符附加列), 也没有 "# 任务结束/号数" 这类额外行。
        _data = [x.strip() for x in txt if x.strip() and not x.strip().startswith("#")]
        if _data and all(x.startswith("http") and "\t" not in x for x in _data):
            end_ok = True
        for ln in _data:
            urls.add(ln.split("\t")[0])
    foreign = sorted(u for u in urls
                     if not u.rsplit("/", 1)[-1].startswith(tag))
    leaks = sorted(str(p.relative_to(ROOT)) for p in _outside_task_files()
                   if str(p) not in _OUTSIDE_SNAP)
    expect = None if res is None else {c["url"] for c in res}
    same = (expect is None) or (expect == urls)
    info = {"sc": sc, "files": [p.name for p in files], "urls": len(urls),
            "expect": None if expect is None else len(expect),
            "foreign": foreign, "leaks": leaks, "same": same,
            "hdr_ok": hdr_ok, "end_ok": end_ok}
    check(f"(iso{sc}) 场景目录隔离: 本场景目录里的 {len(files)} 个 {TASK_GLOB} "
          f"只含本场景 URL, 且目录外没有新建任何任务文件",
          (not foreign) and (not leaks) and same and hdr_ok
          and (end_ok or not urls),
          f"files={info['files']} url数={len(urls)} 本场景应={info['expect']} "
          f"外来={foreign[:2]} 目录外新建={leaks[:2]} 首行任务头={hdr_ok} "
          f"任务结束={end_ok}")
    return info


def check(name, cond, detail=""):
    RESULT.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))


# ==========================================================================
# (a) 到 200 就停 + (c) 纽约豁免 + 圆心
# ==========================================================================
print("=" * 78)
print("(a) 硬性 200: 达标即停, 不多查一个人")
print("=" * 78)
A = run_case(target=200)
n_a = len(A["collected"] or [])
check("(a) 恰好采到 200 个合格用户", n_a == 200, f"实际 {n_a}")
check("(a) 恰好只查了 200 个人(没有多查)", len(A["checks"]) == 200,
      f"实际查了 {len(A['checks'])} 人")
check("(a) 有 [quota] 合格 X/200 进度日志",
      # ★ 2.2 起进度行后面带了 地区/名字/判定依据(便于对账), 所以是"前缀+后缀"
      #   而不是原来那种整行相等; 强度不降: 首行/末行 + 后缀格式都要对得上。
      any(ln.startswith("[quota] 合格 1/200") for ln in A["lines"])
      and any(ln.startswith("[quota] 合格 200/200") for ln in A["lines"])
      and any(re.match(r"\[quota\] 合格 1/200\s+\[New York\] \S+ 自测判定$", ln)
              for ln in A["lines"]),
      str(pick(A["lines"], "[quota] 合格", limit=1)))
check("(a) 有 [quota] 达标日志",
      any("[quota] 达标 200/200" in ln for ln in A["lines"]))
check("(t) 任务成品 collected_users_<tid>.txt + 号级明细 collected_users_<tid>_7.txt",
      len([f for f in A["iso"]["files"] if "_7" not in f]) == 1
      and len([f for f in A["iso"]["files"] if f.endswith("_7.txt")]) == 1
      and all(re.fullmatch(r"collected_users_\d{8}_\d{6}(_7)?\.txt", f)
              for f in A["iso"]["files"]),
      f"files={A['iso']['files']}")
check("(t) 两个任务文件首行都是 '# 任务开始 ...', 数据行是纯链接(无附加列)",
      A["iso"]["hdr_ok"] and A["iso"]["end_ok"],
      f"hdr={A['iso']['hdr_ok']} end={A['iso']['end_ok']}")
check("(t) 任务文件里的 URL 数 == 本次 collected 数(200)",
      A["iso"]["urls"] == 200 and A["iso"]["expect"] == 200 and A["iso"]["same"],
      f"url={A['iso']['urls']} expect={A['iso']['expect']} same={A['iso']['same']}")
check("(c) 纽约地区 exempt_max=True",
      bool(A["checks"]) and all(c["exempt"] is True
                                for c in A["checks"] if c["region"] == 0),
      f"纽约被查 {sum(1 for c in A['checks'] if c['region'] == 0)} 人")
check("(c) 圆心=该号所在地 Chicago(41.88,-87.63), 3 元组带 label, 不是写死的旧圆心",
      bool(A["checks"]) and all(c["center"] == (41.88, -87.63, "Chicago, IL")
                                for c in A["checks"]),
      f"center={A['checks'][0]['center'] if A['checks'] else None}")
check("(c) 纽约排第一且只出现一次(geo_cities 也返回了 NY, 必须去重)",
      any("[geo] 计划扫描 3 个地区: New York(纽约/豁免上限) -> Pennsylvania"
          " -> New Jersey" in ln for ln in A["lines"]),
      str(pick(A["lines"], "[geo] 计划扫描", limit=1)))
print("  关键日志:")
show(A["lines"], "[geo] 本号所在地", "[geo] 计划扫描", "[quota] 硬性指标")
show(A["lines"], "[quota] 合格 200", "[quota] 达标")
show(A["lines"], "自适应缩放")
show(A["lines"], "[check]", limit=1) if any("[check]" in x for x in A["lines"]) else None

# ==========================================================================
# (b) 一个地区不够 -> 继续下一个; 跑完不够 -> log 未达标
#     (c) 顺带验证: 非纽约地区 exempt_max=False
# ==========================================================================
print()
print("=" * 78)
print("(b) 一个地区不够继续下一个; 跑完不够必 log 未达标   (c) 非纽约 exempt=False")
print("=" * 78)
B = run_case(target=200, pass_fn=lambda aid, r, n: n <= 30)
n_b = len(B["collected"] or [])
check("(b) 纽约不够时继续扫了下一个地区", B["region"] >= 1,
      f"实际走到第 {B['region'] + 1} 个地区")
check("(b) 一直换到最后一个地区(计划 3 个地区全走完)", B["region"] == 2,
      f"region 索引={B['region']}(0=New York,1=Pennsylvania,2=New Jersey)")
check("(b) 跑完不够 -> log.warning 未达标",
      any("[quota] 只采到 30/200 未达标" in ln for ln in B["lines"]),
      f"实际 {n_b}/200")
check("(c) 非纽约地区 exempt_max=False",
      any(c["region"] > 0 for c in B["checks"])
      and all(c["exempt"] is False for c in B["checks"] if c["region"] > 0),
      f"非纽约被查 {sum(1 for c in B['checks'] if c['region'] > 0)} 人")
check("(c) 同一轮里纽约 True / 非纽约 False 都出现过",
      {c["exempt"] for c in B["checks"] if c["region"] == 0} == {True}
      and {c["exempt"] for c in B["checks"] if c["region"] > 0} == {False})
check("(c) 非纽约地区不再打印豁免日志",
      sum(1 for ln in B["lines"] if "豁免 1000km 上限" in ln) == 1)
print("  关键日志:")
show(B["lines"], "[geo] 计划扫描")
show(B["lines"], "[region] =====", limit=4)
show(B["lines"], "[quota] 只采到")

# ==========================================================================
# (d) 路段人数门槛 + 硬性地板
# ==========================================================================
print()
print("=" * 78)
print("(d) 每段 >= 5000 人: 4000/4999/-1 采样后被排名淘汰; 5000/5001 被采纳")
print("=" * 78)
D = run_case(target=200,
             seg_ath={"R0S0": 4000, "R0S1": 5000, "R0S2": -1,
                      "R0S3": 4999, "R0S4": 5001})
d_lb_sids = {sid for sid, _age in D["lb_calls"]}
# ★ 2026-09-19: 选路段改成"先采样、再按运动达人数排名" —— 决策时机从"逐个当场
#   判定"挪到了"统一排名", 日志文案随之改变(采用/跳过 -> 采样/排名)。
#   下面的"没被采纳"判定强度不变, 只把日志文案换成新的。
check("(d) 4000 人的路段被采样、但排名时被淘汰(不查排行榜)",
      any("运动达人=4000" in ln for ln in D["lines"])
      and "R0S0" not in d_lb_sids)
check("(d) 5000 人的路段被采样并进入排名",
      any("运动达人=5000" in ln for ln in D["lines"])
      and any("路段排名(运动达人 降序)" in ln for ln in D["lines"]))
check("(d) 读不到人数(-1) 记 0 并 log",
      any("读不到达人数" in ln for ln in D["lines"]))
check("(d) 边界: 4999 被淘汰(不查排行榜), 5001 进入候选排名",
      any("运动达人=4999" in ln for ln in D["lines"])
      and any("运动达人=5001" in ln for ln in D["lines"])
      and "R0S3" not in d_lb_sids
      # ★ 排名日志按达人数降序, R0S4=5001 应当在候选里(桩另外造了 R0S5..R0S9=6000,
      #   它们排在 5001 前面 —— 这正是"取人数最多的"要达到的效果)
      and any("R0S4=5001" in ln for ln in D["lines"]),
      f"采样到的达人数={sorted({ln.split('运动达人=')[1].split()[0] for ln in D['lines'] if '运动达人=' in ln})} "
      f"/ 查过排行榜={sorted(d_lb_sids)}")
check("(d) 未达标的路段没有被拿去查排行榜",
      "R0S0" not in d_lb_sids and "R0S2" not in d_lb_sids,
      f"查过排行榜的路段: {sorted(d_lb_sids)[:4]}")
print("  关键日志:")
show(D["lines"], "运动达人", "读不到达人数", "路段排名", limit=8)

# 缺键 -> 硬性默认值
print()
print("--- 缺键/旧值兜底(界面旧配置仍可能下发 200 / 50 / 8) ---")
F = run_case(target=None, min_athletes=None, max_segments=None,
             auto_regions=False, regions=("New York",))
check("(d) 配置缺键 -> 默认每段 5000 / 每号 200 / 安全上限 40 段",
      any("[quota] 硬性指标: 每号 200 人 / 每段 >= 5000 人 / "
          "环带 100~1000km / 单地区安全上限 40 段" in ln for ln in F["lines"]),
      str(pick(F["lines"], "[quota] 硬性指标", limit=1)))
G = run_case(target=50, min_athletes=200, max_segments=0, auto_regions=False)
check("(d) 旧值 min_athletes=200 -> 抬到 5000 并 log 警告",
      any("[quota] 每段人数门槛 200 低于硬性要求 5000, 已抬到 5000" in ln
          for ln in G["lines"]))
check("(d) 旧值 collect_target_per_account=50 -> 抬到 200 并 log 警告",
      any("[quota] 每号采集目标 50 低于硬性要求 200, 已抬到 200" in ln
          for ln in G["lines"]))
check("(d) 段数上限 0 -> 内部安全上限 40(不是 8)",
      any("单地区安全上限 40 段" in ln for ln in G["lines"]))
print("  关键日志:")
show(G["lines"], "[quota] 每段人数门槛", "[quota] 每号采集目标", "[quota] 硬性指标")

# ==========================================================================
# (e) STOP_EVENT 能打断
# ==========================================================================
print()
print("=" * 78)
print("(e) 用户点停止 -> UserStopped 一路抛出(不被 except Exception 吞掉)")
print("=" * 78)
E = run_case(target=200, stop_after=5)
check("(e) 抛出 UserStopped", isinstance(E["err"], bit.UserStopped), f"err={E['err']!r}")
check("(e) 停止后没有继续把采集跑完",
      E["collected"] is None and len(E["checks"]) <= 6,
      f"停止前只查了 {len(E['checks'])} 人")
# ★ 2.3 起收尾整块搬进 finally: "点停止 / 服务端断开 / 浏览器被关"三条路径都会
#   照常补写 + save_seen + finalize + 统计日志。所以"停止后不再有收尾日志"这条
#   老期望已经过时 —— 新口径是【未达标行照样写(如实记录停止前采到多少),
#   但绝不许出现"达标"】。强度不降反升: 认数字、也认"没有达标"。
check("(e) 停止后收尾照常(finally): 打 [quota] 只采到 N/200 未达标(N<200), 但绝不打达标",
      bool(re.search(r"\[quota\] 只采到 (\d+)/200 未达标", "\n".join(E["lines"])))
      and int(re.search(r"\[quota\] 只采到 (\d+)/200 未达标",
                        "\n".join(E["lines"])).group(1)) < 200
      and not any("[quota] 达标" in ln for ln in E["lines"])
      and any("[region] 完成:" in ln for ln in E["lines"]),
      str(pick(E["lines"], "[quota] 只采到", "[region] 完成", limit=2)))
check("(e) 停止时已采到的条数对得上: [task] 本次任务 N 条 == [quota] 只采到 N/200",
      bool(re.search(r"\[task\] 本次任务 (\d+) 条", "\n".join(E["lines"])))
      and re.search(r"\[task\] 本次任务 (\d+) 条",
                    "\n".join(E["lines"])).group(1)
      == re.search(r"\[quota\] 只采到 (\d+)/200 未达标",
                   "\n".join(E["lines"])).group(1),
      str(pick(E["lines"], "[task] 本次任务", limit=1)))
print("  关键日志(末尾 3 行):")
for ln in E["lines"][-3:]:
    print("   ", ln)

# ==========================================================================
# (g) 领取服务挂掉(ServerDown) -> 必须整体中止, 不能继续跑下一个地区
#     ★ 关键: 引擎只在 cli is not None 时才走"先领后查"那一步(见 collect_regions
#       里 `if cli is not None and aid not in _mine_set`), 所以老写法
#       (claim_raises=True 但 cli=None) 根本碰不到领取代码, 早就测不到了。
#       现在传一个假领取中心, 由【真的】 claim_pick -> cli.claim_batch 抛 ServerDown。
# ==========================================================================
print()
print("=" * 78)
print("(g) 领取中心挂掉 -> ServerDown 整体中止, 不许继续下一个地区(防重复采集)")
print("=" * 78)
_gcl = _FakeCli(raise_serverdown=True)
G2 = run_case(target=200, cli=_gcl)
_g2_headers = [ln for ln in G2["lines"] if "[region] =====" in ln]
check("(g) ServerDown 向上抛出(没被当成'这个地区出错')",
      isinstance(G2["err"], bit.ServerDown), f"err={G2['err']!r}")
check("(g) 真的走到了领取这一步(证明测的是领取挂掉, 不是别的路径)",
      len(_gcl.calls["claim"]) >= 1, f"claim_batch 被调 {len(_gcl.calls['claim'])} 次")
check("(g) 领取挂掉有明确日志 [claim] 领取失败, 采集中止",
      any("[claim] 领取失败, 采集中止" in ln for ln in G2["lines"]),
      str(pick(G2["lines"], "[claim]", limit=1)))
check("(g) 领取挂掉后【没有】再进入下一个地区",
      len(_g2_headers) == 1, f"进入了 {len(_g2_headers)} 个地区: {_g2_headers}")
check("(g) 计划里本来有多个地区可选(证明'没进下一个'是因为中止, 不是没地方去)",
      any("计划扫描 3 个地区" in ln for ln in G2["lines"]),
      str(pick(G2["lines"], "[geo] 计划扫描", limit=1)))
check("(g) 没有掉进 [region] xxx 异常 的兜底(说明不是被 except Exception 吞的)",
      not any("[region]" in ln and "异常:" in ln for ln in G2["lines"]),
      "含'异常:'的 region 日志 = %d 条"
      % sum(1 for ln in G2["lines"] if "[region]" in ln and "异常:" in ln))
check("(g) 没有人'没领到就被查'(checks 为空)",
      len(G2["checks"]) == 0, f"实际查了 {len(G2['checks'])} 人")
print("  关键日志:")
for ln in G2["lines"][-4:]:
    print("   ", ln)

# ★ 领取正常时: 分批领取, 每批 <= CLAIM_CHUNK, 且查了的人都先领过
print()
print("--- 领取中心正常: 分批(<= CLAIM_CHUNK) 且先领后查 ---")
_gok = _FakeCli()
G3 = run_case(target=200, cli=_gok)
_bs = [len(b) for b in _gok.calls["claim"]]
check("(g) 领取分批(每批<=CLAIM_CHUNK), 且查了的人都先领过",
      bool(_bs) and max(_bs) <= bit.CLAIM_CHUNK
      and sum(_bs) == len(G3["checks"]) == 200,
      f"批次={_bs} 领取合计={sum(_bs)} 查了={len(G3['checks'])}")
check("(g) 领取正常时照常达标 200(没有被闸门卡死)",
      len(G3["collected"] or []) == 200 and _gok.calls["collect"],
      f"采到 {len(G3['collected'] or [])} 人")

# ==========================================================================
# (f) 真 check_athlete x 真 geo_cities: 圆心/豁免/下限 端到端
#     (前面几节用的是 geo_cities stub; 这一节把真模块接回来)
# ==========================================================================
print()
print("=" * 78)
print("(f) 真 check_athlete + 真 geo_cities: 纽约豁免上限 / 100km 下限不免 / 不误杀")
print("=" * 78)
sys.modules.pop("geo_cities", None)
import geo_cities as _real_geo                                # noqa: E402

check("(f) 真 geo_cities 已就位(resolve_center/states_in_band/in_target_band)",
      all(hasattr(_real_geo, n) for n in
          ("resolve_center", "states_in_band", "in_target_band", "is_new_york")))
check("(f) 真 states_in_band(芝加哥)确实选不出纽约州(所以纽约必须无条件加)",
      not any(s[1] == "New York"
              for s in _real_geo.states_in_band(41.8781, -87.6298, 100, 1000)))


class _GeoPage:
    """假资料页: evaluate(JS_READ_LOC) 返回指定所在地, 其余返回粉丝/关注数"""
    def __init__(self, loc):
        self.loc = loc

    def evaluate(self, js=None, *a, **k):
        if js == bit.JS_READ_LOC:
            return {"loc": self.loc}
        return {"followers": 10, "following": 20}


def run_check(loc, center, exempt_max):
    _o = {"goto": bit.goto_retry, "wait": bit.wait_text, "STOP": bit.STOP_EVENT}
    bit.goto_retry = lambda *a, **k: None
    bit.wait_text = lambda *a, **k: None
    bit.STOP_EVENT = threading.Event()
    CAP.lines = []
    try:
        return bit.check_athlete(_GeoPage(loc), "999", 200, geo_filter=True,
                                 center=center, exempt_max=exempt_max)
    finally:
        bit.goto_retry, bit.wait_text, bit.STOP_EVENT = (
            _o["goto"], _o["wait"], _o["STOP"])


CHI = (41.8781, -87.6298, "Chicago, IL")
LA = (34.0522, -118.2437, "Los Angeles, CA")
_f1 = run_check("New York, NY", CHI, False)
_l1 = list(CAP.lines)
check("(f) 芝加哥号 + 纽约州的人(1144km), 非纽约路段 -> 淘汰",
      _f1[0] is False, str(_f1))
_f2 = run_check("New York, NY", CHI, True)
check("(f) 同一人走纽约路段(exempt_max=True) -> 保留(豁免上限)",
      _f2[0] is True, str(_f2))
check("(f) [check] 日志打印了圆心/距离/是否豁免",
      any("[check] 999 位置='New York, NY' 圆心=41.88,-87.63" in ln
          and "距离=1144km" in ln and "豁免=是" in ln for ln in _l1 + list(CAP.lines)),
      str(pick(_l1 + list(CAP.lines), "[check]", limit=1)))
_f3 = run_check("Pasadena, CA", LA, True)
check("(f) 洛杉矶号采到 Pasadena(14km): 即使豁免也淘汰(只免上限不免下限)",
      _f3[0] is False, str(_f3))
_f4 = run_check("", CHI, False)
check("(f) 没填所在地 -> 保留(不误杀)", _f4[0] is True, str(_f4))

# 圆心兜底: 认不出 -> 回退配置城市; 都认不出 -> HUBS
_o_cfg = bit.CFG
try:
    bit.CFG = {"location": "Chicago, Illinois"}
    CAP.lines = []
    _r1 = bit.resolve_center_safe("Nowhereville, ZZ")
    check("(f) 本号所在地认不出 -> 回退配置城市 Chicago",
          _r1[3] == "city" and "Chicago" in _r1[2], str(_r1))
    bit.CFG = {"location": "Nowhereville, ZZ"}
    CAP.lines = []
    _r2 = bit.resolve_center_safe("AlsoNowhere, ZZ")
    check("(f) 全都认不出 -> 用 HUBS 兜底并写日志",
          _r2[3] == "hub" and any("兜底用 HUBS" in ln for ln in CAP.lines), str(_r2))
    print("  关键日志:")
    show(CAP.lines, "[geo]", limit=4)
finally:
    bit.CFG = _o_cfg

# ==========================================================================
# (h) detect_home_loc 参数表与 ADS 一致, cached 优先级最高
# ==========================================================================
print()
print("=" * 78)
print("(h) detect_home_loc(page, seq=None, cached=''): cached > 页面现读 > state > CFG")
print("=" * 78)
_o_h = {"ri": bit.read_settings_info, "ls": bit.load_state, "CFG": bit.CFG}
_h = {"ri": 0, "page_loc": "PageTown, IA"}


def _fake_ri(page, timeout=6.0):
    _h["ri"] += 1
    return {"name": "X", "location": _h["page_loc"]}


try:
    bit.read_settings_info = _fake_ri
    bit.load_state = lambda: {"_7": {"location": "StateTown, IN"}}
    bit.CFG = {"location": "ConfigCity, IL"}

    _sig = list(inspect.signature(bit.detect_home_loc).parameters)
    check("(h) 形参表和 ADS 一致: ['page','seq','cached']",
          _sig == ["page", "seq", "cached"], str(_sig))

    _h["ri"] = 0
    _r1 = bit.detect_home_loc(object(), seq="_7", cached="CachedTown, WI")
    check("(h) cached 优先于 页面现读/state/CFG", _r1 == "CachedTown, WI", repr(_r1))
    check("(h) 传了 cached 就不再读资料页(省一次 6 秒轮询)", _h["ri"] == 0,
          f"read_settings_info 被调用 {_h['ri']} 次")

    _r2 = bit.detect_home_loc(object(), seq="_7")
    check("(h) 无 cached 时 页面现读 优先于 state/CFG", _r2 == "PageTown, IA", repr(_r2))

    _h["page_loc"] = ""
    _r3 = bit.detect_home_loc(object(), seq="_7")
    check("(h) 页面读不到 -> 用 state 记录", _r3 == "StateTown, IN", repr(_r3))

    bit.load_state = lambda: {}
    _r4 = bit.detect_home_loc(object(), seq="_7")
    check("(h) 页面+state 都没有 -> 用 CFG['location']", _r4 == "ConfigCity, IL", repr(_r4))

    bit.read_settings_info = lambda page, timeout=6.0: {"location": ""}
    bit.load_state = lambda: {}
    bit.CFG = {}                      # CFG 也没有 -> 四处全空
    _r5 = bit.detect_home_loc(object(), seq="_7", cached="")
    check("(h) 四处全空 -> 返回空串(不抛, 交给 collect_regions 兜底圆心)",
          _r5 == "", repr(_r5))
    print("  关键日志:")
    show(CAP.lines, "[geo] 本号所在地识别", limit=3)
finally:
    bit.read_settings_info = _o_h["ri"]
    bit.load_state = _o_h["ls"]
    bit.CFG = _o_h["CFG"]

# ==========================================================================
# (i)~(m) ★ 自适应缩放: 修掉"放大过头 -> 一个路段都选不出来 -> 采集 0 人"
#   真机实测(AdsPower 会员号 / 纽约州热力图, find_markers 引擎口径)认到的标记:
#     4级38 / 5级38 / 6级56 / 7级56 / 8级56 / 9级21 / 10级1 / 11级及以上 0
#   旧口径"最多放 14 级 + 看到标记后再多放 4 级"会一路放到 0 个 -> 采集 0 人。
#   新口径: 边放边数, 停在标记最多的那一级; 明显变差立刻停, 并回退到最佳级别。
#   假页面: 进来时在第 _START 级, 每滚一次 -500 进一级(绝对级别)。
# ==========================================================================
def _zoom_markers(table, default=0):
    """按【绝对缩放级别】给标记坐标; 表里写 None 表示这一级截图失败(返回 None)"""
    def fn(page):
        n = table.get(page.zoom, default)
        if n is None:
            return None
        base = page.zoom * 100
        return [(base + 50 + i * 37, base + 50 + i * 41) for i in range(n)]
    return fn


def _zoom_log(lines):
    for ln in lines:
        if "自适应缩放" in ln:
            return ln
    return ""


print()
print("=" * 78)
print("(i) 自适应缩放: 边放边数, 变差立刻停 + 回退到最佳级别(不再放大到 0 个标记)")
print("=" * 78)
# 标记序列 [1,1,38,56,56,56,21,1,0,0] 对应绝对级别 3..12:
#   绝对 6/7/8 级 = 56 个(真机最好的那一级), 9 级掉到 21, 11 级起 0 个。
_START, _PEAK = 2, 6            # 进来时第 2 级; 真机口径最好的一级 = 绝对 6 级(56 个)
_Z_TABLE = {3: 1, 4: 1, 5: 38, 6: 56, 7: 56, 8: 56, 9: 21, 10: 1, 11: 0, 12: 0}
I = run_case(target=200, markers_fn=_zoom_markers(_Z_TABLE), start_zoom=_START)
_i_log = _zoom_log(I["lines"])
_i_in, _i_out = I["page"].zooms.count("in"), I["page"].zooms.count("out")
_i_best = re.search(r"最佳 (\d+) 级\((\d+) 个标记\)", _i_log)
_i_cur = re.search(r"现在停在 (\d+) 级", _i_log)
check("(i) 没有一路放大到上限 12: 9 级一掉到 21 就停了(只放 7 次)",
      _i_in == 7 and _i_out == 3,
      f"放大 {_i_in} 次 / 缩小 {_i_out} 次 / 最终绝对级别={I['page'].zoom}")
check("(i) 回退到标记最多的那一级: 绝对 6 级 / 56 个(真机最好的那一级)",
      I["page"].zoom == _PEAK and bool(_i_best) and _i_best.group(2) == "56",
      f"最终绝对级别={I['page'].zoom}, 日志={_i_log}")
check("(i) 最终级别 == 最佳级别(引擎口径: 停在4级 = 绝对6级)",
      bool(_i_best and _i_cur) and _i_best.group(1) == _i_cur.group(1)
      and _i_cur.group(1) == str(_PEAK - _START),
      f"最佳={_i_best.group(1) if _i_best else '?'}级 / "
      f"停在={_i_cur.group(1) if _i_cur else '?'}级")
check("(i) 变差时明确 log 并停止放大: 标记开始变少(56->21)",
      any("标记开始变少(56->21), 停止放大" in ln for ln in I["lines"]))
check("(i) 全程没有出现'标记0个'(旧逻辑会放大到 0 个 -> 一个路段都选不出来)",
      not any(re.search(r"标记0个", ln) for ln in I["lines"]))
check("(i) 回退后又确认了一次(56 个标记)才开始平移找路段",
      any(f"回退到{_PEAK - _START}级后确认56个标记, 开始平移找路段" in ln
          for ln in I["lines"]),
      str(pick(I["lines"], "回退到", limit=1)))
check("(i) 该地区照常平移找路段并采到达标 200",
      I["page"].pans >= 1 and len(I["collected"] or []) == 200,
      f"平移 {I['page'].pans} 轮, 采到 {len(I['collected'] or [])} 人")
print("  关键日志:")
show(I["lines"], "第5级", "第6级", "第7级", limit=3)
show(I["lines"], "标记开始变少", "自适应缩放", "回退到", limit=3)

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(j) 截图失败(None) ≠ 0 个标记: 不计入比较, 不改变最佳级别, 不提前回退")
print("=" * 78)
# ★ ZOOM_MIN_STEPS=6: "变差就停"至少要放到第 6 级才允许判(浅层标记多但多是重叠的
#   小路段)。所以本用例把"真掉到 21"安排在第 6 级:
#   绝对 3 级 56 个(最佳) -> 4/5 级截图失败(未知) -> 6/7 级还是 56 -> 8 级掉到 21
_J_TABLE = {3: 56, 4: None, 5: None, 6: 56, 7: 56, 8: 21}
J = run_case(target=200, markers_fn=_zoom_markers(_J_TABLE, default=0),
             start_zoom=_START)
_j_log = _zoom_log(J["lines"])
_j_best = re.search(r"最佳 (\d+) 级\((\d+) 个标记\)", _j_log)
check("(j) 两次截图失败都记成'未知, 不计入比较'",
      sum(1 for ln in J["lines"] if "截图失败(未知), 不计入比较" in ln) == 2)
check("(j) None 没被当成 0 个标记(否则会立刻 '标记开始变少(56->0)')",
      not any("标记开始变少(56->0)" in ln for ln in J["lines"]),
      str(pick(J["lines"], "标记开始变少", limit=2)))
check("(j) None 不改变 best_level: 仍是绝对 3 级/56 个, 一路放到第 6 级才因 21 停",
      bool(_j_best) and _j_best.group(1) == str(3 - _START) and _j_best.group(2) == "56"
      and J["page"].zooms.count("in") == 6,
      f"最佳={_j_best.group(0) if _j_best else '?'}, 放大 {J['page'].zooms.count('in')} 次")
check("(j) 变差判定用的是真实标记数(56->21), 且在第 6 级才判(不提前回退)",
      any("标记开始变少(56->21), 停止放大" in ln for ln in J["lines"])
      and sum(1 for ln in J["lines"] if "标记开始变少" in ln) == 1
      and any("第5级 标记56个" in ln for ln in J["lines"]))
check("(j) 回退到 56 个那一级(绝对 3 级)并确认", J["page"].zoom == 3
      and any("回退到1级后确认56个标记, 开始平移找路段" in ln for ln in J["lines"]),
      f"最终绝对级别={J['page'].zoom}, 日志={_j_log}")
print("  关键日志:")
show(J["lines"], "截图失败(未知)", "标记开始变少", "自适应缩放", limit=3)

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(j2) ZOOM_MIN_STEPS=6: 第 2~5 级就变差也不许停, 放到第 6 级才判")
print("=" * 78)
# 绝对 3 级 56 个 -> 4 级就掉到 6 个: 引擎必须继续放到第 6 级才允许"变少就停"
J2 = run_case(target=200, markers_fn=_zoom_markers({3: 56}, default=6),
              start_zoom=_START)
check("(j2) 第2~5级(56->6)不算数: 一路放到第 6 级才 '标记开始变少(56->6)' 停",
      J2["page"].zooms.count("in") == 6
      and any("第5级 标记6个" in ln for ln in J2["lines"])
      and any("标记开始变少(56->6), 停止放大" in ln for ln in J2["lines"]),
      f"放大 {J2['page'].zooms.count('in')} 次")
check("(j2) 最佳级别仍是绝对 3 级(56 个), 最终回退到 3 级",
      J2["page"].zoom == 3
      and any("最佳 1 级(56 个标记), 现在停在 1 级" in ln for ln in J2["lines"]),
      _zoom_log(J2["lines"]))

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(k) 全程截图失败(None): 不崩, 8 级上限 + 死地区最多试 3 轮(不再磨满 16 轮)")
print("=" * 78)
K = run_case(target=200, markers_fn=lambda page: None, start_zoom=0,
             auto_regions=False, regions=("New York",))
check("(k) 全程 None 不崩(err=None)", K["err"] is None, f"err={K['err']!r}")
check("(k) 放大级数上限 = ZOOM_MAX_STEPS(8): 8 级全失败后回退 8 次(最佳=0 级)",
      K["page"].zooms.count("in") == bit.ZOOM_MAX_STEPS == 8
      and K["page"].zooms.count("out") == 8
      and "最佳 0 级(0 个标记), 现在停在 0 级" in _zoom_log(K["lines"]),
      _zoom_log(K["lines"]))
check("(k) 回退后确认失败 -> warning 且明确'不跳过该地区'",
      any("回退到0级后截图失败(标记未知), 不跳过该地区, 继续平移找" in ln
          for ln in K["lines"]))
# ★ 2.11: 平移轮数 16 -> PAN_ROUNDS(8); ★ 第二批 §2: 死地区在平移阶段最多试 3 轮
check("(k) 平移按 PAN_ROUNDS=8 计轮, 死地区最多试 3 轮(每轮 None 都只 warning, 不许 break)",
      K["page"].pans == 2
      and sum(1 for ln in K["lines"] if "本轮不点标记, 继续下一轮" in ln) == 3
      and any("死地区, 最多试 3 轮" in ln for ln in K["lines"])
      and not any(re.search(r"第4轮 截图失败", ln) for ln in K["lines"]),
      f"平移 {K['page'].pans} 轮, None warning "
      f"{sum(1 for ln in K['lines'] if '本轮不点标记, 继续下一轮' in ln)} 条")
# ★★ 铁律: mk is None = 截图失败 = 标记数【未知】, 绝不算"空地区"
#    (算进去的话连跑 4 个截图故障的地区就会白白中止一整轮采集)
check("(k) 截图失败(未知) 不算空地区: 不打'零标记零路段'/不触发'连续 4 个空地区'",
      not any("零标记零路段" in ln for ln in K["lines"])
      and not any("连续 4 个空地区" in ln for ln in K["lines"]))
check("(k) 没标记就不点、不采(没有路段被采用, 也没崩)", K["lb_calls"] == [])
check("(k) 跑完仍然正常收尾(未达标)", (K["collected"] or []) == []
      and any("[quota] 只采到 0/200 未达标" in ln for ln in K["lines"]))
print("  关键日志:")
show(K["lines"], "截图失败(未知)", "不跳过该地区", "未达标", limit=3)

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(l) 回退后标记 <3 个: warning 但【不跳过该地区】, 继续平移找路段")
print("=" * 78)
_l_calls = {"n": 0}


def _l_markers(page):
    """自适应阶段(前 2 次): 绝对 3 级 56 个 -> 4 级 21 个; 之后(回退确认+平移): 只剩 2 个"""
    _l_calls["n"] += 1
    n = ({3: 56, 4: 21}.get(page.zoom, 0) if _l_calls["n"] <= 2 else 2)
    base = page.zoom * 100
    return [(base + 50 + i * 37, base + 50 + i * 41) for i in range(n)]


L = run_case(target=200, markers_fn=_l_markers, start_zoom=_START)
check("(l) 回退后只有 2 个标记(<3) -> warning 且明确'不跳过该地区'",
      any("回退到1级后只有2个标记(<3), 不跳过该地区, 继续平移找" in ln
          for ln in L["lines"]),
      str(pick(L["lines"], "回退到", limit=1)))
check("(l) 该地区没有被跳过: 平移按 PAN_ROUNDS=8 照跑(每轮 1 次拖拽)",
      L["page"].pans == 8
      # ★ 2026-09-19: 平移轮日志已与 ADS 版统一为「第N/PAN_ROUNDS轮」
      #   (原来是 BIT 独有的「第N轮」, 双胞胎日志口径不一致)。
      and sum(1 for ln in L["lines"] if re.search(r"第\d+/8轮 标记", ln)) == 8
      and not any("死地区" in ln for ln in L["lines"]),
      f"平移 {L['page'].pans} 轮, "
      f"轮次日志={sum(1 for ln in L['lines'] if re.search(r'第\d+/8轮 标记', ln))}")
check("(l) 标记少也能继续采: 2 个路段仍被采用并采到达标 200",
      len(L["lb_calls"]) > 0 and len(L["collected"] or []) == 200,
      f"查排行榜 {len(L['lb_calls'])} 次, 采到 {len(L['collected'] or [])} 人")
print("  关键日志:")
show(L["lines"], "回退到", "采用", limit=3)

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(m) 源码静态核查: 4 个 find_markers( 调用点都区分 None; 死代码清干净")
print("=" * 78)
_SRC = (ROOT / "主脚本" / "strava_bit.py").read_text(encoding="utf-8").splitlines()
_CALLS = [i for i, ln in enumerate(_SRC) if "find_markers(page)" in ln]
check("(m) 调用点 4 个: 自适应循环 / 回退确认 / 平移轮 / 旧 collect_users",
      len(_CALLS) == 4, f"第 {[i + 1 for i in _CALLS]} 行")
check("(m) 每个调用点紧跟着 '... is None' 判定",
      all(any(("is None" in _SRC[j] or "is not None" in _SRC[j])
              for j in range(i, min(i + 3, len(_SRC))))
          for i in _CALLS),
      f"第 {[i + 1 for i in _CALLS]} 行")
_d = next(i for i, ln in enumerate(_SRC) if ln.startswith("def find_markers("))
_blk = "\n".join(_SRC[_d:_d + 40])
check("(m) find_markers: 单次截图 timeout=8000(不再是 12000), 且只重试 2 轮",
      "page.screenshot(timeout=8000)" in _blk and "for _try in range(2)" in _blk
      and "timeout=12000" not in _blk and "timeout=20000" not in _blk,
      str(pick(_blk.splitlines(), "screenshot(", limit=1)))
check("(m) find_markers: 全失败 -> log.warning + return None(不是 [])",
      "return None" in _blk and "Playwright + CDP 都截不到" in _blk
      and not any(ln.strip() == "return []" for ln in _SRC[_d:_d + 40]))
check("(m) ZOOM_MAX_STEPS = 8(旧的 12/14 已改) + ZOOM_MIN_STEPS = 6, 无 ZOOM_EXTRA_STEPS",
      any(ln.strip().startswith("ZOOM_MAX_STEPS = 8") for ln in _SRC)
      and any(ln.strip().startswith("ZOOM_MIN_STEPS = 6") for ln in _SRC)
      and not any("ZOOM_EXTRA_STEPS" in ln for ln in _SRC))
check("(m) 旧缩放逻辑(见标记后再多放大 4 级)已彻底删掉",
      not any(k in ln for ln in _SRC for k in ("_first_z", "再放大4级", "缩放完成")))
check("(m) 平移轮数 = PAN_ROUNDS = 8(不再写死 16), 且 ENOUGH_SEGMENTS = 12(采样目标)",
      any(ln.strip().startswith("PAN_ROUNDS = 8") for ln in _SRC)
      and any(ln.strip().startswith("ENOUGH_SEGMENTS = 12") for ln in _SRC)
      and any("for rnd in range(PAN_ROUNDS)" in ln for ln in _SRC)
      and not any("range(16)" in ln for ln in _SRC))
# ★ 2026-09-19 用户要求"精准找每个州人数最多的路段": 按达人数排名, 不再先到先得
_all_src_bit = "\n".join(_SRC)
check("(m) 选路段改成【按运动达人数排名取最大】",
      "seg_cands" in _all_src_bit and "_ranked = sorted(" in _all_src_bit
      and "seg_cands[sid] = n_ath" in _all_src_bit)
check("(m) 达人数与粉丝数读取支持中文界面",
      "运动达人" in _all_src_bit and "关注者" in _all_src_bit)
check("(m) 选路段点击后是有界轮询 wait_text(timeout=1.8), 不再固定 sleep(1.8)",
      any('timeout=1.8, key="segpop"' in ln for ln in _SRC)
      and not any("time.sleep(1.8)" in ln for ln in _SRC))
check("(m) 风控闸门 rate_gate 已接管 nav/api/act(4 个调用点), 间隔 6.0/1.5/0.6",
      sum(1 for ln in _SRC if 'rate_gate("' in ln) >= 4
      and (bit.RATE_NAV_SEC, bit.RATE_API_SEC, bit.RATE_ACT_SEC) == (6.0, 1.5, 0.6))
check("(m) 单号时间预算 collect_max_minutes + 死地区跳过(连续 4 个空地区) 都在源码里",
      any("collect_max_minutes" in ln for ln in _SRC)
      and any("已达单号时间上限" in ln for ln in _SRC)
      and any("连续 4 个空地区" in ln for ln in _SRC)
      and any("死地区, 最多试 3 轮" in ln for ln in _SRC))
check("(m) 任务文件/极致去重链路都在: TASK_FILE_PREFIX / append_task_url / _out_index",
      any("TASK_FILE_PREFIX" in ln for ln in _SRC)
      and any(ln.startswith("def append_task_url(") for ln in _SRC)
      and any(ln.startswith("def _out_index(") for ln in _SRC))
check("(m) 硬性地板/纽约必扫都没动",
      any("MIN_ATHLETES_FLOOR = 5000" in ln for ln in _SRC)
      and any("TARGET_FLOOR = 200" in ln for ln in _SRC)
      and any('_add_region("New York", True)' in ln for ln in _SRC))

# --------------------------------------------------------------------------
print()
print("=" * 78)
print("(n) 真 find_markers(不桩): 截到图没标记=[]; 两轮超时=None; 第2轮成功=取到标记")
print("=" * 78)
import io as _io                                        # noqa: E402
from PIL import Image as _Image                         # noqa: E402
from PIL import ImageDraw as _ImageDraw                 # noqa: E402


def _png(n):
    """造假截图: 画 n 个 Strava 橙圆点(60<=面积<=900 / 长宽比1 / 填充率~0.7 都过判定)

    左上角 160x200 会被 find_markers 当界面元素挖掉, 所以圆点画在中下部。
    """
    im = _Image.new("RGB", (1280, 720), (25, 25, 25))
    d = _ImageDraw.Draw(im)
    for i in range(n):
        cx, cy = 420 + i * 60, 420
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(252, 76, 2))
    buf = _io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class _ShotPage:
    """假 page: screenshot 按脚本"返图 / 抛超时", 并记录传进来的 timeout

    cdp=PNG 时额外提供一个"能用的"假 CDP 会话(context.new_cdp_session),
    用来验证 Playwright 超时后 CDP 兜底真的能把图救回来。
    """
    class _M:
        def move(self, *a, **k):
            pass

        def wheel(self, *a, **k):
            pass

    def __init__(self, script, cdp=None):
        self.script = list(script)
        self.cdp = cdp
        self.calls = 0
        self.timeouts = []
        self.mouse = _ShotPage._M()

    def screenshot(self, *a, **k):
        self.calls += 1
        self.timeouts.append(k.get("timeout"))
        v = self.script[min(self.calls - 1, len(self.script) - 1)]
        if isinstance(v, Exception):
            raise v
        return v

    @property
    def context(self):
        _p = self

        class _Ctx:
            def new_cdp_session(self, _page):
                class _Sess:
                    def send(self, _m, _a=None):
                        import base64 as _b
                        return {"data": _b.b64encode(_p.cdp).decode()}
                return _Sess()
        return _Ctx()


_o_n = {"sleep": bit.sleep_or_stop, "stop": bit.STOP_EVENT}
bit.sleep_or_stop = lambda *a, **k: None            # 重试间隔的 2/4 秒不必真等
bit.STOP_EVENT = threading.Event()
try:
    CAP.lines = []
    _p_ok = _ShotPage([_png(5)])
    _r_ok = bit.find_markers(_p_ok)
    check("(n) 截到图且认出 5 个橙点 -> 返回 list(5 个), 不是 None",
          isinstance(_r_ok, list) and len(_r_ok) == 5 and _p_ok.calls == 1,
          f"返回 {type(_r_ok).__name__}/{len(_r_ok or [])} 个, 截图 {_p_ok.calls} 次")
    check("(n) 单次截图 timeout=8000(不再是 12000)",
          _p_ok.timeouts == [8000], str(_p_ok.timeouts))

    CAP.lines = []
    _p_empty = _ShotPage([_png(0)])
    _r_empty = bit.find_markers(_p_empty)
    check("(n) 截到图但一个标记都没有 -> 返回 [](空 list, 表示'确实没标记')",
          _r_empty == [] and _r_empty is not None, f"返回 {_r_empty!r}")

    CAP.lines = []
    _p_to = _ShotPage([TimeoutError("Timeout 8000ms exceeded.")])
    _r_to = bit.find_markers(_p_to)
    check("(n) 两轮(Playwright+CDP)都拿不到 -> 返回 None(不是 []), 且只截 2 次",
          _r_to is None and _p_to.calls == 2, f"返回 {_r_to!r}, 截图 {_p_to.calls} 次")
    check("(n) 两轮失败有 log.warning(含轮次与'标记数未知(返回 None)')",
          any("[markers] Playwright 截图失败(1/2)" in ln for ln in CAP.lines)
          and any("[markers] Playwright 截图失败(2/2)" in ln for ln in CAP.lines)
          and any("Playwright + CDP 都截不到" in ln for ln in CAP.lines),
          str(pick(CAP.lines, "[markers]", limit=2)))

    CAP.lines = []
    _p_retry = _ShotPage([TimeoutError("t"), _png(2)])
    _r_retry = bit.find_markers(_p_retry)
    check("(n) 第 1 轮超时、第 2 轮成功 -> 返回 2 个标记(重试真的救回来了)",
          isinstance(_r_retry, list) and len(_r_retry) == 2 and _p_retry.calls == 2,
          f"返回 {_r_retry!r}, 截图 {_p_retry.calls} 次")

    CAP.lines = []
    _p_cdp = _ShotPage([TimeoutError("t")], cdp=_png(2))
    _r_cdp = bit.find_markers(_p_cdp)
    check("(n) Playwright 超时 -> CDP 兜底抓到图 -> 返回 2 个标记(不是 None)",
          isinstance(_r_cdp, list) and len(_r_cdp) == 2 and _p_cdp.calls == 1,
          f"返回 {_r_cdp!r}, 截图 {_p_cdp.calls} 次")
finally:
    bit.sleep_or_stop = _o_n["sleep"]
    bit.STOP_EVENT = _o_n["stop"]

# ==========================================================================
# (o) 风控闸门 rate_gate
# ==========================================================================
print()
print("=" * 78)
print("(o) 风控闸门 rate_gate: nav 6.0s / api 1.5s / act 0.6s, 走 sleep_or_stop(可打断)")
print("=" * 78)
check("(o) 闸门间隔: nav 6.0s / api 1.5s / act 0.6s",
      (bit._RATE["nav"]["min_gap"], bit._RATE["api"]["min_gap"],
       bit._RATE["act"]["min_gap"]) == (6.0, 1.5, 0.6)
      and set(bit._RATE) == {"nav", "api", "act"},
      f"{ {k: v['min_gap'] for k, v in bit._RATE.items()} }")
_waits = []
_so_o = bit.sleep_or_stop
bit.sleep_or_stop = lambda sec: _waits.append(sec)
try:
    # ★ 2026-09-19 并发改造后必须显式清作用域: 前面的场景跑过 collect_regions,
    #   已经把"本线程的账号作用域"设上了; 不清的话 rate_gate 会走【按号桶】,
    #   下面写进默认桶的 last 就被忽略。
    bit.set_rate_scope("")
    bit._RATE_BUCKETS.clear()
    bit._RATE["act"]["last"] = _RealTime.time()          # 刚放过一个动作
    bit.rate_gate("act")                                # 紧接着再来一个 -> 必须补等
    bit._RATE["api"]["last"] = _RealTime.time() - 99     # 早就冷却好了
    bit.rate_gate("api")                                # -> 不该等
finally:
    bit.sleep_or_stop = _so_o
check("(o) 超速补等(相邻动作 <0.6s 必须等), 且等待走 sleep_or_stop(= 停止键可打断)",
      len(_waits) == 1 and 0 < _waits[0] <= 0.6, f"等待={_waits}")
# ★ 新增: 按号分桶 —— 每个号各有一份独立预算(用户要的"并发真并行")
_waits2 = []
bit.sleep_or_stop = lambda sec: _waits2.append(sec)
try:
    bit._RATE_BUCKETS.clear()
    bit.set_rate_scope("seq3")
    bit.rate_gate("act")            # 号3 用掉一次
    bit.set_rate_scope("seq4")
    bit.rate_gate("act")            # 号4 紧接着 -> 【不该等】(各自一份预算)
    bit.set_rate_scope("seq3")
    bit.rate_gate("act")            # 号3 再来 -> 【必须补等】
finally:
    bit.sleep_or_stop = _so_o
check("(o) 按号分桶: 号4 不受号3 的额度影响, 但号3 自己第二次要补等",
      len(_waits2) == 1 and 0 < _waits2[0] <= 0.6, f"等待={_waits2}")
bit.set_rate_scope("")
bit._RATE_BUCKETS.clear()
print("  关键日志: 闸门不走日志, 只体现在上面的等待上")

# ==========================================================================
# (p) 单号时间预算 collect_max_minutes
# ==========================================================================
print()
print("=" * 78)
print("(p) 单号时间预算: 缺省 240 分钟 / 配置值生效; 到点 [quota] 已达单号时间上限 N 分钟")
print("=" * 78)
P = run_case(target=200, cfg_extra=None, clock_step=15000,
             auto_regions=False, regions=("New York",))
check("(p) 缺省预算 = 240 分钟: 到点打 [quota] 已达单号时间上限 240 分钟 并 break",
      P["err"] is None and (P["collected"] or []) == []
      and any("[quota] 已达单号时间上限 240 分钟, 停止采集" in ln for ln in P["lines"])
      and not [ln for ln in P["lines"] if "[region] =====" in ln],
      str(pick(P["lines"], "[quota] 已达", limit=1)))
P2 = run_case(target=200, cfg_extra={"collect_max_minutes": 1}, clock_step=61,
              auto_regions=False, regions=("New York",))
check("(p) 配置 collect_max_minutes=1 生效: 上限 1 分钟就停, 不进任何地区",
      P2["err"] is None and (P2["collected"] or []) == []
      and any("[quota] 已达单号时间上限 1 分钟, 停止采集" in ln for ln in P2["lines"])
      and not [ln for ln in P2["lines"] if "[region] =====" in ln],
      str(pick(P2["lines"], "[quota] 已达", limit=1)))

# ==========================================================================
# (q) 死地区跳过: 零标记 -> 跳过平移; 连续 4 个 -> 停止采集
# ==========================================================================
print()
print("=" * 78)
print("(q) 死地区跳过: 零标记地区不磨平移; 连续 4 个空地区 -> [region] 连续 4 个空地区")
print("=" * 78)
Q = run_case(target=200, markers_fn=_zoom_markers({}, default=0), start_zoom=0,
             auto_regions=False,
             regions=("New York", "Ohio", "Iowa", "Kansas"))
_q_regs = [ln for ln in Q["lines"] if "[region] =====" in ln]
check("(q) 零标记地区直接跳过平移(不打第N/8轮), 连续 4 个 -> 停止采集",
      Q["err"] is None and (Q["collected"] or []) == [] and len(_q_regs) == 4
      and sum(1 for ln in Q["lines"] if "零标记零路段, 跳过平移" in ln) == 4
      and any("[region] 连续 4 个空地区, 停止采集" in ln for ln in Q["lines"])
      and not any(re.search(r"第\d+/8轮", ln) for ln in Q["lines"]),
      f"进了 {len(_q_regs)} 个地区")
check("(q) 跳过不是崩溃: 正常收尾(未达标), 没有 [region] 异常",
      any("[quota] 只采到 0/200 未达标" in ln for ln in Q["lines"])
      and not any("[region]" in ln and "异常:" in ln for ln in Q["lines"]))

# ==========================================================================
# (r) 任务文件契约
# ==========================================================================
print()
print("=" * 78)
print("(r) 任务文件: 号级明细 collected_users_<tid>_7.txt + 任务成品 collected_users_<tid>.txt")
print("=" * 78)
R = run_case(target=200)
_r_files = R["iso"]["files"]
check("(r) 两个文件都在, 名字符合 任务成品/号级明细 规格",
      len([f for f in _r_files if f.endswith("_7.txt")]) == 1
      and len([f for f in _r_files if not f.endswith("_7.txt")]) == 1
      and all(re.fullmatch(r"collected_users_\d{8}_\d{6}(_7)?\.txt", f)
              for f in _r_files),
      f"files={_r_files}")
check("(r) 首行都是 '# 任务开始 ...', 数据行是纯链接(无附加列/无额外信息)",
      R["iso"]["hdr_ok"] and R["iso"]["end_ok"] and R["iso"]["same"],
      f"hdr={R['iso']['hdr_ok']} end={R['iso']['end_ok']} url={R['iso']['urls']}")
check("(r) 任务文件里的 URL 数 == 本次 collected 数(200)",
      R["iso"]["urls"] == 200 and R["iso"]["expect"] == 200,
      f"url={R['iso']['urls']} expect={R['iso']['expect']}")

# ==========================================================================
# (s) append_task_url: 写前判重 / 落盘失败不报 pass
# ==========================================================================
print()
print("=" * 78)
print("(s) 极致去重 append_task_url: 历史已有 -> False 不计数; 落盘失败 -> write_err 且不报 pass")
print("=" * 78)
_unit = TMP / "unit_task"
_unit.mkdir(parents=True, exist_ok=True)
_out_o, _seen_o = bit.COLLECT_OUT, bit.COLLECT_SEEN
bit.COLLECT_OUT = _unit / "collected.txt"
bit.COLLECT_SEEN = _unit / "seen.json"
try:
    if hasattr(bit, "_OUT_HAVE"):
        bit._OUT_HAVE["built"] = False
        bit._OUT_HAVE["set"] = set()
    _t1 = bit.new_task_ctx(target=200, mode="selftest")
    _s1 = bit.new_account_ctx(_t1, "7")
    _u = "https://www.strava.com/athletes/unit1"
    _w1 = bit.append_task_url(_s1, _u)
    _w2 = bit.append_task_url(_s1, _u)
    _n1 = sum(1 for x in _s1["path"].read_text(encoding="utf-8").splitlines()
              if x and not x.startswith("#"))
    check("(s) 首写返回 True; 同一条第二次写返回 False 且不落第二行",
          _w1 is True and _w2 is False and _n1 == 1, f"{_w1}/{_w2}/行数{_n1}")
    if hasattr(bit, "_OUT_HAVE"):
        bit._OUT_HAVE["built"] = False               # 模拟下一次任务重建索引
        bit._OUT_HAVE["set"] = set()
    _s2 = bit.new_account_ctx(bit.new_task_ctx(target=200, mode="selftest"), "8")
    _w3 = bit.append_task_url(_s2, _u)
    check("(s) 历史成果里已有(重建索引后) -> 返回 False(极致去重: 不计数不重写)",
          _w3 is False, f"返回={_w3}")
    _bad = {"t_start": _s2["t_start"], "tid": "99990101_000000", "seq": "9",
            "urls": {}, "path": _unit}               # path 是目录 -> 写入必失败
    _w4 = bit.append_task_url(_bad, "https://www.strava.com/athletes/unit2")
    check("(s) 落盘失败(路径是目录) -> 返回 False 且 ctx['write_err'] 有值 + 日志",
          _w4 is False and bool(_bad.get("write_err"))
          and any("[task] 落盘失败" in ln for ln in CAP.lines),
          f"返回={_w4} write_err={str(_bad.get('write_err'))[:40]!r}")
finally:
    bit.COLLECT_OUT, bit.COLLECT_SEEN = _out_o, _seen_o
    shutil.rmtree(_unit, ignore_errors=True)

_cli_s = _FakeCli()
S = run_case(target=200, cli=_cli_s, broken_write=True)
_s_pass = [c for c in _cli_s.calls["finish"] if len(c[0]) > 1 and c[0][1] == "pass"]
check("(s) 落盘失败: 不计数(0 条) + 日志'落盘失败, 本条不上报中心'",
      (S["collected"] or []) == []
      and any("落盘失败, 本条不上报中心" in ln for ln in S["lines"]),
      f"采到 {len(S['collected'] or [])} 人")
check("(s) 落盘失败时没有给中心报 pass / 没写 collect(防'中心说采到了、本地没有')",
      _s_pass == [] and _cli_s.calls["collect"] == [],
      f"pass上报={len(_s_pass)} collect={len(_cli_s.calls['collect'])}")

# ==========================================================================
print()
print("=" * 78)
_ok = sum(1 for _n, c in RESULT if c)
print(f"自测结果: {_ok}/{len(RESULT)} 通过")
for n, c in RESULT:
    if not c:
        print("   FAIL:", n)
print("=" * 78)
try:
    logging.shutdown()          # ★ 先关掉引擎日志的文件句柄, 否则 Windows 删不掉临时目录
    shutil.rmtree(TMP, ignore_errors=True)      # 清掉自测临时目录
except Exception:
    pass
print(f"临时目录: {TMP} {'(已清理)' if not TMP.exists() else '(未能清理, 可手动删)'}")
sys.exit(0 if _ok == len(RESULT) else 1)
