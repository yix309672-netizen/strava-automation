#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自测: 用假 page + 桩函数【真跑】strava_ads.collect_regions

不联网、不启动指纹浏览器、不碰真实账号、不发外部请求。
被测对象: 主脚本/strava_ads.py 的新口径区域采集(用户第2/3/4条)

覆盖:
  (a) 合格数到 200 立刻停(不会多采)
  (b) 一个地区不够会继续下一个地区; 跑完不够会 log 未达标
  (c) 扫纽约时 check_athlete 收到 exempt_max=True / 别的州 False; 圆心=该号所在地
  (d) 段人数 4000 的路段被跳过, 5000+ 的采用, 读不到人数(-1)也跳过
  (e) STOP_EVENT 置位后 UserStopped 能打断(停止立即生效)
  (f) cli.finish 抛 ServerDown -> 整体中止(不退化成"本地去重继续跑")
  (g) 旧值兜底: min_athletes=200 / target=50 被抬到 5000 / 200
  (h) 真 check_athlete + 真 geo_cities: 纽约来源豁免上限、太近照样淘汰
  (i) fetch_lb_filtered 默认翻页数 = 配置 lb_max_pages(默认 8)
  (j) detect_home_loc 优先级: 页面真实 location > state > CFG
  (S1)~ (S5) ★★ 自适应缩放(真机缺陷修复): 放大过头(11级后0个标记) -> 变差就停 + 回退到
       最佳级别; 截图失败(None) 不算 0、不改最佳级别; 全程失败也不崩、不跳过地区
  (S6) 真 find_markers 返回值三态: Playwright 2 次(各 8000ms) + CDP 兜底都拿不到
       -> None(不是 []); 截到空图 -> []; CDP 兜底救回来 -> 正常标记
  (S7) 真 popup_athletes: 读不到(-1)/读到 0/类型异常 都归一成 -1, 日志区分两种无效读数
  (S8) 常量口径(2.11 提速): PAN_ROUNDS=8 / ENOUGH_SEGMENTS=4 / ZOOM_MAX_STEPS=8 /
       ZOOM_MIN_STEPS=6, 且源码里 16 轮、12000ms 这类旧值已清干净
  (S9) 风控闸门 rate_gate: nav/api/act 最小间隔 6.0/1.5/0.6 秒, 且走 sleep_or_stop(可打断)
  (S10) 单号时间预算 collect_max_minutes: 缺省 240 分钟 / 配置值生效, 到点打
       [quota] 已达单号时间上限 N 分钟 并 break
  (S11) 死地区跳过: 零标记(且最佳级别也零标记) -> 跳过平移; 连续 4 个 -> 停止采集;
        mk is None(截图失败=未知) 绝不算空地区
  (S12) 任务文件: 任务成品 collected_users_<tid>.txt + 号级明细 _<号>.txt, 首行 # 任务开始
  (S13) append_task_url: 写前判重(历史已有 -> False 不计数); 落盘失败设 ctx["write_err"]
        且不向中心报 pass
  (iso1)~(isoN) ★ 场景隔离: 每个场景一个独立空目录(引擎 _out_index 会扫 COLLECT_OUT.parent
       下的任务文件, 共用目录会让上一场景的成果把下一场景全判成"历史已有"), 场景末尾断言
       "本场景目录里的 collected_users_*.txt 只属于本场景 + 目录外零新建"

用法: python _自测_采集_ADS.py     (退出码 0=全过, 1=有失败)
"""
import logging
import re
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "主脚本"))
import strava_ads as A            # noqa: E402  (必须在 sys.path 之后)

_real_time = time                 # 真 time 模块(后面要拿它做假时钟的委托对象)

TMP = ROOT / "_自测_临时"
if TMP.exists():
    shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

# ================================================================ ★ 场景隔离
# 为什么必须隔离(2026-09-19 改造后): 引擎新增的"极致去重"索引 _out_index() 扫的是
#   COLLECT_OUT 本身 **以及 COLLECT_OUT.parent 下所有 collected_users_*.txt 任务文件**。
#   老自测让所有场景共用 _自测_临时/out.txt, 于是上一场景留在同一目录里的任务成品/
#   号级明细会被下一场景重建索引时读进来 —— 同一批假 athlete id(a3000…)立刻被判成
#   "历史已有", collected 恒为 0(实测 _自测_采集_ADS.log 里 3586 行
#   "本地已有, 跳过不计数")。
#   生产上"交付过的绝不再交付"正是用户要的极致去重, 所以这【不是引擎 bug】——
#   是测试必须给每个场景一个干净目录。下面 TMP/sc<N>/ 就是那个目录。
TASK_GLOB = "collected_users_*.txt"
_SCEN = {"n": 0}


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

# ★ 自测必须关掉停顿看门狗: 本自测把 time.sleep 整体换成空操作, 看门狗线程会变成
#   忙等; 而"单号时间预算"用例要用假时钟把 time() 往前拨, 真看门狗会当场 os._exit(9)。
A.STALL_EXIT_SEC = 0

# ---------------------------------------------------------------- 日志捕获
class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, rec):
        try:
            self.lines.append(rec.getMessage())
        except Exception:
            pass


CAP = Capture()
CAP.setLevel(logging.INFO)
A.log.addHandler(CAP)
A.log.setLevel(logging.INFO)
A.log.propagate = False          # 自测噪音不写进引擎的 run_*.log

_results = []


def check(name, cond, extra=""):
    _results.append((name, bool(cond)))
    print(("[PASS] " if cond else "[FAIL] ") + name + (f"   {extra}" if extra else ""))


def log_has(lines, sub):
    return any(sub in x for x in lines)


# ---------------------------------------------------------------- 假 page
class FakeMouse:
    def __init__(self):
        self.wheels = 0
        self.clicks = 0

    def move(self, *a, **k):
        pass

    def wheel(self, *a, **k):
        self.wheels += 1

    def click(self, *a, **k):
        self.clicks += 1

    def down(self, *a, **k):
        pass

    def up(self, *a, **k):
        pass


class FakeLocator:
    def __init__(self, page, kind, sel=None, visible=True):
        self.page, self.kind, self.sel, self._v = page, kind, sel, visible

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self._v else 0

    def is_visible(self):
        return self._v

    def click(self, *a, **k):
        if self.kind == "search":
            self.page.typed = ""        # 开始新一次地区搜索
        return None


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def type(self, ch, delay=0):
        self.page.typed += ch


class FakePage:
    """只实现 collect_regions / check_athlete 真正会碰的那几个接口"""

    def __init__(self):
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard(self)
        self.typed = ""
        self.url = "https://www.strava.com/settings/profile"
        self.markers = [(100, 150), (300, 350), (500, 550)]
        self.athlete = {"followers": 50, "following": 60}
        self.loc = "New York, NY"
        self.private = False
        self._segq, self._last_ath = [], -1

    # ---- playwright 风格
    def get_by_role(self, role, name=None):
        return FakeLocator(self, "role", name)

    def locator(self, sel):
        return FakeLocator(self, "search", sel)

    def get_by_text(self, t, exact=False):
        return FakeLocator(self, "text", t)

    def evaluate(self, expr, arg=None):
        if isinstance(expr, str) and "devicePixelRatio" in expr:
            return 1
        if isinstance(expr, str) and "querySelectorAll('li,div,span')" in expr:
            return {"private": True} if self.private else dict(self.athlete)
        if isinstance(expr, str) and "var h1" in expr:
            return {"loc": self.loc, "kind": "city" if self.loc else "none"}
        return None

    def screenshot(self, **k):
        raise RuntimeError("自测不使用截图(find_markers 已桩替换)")

    # ---- 路段弹窗序列: 每轮 3 个标记 -> 4000 / 6000 / 读不到(-1)
    def next_seg(self):
        if not self._segq:
            code = re.sub(r"[^A-Za-z0-9]", "", self.typed)[:8] or "X"
            self._segq = [(f"{code}_s4000", 4000),
                          (f"{code}_s6000", 6000),
                          (f"{code}_sBAD", -1)]
        sid, n = self._segq.pop(0)
        self._last_ath = n
        return sid

    def next_ath(self):
        return self._last_ath


# ------------------------------------------------- ★ 自适应缩放专用假 page
class ZoomMouse(FakeMouse):
    """滚轮 = 放大级数: wheel(0, -500) 放大一级, wheel(0, +500) 缩小一级"""

    def __init__(self, page):
        super().__init__()
        self.page = page

    def wheel(self, dx, dy):
        self.wheels += 1
        if dy < 0:
            self.page.zoom += 1
            self.page.wheel_log.append(+1)
        elif dy > 0:
            self.page.zoom -= 1
            self.page.wheel_log.append(-1)
            self.page.rolled_back = True      # 出现过回退


class ZoomPage(FakePage):
    """标记数按【当前放大级数】给, 复现真机"放大过头标记就没了"

    seq[i]      = 第 (i+1) 级引擎认到的标记数; None = 该级截图失败(find_markers 返回 None)
    confirm_n   = 回退后那次"确认截图"的返回("level"=按该级真实值, 数字=指定个数,
                  None=截图失败) —— 用来测"回退后标记少/截图失败也不跳过地区"
    zero_n      = 第 0 级(一次都没放大成功)时的标记数; None = 该级也截图失败
    """

    def __init__(self, seq, confirm_n="level", zero_n=0):
        super().__init__()
        self.seq = list(seq)
        self.confirm_n = confirm_n
        self.zero_n = zero_n
        self.zoom = 0                  # 当前放大级数(0=没放大)
        self.wheel_log = []            # [+1]=放大, [-1]=缩小
        self.calls = []                # 每次 find_markers: (级数, 标记数 / "confirm" / None)
        self.rolled_back = False
        self.confirm_level = None      # 回退后第一次截图时的级数
        self.confirm_marks = None      # 那次截图拿到的标记数
        self.mouse = ZoomMouse(self)

    # ---- 引擎口径的标记数
    def level_n(self, lvl):
        if lvl <= 0:
            return self.zero_n
        if lvl <= len(self.seq):
            return self.seq[lvl - 1]
        return self.seq[-1] if self.seq else 0

    @property
    def zooms_in(self):
        """放大次数(= 引擎滚了几次 -500)"""
        return self.wheel_log.count(+1)

    @property
    def zooms_out(self):
        """缩小次数(回退)"""
        return self.wheel_log.count(-1)

    def _mk(self, n):
        if n is None:
            return None                # ★ 截图失败: 必须返回 None, 不是 []
        return [(100 + (i % 40) * 20, 150 + (i // 40) * 20) for i in range(int(n))]

    # ---- 桩 find_markers
    def find_markers_stub(self, page=None, **k):
        if self.rolled_back and self.confirm_level is None:
            self.confirm_level = self.zoom
            if self.confirm_n == "level":
                n = self.level_n(self.zoom)
            else:
                n = self.confirm_n
            self.confirm_marks = n
            self.calls.append((self.zoom, "confirm"))
            return self._mk(n)
        n = self.level_n(self.zoom)
        self.calls.append((self.zoom, n))
        return self._mk(n)


class FakeCli:
    def __init__(self, env):
        self.env = env

    def collect(self, aid, url, **k):
        self.env.calls["collect"].append((aid, url))

    def finish(self, aid, status, note="", **k):
        self.env.calls["finish"].append((aid, status))
        if self.env.sd_finish:
            raise A.ServerDown("stub 上报失败")


class LBStub:
    """假排行榜: 每次调用返回 rows 个新候选人"""

    def __init__(self, env, rows=100, max_calls=None):
        self.env, self.rows, self.max_calls = env, rows, max_calls

    def __call__(self, page, seg_id, age, max_pages=None):
        self.env.calls["lb"].append({"seg": seg_id, "age": age, "region": page.typed,
                                     "max_pages": max_pages})
        if self.max_calls is not None and len(self.env.calls["lb"]) > self.max_calls:
            return 0, []
        base = len(self.env.calls["lb"]) * 1000
        # ★ 假 athlete id 带场景号(场景间不重号): 于是"本场景任务文件里的 URL
        #   只属于本场景"可以被真正断言出来, 而不是靠肉眼比对。
        tag = f"a{self.env.sc}_"
        return 1000, [{"aid": f"{tag}{base + j}", "name": f"U{base + j}"}
                      for j in range(self.rows)]


class Env:
    def __init__(self, home="Chicago, Illinois", regions=None, auto=False,
                 rows=100, max_lb_calls=None, pass_first=None, stop_after=None,
                 sd_finish=False, sd_claim=False, cli=None, page=None,
                 cfg_extra=None, seq="7", clock=None):
        self.home = home
        self.regions = regions
        self.auto = auto
        self.rows = rows
        self.pass_first = pass_first
        self.stop_after = stop_after
        self.sd_finish = sd_finish
        self.sd_claim = sd_claim
        self.page = page or FakePage()
        self.cfg_extra = cfg_extra
        self.seq = seq
        self.clock = clock           # 非 None -> 本次用假时钟(时间预算用例)
        self.pass_count = 0
        self.sc = 0
        self.dir = None
        self.iso = {}
        self.calls = {"check": [], "lb": [], "claim": [], "collect": [], "finish": []}
        self.lb = LBStub(self, rows=rows, max_calls=max_lb_calls)
        self.cli = cli if cli is not None else FakeCli(self)
        self._start = 0
        self.logs = []

    # ---- 桩
    def check_athlete(self, page, aid, max_followers=200, geo_filter=False,
                      center=None, exempt_max=False):
        self.calls["check"].append({"aid": aid, "region": page.typed, "center": center,
                                    "exempt_max": exempt_max, "geo": geo_filter,
                                    "max_followers": max_followers})
        ok, why = True, "粉丝50/关注60"
        if self.pass_first is not None and self.pass_count >= self.pass_first:
            ok, why = False, "粉丝300超标"
        self.pass_count += 1
        if self.stop_after and self.pass_count >= self.stop_after:
            A.STOP_EVENT.set()          # 模拟用户中途点停止
        return ok, why

    def claim_pick(self, cli, seen, aids):
        if self.sd_claim:
            raise A.ServerDown("stub 领取失败")
        self.calls["claim"].append(list(aids))
        return [a for a in aids if a not in seen], 0

    # ---- 跑一次
    def run(self, min_athletes=None, target=None, segs=None, geo=True):
        # ★ 场景隔离: 每个场景一个全新的空目录, 并把它作为 COLLECT_OUT 的父目录
        #   (引擎的 _task_dir() == COLLECT_OUT.parent, 任务成品/明细都落这里)。
        _SCEN["n"] += 1
        self.sc = _SCEN["n"]
        self.dir = TMP / f"sc{self.sc}"
        if self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        install_stubs(self)
        A.STOP_EVENT.clear()
        A.COLLECT_SEEN = self.dir / "seen.json"
        A.COLLECT_OUT = self.dir / "out.txt"
        _cfg_o = A.CFG
        if self.cfg_extra is not None:
            _cfg = dict(_cfg_o)
            for _k, _v in self.cfg_extra.items():
                if _v is None:               # None = 把这个键去掉(测引擎缺省值)
                    _cfg.pop(_k, None)
                else:
                    _cfg[_k] = _v
            A.CFG = _cfg
        _clock_o = A.time
        if self.clock is not None:
            A.time = self.clock
        # ★ 2026-09-19 改造后必须补这一步: 引擎新增了进程内一次性去重索引
        #   _OUT_HAVE(交付过的 URL 绝不再写第二遍), 它只在第一次调用 _out_index()
        #   时扫盘、之后常驻内存。本自测在同一个进程里连跑十几个场景, 若不重置,
        #   第一轮采到的 URL 会把后面所有轮次都判成"已交付", collected 恒为 0
        #   —— 那是测试隔离问题, 不是引擎 bug(生产每个号采的人不同)。
        #   ★ 重置之外还必须配合上面的"每场景独立空目录": _out_index() 扫的是
        #     COLLECT_OUT.parent 下所有 collected_users_*.txt, 只重置内存索引而共用
        #     目录的话, 重建索引时照样会把上一场景的成果读回来。
        if hasattr(A, "_OUT_HAVE"):
            A._OUT_HAVE["built"] = False
            A._OUT_HAVE["set"] = set()
        del _RATE_CALLS[:]
        self._start = len(CAP.lines)
        out, err = None, None
        try:
            out = A.collect_regions(self.page, regions=self.regions,
                                    age_groups=("45_54", "55_64", "65_69"),
                                    min_athletes=min_athletes,
                                    max_followers=200,
                                    target_per_account=target,
                                    max_segments_per_region=segs,
                                    cli=self.cli, geo_filter=geo,
                                    home_loc=self.home, auto_regions=self.auto,
                                    seq=self.seq)
        except BaseException as e:            # noqa: BLE001  自测要看异常类型
            err = e
        finally:
            A.STOP_EVENT.clear()
            A.CFG = _cfg_o
            A.time = _clock_o
        self.logs = CAP.lines[self._start:]
        self._iso_check(out)
        return out, err

    # ---- ★ 场景隔离自检: 目录内只属于本场景 + 目录外零新建
    def _iso_check(self, out):
        tag = f"a{self.sc}_"
        files = sorted(self.dir.glob(TASK_GLOB))
        urls, hdr_ok, end_ok = set(), True, False
        for p in files:
            txt = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if not txt or not txt[0].startswith("# 任务开始"):
                hdr_ok = False
            # ★ 2026-09-19 用户要求"只保留链接, 其他信息不需要":
            #   数据行必须是纯 URL(无制表符附加列), 也没有 "# 任务结束/号数" 这类额外行。
            #   end_ok 的语义随之改成"格式符合新要求"。
            _data = [x.strip() for x in txt if x.strip() and not x.strip().startswith("#")]
            if _data and all(x.startswith("http") and "\t" not in x for x in _data):
                end_ok = True
            for ln in _data:
                urls.add(ln.split("\t")[0])
        foreign = sorted(u for u in urls if not u.rsplit("/", 1)[-1].startswith(tag))
        leaks = sorted(str(p.relative_to(ROOT)) for p in _outside_task_files()
                       if str(p) not in _OUTSIDE_SNAP)
        expect = None if out is None else {c["url"] for c in out}
        same = (expect is None) or (expect == urls)
        self.iso = {"sc": self.sc, "files": [p.name for p in files],
                    "urls": len(urls),
                    "expect": None if expect is None else len(expect),
                    "foreign": foreign, "leaks": leaks, "same": same,
                    "hdr_ok": hdr_ok, "end_ok": end_ok}
        check(f"(iso{self.sc}) 场景目录隔离: 本场景目录里的 {len(files)} 个 "
              f"{TASK_GLOB} 只含本场景 URL, 且目录外没有新建任何任务文件",
              (not foreign) and (not leaks) and same and hdr_ok
              and (end_ok or not urls),
              f"files={self.iso['files']} url数={len(urls)} 本场景应={self.iso['expect']} "
              f"外来={foreign[:2]} 目录外新建={leaks[:2]} 首行任务头={hdr_ok} 任务结束={end_ok}")
        shutil.rmtree(self.dir, ignore_errors=True)     # 场景结束清掉该子目录


_RATE_CALLS = []                       # 本场景里 rate_gate 被调用的 kind 序列
_REAL_RATE_GATE = A.rate_gate          # 在 install_stubs 之前抓一次真实现


def install_stubs(env):
    A.goto_retry = lambda page, url, **k: True
    A.accept_cookies = lambda page, timeout=0: True
    A.wait_text = lambda *a, **k: None
    A.net_info = lambda: "stub"
    A.backoff = lambda *a, **k: 0.0
    A.sleep_or_stop = lambda sec: A.check_stop()      # 不真睡, 但保留停止响应
    # ★ 风控闸门: 记下调用序列(仍然走真实现 -> 真实现里的等待被上面的
    #   sleep_or_stop 桩吃掉, 不会真的拖慢自测)
    def _rate_gate(kind):
        _RATE_CALLS.append(kind)
        return _REAL_RATE_GATE(kind)

    A.rate_gate = _rate_gate
    # ★ ZoomPage 按放大级数给标记数(可返回 None); 普通 FakePage 仍是固定 3 个标记
    _fm = getattr(env.page, "find_markers_stub", None)
    A.find_markers = _fm if callable(_fm) else (lambda page, **k: list(page.markers))
    A.segment_from_popup = lambda page: page.next_seg()
    A.popup_athletes = lambda page: page.next_ath()
    A.fetch_lb_filtered = env.lb
    A.check_athlete = env.check_athlete
    A.claim_pick = env.claim_pick
    A.read_settings_info = lambda page, timeout=0: {"name": "SelfTest",
                                                    "location": env.home}


# ---------------------------------------------------------------- 自测开始
print("=" * 78)
print("离线自测 collect_regions (假 page / 桩函数, 不联网不启动浏览器)")
print("=" * 78)

_real_sleep = time.sleep
time.sleep = lambda s: None            # 引擎里那些固定等待没必要真等

_reals = {k: getattr(A, k) for k in
          ("goto_retry", "accept_cookies", "wait_text", "net_info", "backoff",
           "sleep_or_stop", "find_markers", "segment_from_popup", "popup_athletes",
           "fetch_lb_filtered", "check_athlete", "claim_pick", "read_settings_info",
           "rate_gate")}

try:
    # ============================ (a) 达标即停 ============================
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100)
    out, err = e.run()
    check("(a) 采到 200 就停: 返回 200 条", out is not None and len(out) == 200,
          f"len={len(out) if out else None} err={err!r}")
    check("(a) 达标后不再多查一个人(检查次数=200)", len(e.calls["check"]) == 200,
          f"检查{len(e.calls['check'])}次")
    check("(a) 日志有达标行 [quota] 已达标 200/200",
          log_has(e.logs, "[quota] ★ 已达标 200/200"))
    check("(a) 每采到一个都打 [quota] 合格 X/200",
          log_has(e.logs, "[quota] 合格 1/200") and log_has(e.logs, "[quota] 合格 200/200"))
    check("(a) 每段人数门槛是 5000(不是 200)",
          log_has(e.logs, "路段排名(运动达人 降序)")
          and log_has(e.logs, "采样路段"))
    # (m) 分批领取: 每次 <= CLAIM_CHUNK(60), 且每个被查的人都先领过
    _bs = [len(b) for b in e.calls["claim"]]
    check("(m) 领取分批(每批<=60), 且查了的人都领过",
          bool(_bs) and max(_bs) <= A.CLAIM_CHUNK
          and sum(_bs) == len(e.calls["check"]), f"批次={_bs}")
    # (t) ★ 任务文件契约: 任务成品 collected_users_<tid>.txt + 号级明细 _<号>.txt
    _prod = [f for f in e.iso["files"] if "_7" not in f]
    _detail = [f for f in e.iso["files"] if f.endswith("_7.txt")]
    check("(t) 任务成品 collected_users_<tid>.txt + 号级明细 collected_users_<tid>_7.txt",
          len(_prod) == 1 and len(_detail) == 1
          and re.fullmatch(r"collected_users_\d{8}_\d{6}\.txt", _prod[0])
          and re.fullmatch(r"collected_users_\d{8}_\d{6}_7\.txt", _detail[0]),
          f"files={e.iso['files']}")
    check("(t) 两个文件首行都是 '# 任务开始 ...', 数据行是纯链接(无附加列/无额外信息)",
          e.iso["hdr_ok"] and e.iso["end_ok"], f"hdr={e.iso['hdr_ok']} end={e.iso['end_ok']}")
    check("(t) 任务文件里的 URL 数 == 本次 collected 数(200)",
          e.iso["urls"] == 200 and e.iso["expect"] == 200 and e.iso["same"],
          f"url={e.iso['urls']} expect={e.iso['expect']} same={e.iso['same']}")
    # (v) 风控闸门: 选路段点标记/拖拽都必须过 rate_gate("act")
    check("(v) 选路段阶段每个点击/拖拽都过风控闸门 rate_gate('act')",
          _RATE_CALLS.count("act") >= 2 and set(_RATE_CALLS) == {"act"},
          f"rate_gate 调用={sorted(set(_RATE_CALLS))} act={_RATE_CALLS.count('act')}次")

    # ============================ (b) 换地区 + 未达标告警 ============================
    e = Env(home="Chicago, Illinois", regions=["New York", "Wisconsin"], auto=False,
            rows=100, pass_first=50)
    out, err = e.run()
    n_regions = len([x for x in e.logs if x.startswith("[region] =====")])
    check("(b) 一个地区不够会继续下一个地区", n_regions >= 2, f"跑了{n_regions}个地区")
    check("(b) 第一个地区是纽约", log_has(e.logs, "[region] ===== New York ====="))
    check("(b) 跑完不够 -> 只采到 50 并明确告警未达标",
          len(out or []) == 50 and log_has(e.logs, "[quota] 只采到 50/200 未达标"),
          f"len={len(out or [])}")
    check("(b) 未达标时不打达标行", not log_has(e.logs, "已达标"))

    # ============================ (c) 纽约豁免 + 圆心=本号所在地 ============================
    # rows=60 -> 每个地区最多 1段×3年龄组×60 = 180 人 < 200, 保证两个地区都会被扫到
    e = Env(home="Milwaukee, Wisconsin", regions=["Wisconsin"], auto=False, rows=60)
    out, err = e.run()
    ny = [c for c in e.calls["check"] if c["region"] == "New York"]
    wi = [c for c in e.calls["check"] if c["region"] == "Wisconsin"]
    check("(c) 配置里没纽约也要先扫纽约", log_has(e.logs, "配置里没有纽约") and len(ny) > 0,
          f"纽约检查{len(ny)}人 威州检查{len(wi)}人")
    check("(c) 纽约段 exempt_max=True, 威州段 False",
          ny and wi and all(c["exempt_max"] for c in ny)
          and all(not c["exempt_max"] for c in wi))
    check("(c) 圆心 = 该号所在地(Milwaukee), 不是写死的芝加哥",
          ny and wi and all(c["center"][2] == "Milwaukee, Wisconsin" for c in ny + wi)
          and abs(ny[0]["center"][0] - 41.8781) > 0.5,
          f"center={ny[0]['center'] if ny else None}")
    check("(c) 圆心日志 [geo] 本号所在地=... -> 圆心=...",
          log_has(e.logs, "[geo] 本号所在地=Milwaukee, Wisconsin -> 圆心=Milwaukee, Wisconsin"))

    # ============================ (d) 5000 门槛 ============================
    e = Env(home="Chicago, Illinois", regions=["New York", "Wisconsin"], auto=False, rows=100)
    out, err = e.run()
    segs = [c["seg"] for c in e.calls["lb"]]
    # ★ 2026-09-19: 选路段改成"先采样、再按运动达人数排名" —— 决策时机从"逐个当场
    #   判定"挪到了"统一排名", 所以日志文案也变了(采用/跳过 -> 采样/排名)。
    #   下面同时验"没被采纳"和"新日志在", 强度不减。
    check("(d) 4000 人的路段被采样、但排名时被淘汰",
          log_has(e.logs, "运动达人=4000") and not any("_s4000" in s for s in segs),
          f"segs={sorted(set(segs))}")
    check("(d) 纯 5000+ 的路段被采用", any("_s6000" in s for s in segs))
    check("(d) 读不到人数(-1)的路段也淘汰",
          not any("_sBAD" in s for s in segs))
    check("(d) 采样与排名都有日志(读不到也照记)",
          log_has(e.logs, "读不到达人数") and log_has(e.logs, "路段排名(运动达人 降序)"))

    # ============================ (e) 停止立即生效 ============================
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100,
            stop_after=15)
    out, err = e.run()
    check("(e) 置 STOP_EVENT 后 UserStopped 打断采集", isinstance(err, A.UserStopped),
          f"err={err!r}")
    check("(e) 被打断时没有返回结果", out is None and len(e.calls["check"]) <= 17,
          f"检查{len(e.calls['check'])}次")

    # ============================ (f) ServerDown 整体中止 ============================
    e = Env(home="Chicago, Illinois", regions=["New York", "Wisconsin"], auto=False,
            rows=100, sd_finish=True)
    out, err = e.run()
    check("(f) 上报失败(ServerDown) 整体中止", isinstance(err, A.ServerDown), f"err={err!r}")
    check("(f) 中止后没有再跑下一个地区",
          not log_has(e.logs, "[region] ===== Wisconsin ====="))

    # ============================ (g) 旧值兜底 5000 / 200 ============================
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100)
    out, err = e.run(min_athletes=200, target=50, segs=8)
    check("(g) 门槛 200 被抬到 5000 并告警",
          log_has(e.logs, "每段人数门槛 200 低于硬性要求 5000, 已抬到 5000"))
    check("(g) 目标 50 被抬到 200 并告警",
          log_has(e.logs, "每号目标 50 低于硬性要求 200, 已抬到 200"))
    check("(g) 抬完真的按 200 采(不是 50)", len(out or []) == 200, f"len={len(out or [])}")
    check("(g) segs_per_region=8 不再卡死采集量(仍能采够 200)", len(out or []) == 200)

    # ============================ (h) 真 check_athlete + 真 geo_cities ============================
    install_stubs(Env())                     # 只装与 check_athlete 无关的桩
    A.check_athlete = _reals["check_athlete"]
    pg = FakePage()
    A.goto_retry = lambda page, url, **k: True
    A.wait_text = lambda *a, **k: None
    A.backoff = lambda *a, **k: 0.0
    mil = A.geo_resolve_center("Milwaukee, Wisconsin")
    center3 = (mil[0], mil[1], mil[2])
    pg.loc, pg.athlete = "New York, NY", {"followers": 50, "following": 60}
    ok_ny_ex, why_ny_ex = A.check_athlete(pg, "999", 200, geo_filter=True,
                                          center=center3, exempt_max=True)
    ok_ny_no, why_ny_no = A.check_athlete(pg, "999", 200, geo_filter=True,
                                          center=center3, exempt_max=False)
    check("(h) 纽约来源 >1000km: 豁免=True 保留 / 豁免=False 淘汰",
          ok_ny_ex is True and ok_ny_no is False, f"{why_ny_ex} || {why_ny_no}")
    pg.loc = "Milwaukee, Wisconsin"
    ok_near, why_near = A.check_athlete(pg, "999", 200, geo_filter=True,
                                        center=center3, exempt_max=True)
    check("(h) 豁免只免上限不免下限: 14km 太近照样淘汰", ok_near is False, f"{why_near}")
    check("(h) 位置日志带圆心/距离/豁免标记",
          log_has(CAP.lines, "圆心=Milwaukee, Wisconsin 距离=")
          and log_has(CAP.lines, "豁免上限(仅判>100km)"))

    # ============================ (i) 排行榜默认翻页 ============================
    A.fetch_lb_filtered = _reals["fetch_lb_filtered"]      # 换回真的实现

    class LbPage:
        def __init__(self):
            self.pages = []

        def evaluate(self, js, args=None):
            if args:
                self.pages.append(args[2])
                return {"ok": True, "total": 1000,
                        "rows": [{"aid": f"p{args[2]}_{i}", "name": "n"} for i in range(5)]}
            return None

    lp = LbPage()
    _cfg_real = A.CFG
    A.CFG = {}
    tot, rows = A.fetch_lb_filtered(lp, "123", "65_69")
    check("(i) lb_max_pages 缺省 -> 翻 8 页", lp.pages == [1, 2, 3, 4, 5, 6, 7, 8],
          f"pages={lp.pages}")
    lp.pages = []
    A.CFG = {"lb_max_pages": 3}
    A.fetch_lb_filtered(lp, "123", "65_69")
    check("(i) 配置 lb_max_pages=3 -> 翻 3 页", lp.pages == [1, 2, 3], f"pages={lp.pages}")
    A.CFG = _cfg_real

    # ============================ (j) detect_home_loc 优先级 ============================
    class StPage:
        pass

    A.read_settings_info = lambda page, timeout=0: {"name": "x", "location": "Denver, Colorado"}
    A.load_state = lambda: {"ads_7": {"location": "Boston, Massachusetts"}}
    A.CFG = dict(_cfg_real)
    A.CFG["location"] = "Chicago, Illinois"
    loc1 = A.detect_home_loc(StPage(), 7, cached="Miami, Florida")
    loc2 = A.detect_home_loc(StPage(), 7)
    A.read_settings_info = lambda page, timeout=0: {"name": "x", "location": ""}
    loc3 = A.detect_home_loc(StPage(), 7)
    A.load_state = lambda: {}
    loc4 = A.detect_home_loc(None, 7)
    check("(j) detect_home_loc: cached > 页面 > state > CFG",
          (loc1, loc2, loc3, loc4) == ("Miami, Florida", "Denver, Colorado",
                                       "Boston, Massachusetts", "Chicago, Illinois"),
          f"{loc1!r} {loc2!r} {loc3!r} {loc4!r}")
    A.CFG = _cfg_real

    # ============================ (k) 计划地区: 纽约第一 + 自动补环带州 ============================
    e = Env(home="Chicago, Illinois", regions=["Wisconsin", "New York"], auto=True, rows=100)
    out, err = e.run()
    _pl = [x for x in e.logs if x.startswith("[geo] 计划地区")]
    plan = _pl[0].split(": ", 1)[1] if _pl else ""
    _order = [x for x in e.logs if x.startswith("[region] =====")]
    check("(k) 纽约排第一(即使配置里纽约在后面)",
          bool(_order) and "New York" in _order[0] and plan.startswith("New York("), f"{plan[:80]}")
    check("(k) 配置里的威斯康星也在计划里(纽约之后)",
          "Wisconsin(" in plan and plan.index("Wisconsin(") > plan.index("New York("))
    check("(k) 自动补了环带内的州(如 Illinois)", "Illinois(" in plan)
    check("(k) 纽约不重复出现", plan.count("New York(") == 1, f"出现{plan.count('New York(')}次")
    check("(k) 计划地区数 > 5", len(plan.split(" -> ")) > 5, f"{len(plan.split(' -> '))}个")

    # ==================== (l) 本号所在地认不出/不精确 -> warning + 兜底 ====================
    e = Env(home="Nowhereville, ZZ", regions=["New York"], auto=False, rows=100)
    out, err = e.run()
    check("(l) 认不出所在地 -> warning 并回退配置 location=Chicago, Illinois",
          log_has(e.logs, "本号所在地识别不精确")
          and log_has(e.logs, "回退配置 location=Chicago, Illinois"),
          f"圆心={[c['center'][2] for c in e.calls['check']][:1]}")
    e = Env(home="Ohio", regions=["New York"], auto=False, rows=100)
    out, err = e.run()
    check("(l) 只认到州(conf=state) 也 warning + 回退(不当精确圆心用)",
          log_has(e.logs, "home_loc='Ohio'(conf=state)")
          and log_has(e.logs, "回退配置 location=Chicago, Illinois"))

    # ============ (S1)~(S5) ★★ 自适应缩放: 放大过头 -> 停 + 回退到最佳级别 ============
    # 真机实测(纽约州热力图, 环境3 会员, 引擎 find_markers 口径认到的标记数):
    #   放大级数 4~8 级 = 38~56 个(甜点区), 9 级 21 个, 10 级 1 个, 11 级及以后 0 个。
    #   老逻辑"最多 14 级 + 见到标记后再多放 4 级"会一路放到 0 个 -> 一个路段都选不出来。
    #   下面 ZoomPage 的 seq[i] = 第(i+1)级的标记数, 复现同一条曲线。

    # ---- (S1) 标记序列 [1,1,38,56,56,56,21,1,0,0]: 变差就停 + 回退 ----
    zp = ZoomPage([1, 1, 38, 56, 56, 56, 21, 1, 0, 0])
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    _zl = [x for x in e.logs if "自适应缩放" in x]
    _lv = [lvl for lvl, n in zp.calls if n != "confirm" and lvl > 0]
    _deep = max(_lv) if _lv else 0
    print("    (S1) 级数->标记数轨迹: " + ", ".join(
        f"{lvl}:{'失败' if n is None else n}" for lvl, n in zp.calls if n != "confirm"))
    check("(S1) 全程不崩, 最终仍然采到 200 条",
          err is None and len(out or []) == 200, f"len={len(out or [])} err={err!r}")
    check("(S1) 变差就停: 56->21 时停止放大, 没有一路放到 0 个标记",
          log_has(e.logs, "标记开始变少(56->21), 停止放大") and _deep == 7,
          f"最深只放到第{_deep}级(真机 11 级后 0 个)")
    check("(S1) 最佳级别 = 标记最多的那一级(56 个)",
          bool(_zl) and "最佳 4 级(56 个标记)" in _zl[0], f"{_zl[:1]}")
    check("(S1) 回退: 最终当前级别 == 最佳级别(7 级 -> 4 级)",
          bool(_zl) and _zl[0].endswith("现在停在 4 级") and zp.zoom == 4,
          f"zoom={zp.zoom} {_zl[:1]}")
    check("(S1) 回退后停在峰值级: 确认截图拿到 56 个标记(=最佳)",
          zp.confirm_level == 4 and zp.confirm_marks == 56,
          f"确认级={zp.confirm_level} 标记={zp.confirm_marks}")
    check("(S1) 停对级别后确实选到了路段",
          bool(e.calls["lb"]) and log_has(e.logs, "采用 1 个路段"),
          f"lb调用{len(e.calls['lb'])}次")

    # ---- (S1b) 真机同款序列(第4~7级 = 38,38,56,21): 变差就停 + 回退 ----
    # ★ 2.11 提速把 ZOOM_MAX_STEPS 从 12 收到 8(真机第10级后整轮 11 分钟无输出),
    #   所以真机那条 38,38,56,56,56,21,1,0 现在最多只走到第 8 级; 本用例把
    #   "变差就停"这一条整体前移, 保住原来的检验强度:
    #   第6级爬到 56 之后第7级掉到 21 -> 停, 回退到最佳的第6级, 第8级起不再走。
    zp = ZoomPage([0, 0, 0, 38, 38, 56, 21, 1, 0, 0, 0])
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    print("    (S1b) 真机同款 级数->标记数轨迹: " + ", ".join(
        f"{lvl}:{'失败' if n is None else n}" for lvl, n in zp.calls if n != "confirm"))
    check("(S1b) 真机同款序列: 最佳 6 级(56 个), 最终停在 6 级",
          log_has(e.logs, "自适应缩放: 最佳 6 级(56 个标记), 现在停在 6 级") and zp.zoom == 6,
          f"zoom={zp.zoom}")
    check("(S1b) 第7级(21个)就停, 没走到第8级(1个)/第9级(0个)",
          log_has(e.logs, "标记开始变少(56->21), 停止放大")
          and max(lvl for lvl, n in zp.calls if n != "confirm") == 7)
    check("(S1b) 回退后确认截图 = 峰值 56 个, 且照常采到 200",
          zp.confirm_level == 6 and zp.confirm_marks == 56 and len(out or []) == 200,
          f"确认级={zp.confirm_level} 标记={zp.confirm_marks} len={len(out or [])}")
    # ★ 新增: ZOOM_MAX_STEPS=8 是硬上限 —— 浅层一直不出标记也不许放到第 9 级
    zp = ZoomPage([0] * 20)
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    check("(S1b) 放大硬上限 ZOOM_MAX_STEPS=8: 全程 0 个标记也只放 8 级",
          A.ZOOM_MAX_STEPS == 8 and zp.zooms_in == 8
          and log_has(e.logs, "第8级 标记0个")
          and not log_has(e.logs, "第9级"),
          f"放大{zp.zooms_in}级(wheel+) 日志有第8级={log_has(e.logs, '第8级')}")

    # ---- (S2) 截图失败(None) 不改变最佳级别, 更不许当成 0 个 ----
    zp = ZoomPage([1, 1, None, 38, None, 56, None, None, None, None])
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    print("    (S2) 级数->标记数轨迹: " + ", ".join(
        f"{lvl}:{'失败' if n is None else n}" for lvl, n in zp.calls if n != "confirm"))
    check("(S2) 有级别截图失败也不崩, 仍采到 200 条",
          err is None and len(out or []) == 200, f"len={len(out or [])} err={err!r}")
    check("(S2) 失败级别打'截图失败(未知), 不计入比较'",
          log_has(e.logs, "第3级 截图失败(未知), 不计入比较")
          and log_has(e.logs, "第5级 截图失败(未知), 不计入比较"))
    check("(S2) None 不改变 best_level: 第3级失败后最佳仍是'1级/1个'",
          log_has(e.logs, "第2级 标记1个 (当前最佳 1级/1个)")
          and log_has(e.logs, "第4级 标记38个 (当前最佳 4级/38个)"))
    check("(S2) None 没被当成 0: 第5级失败没触发'标记开始变少(38->0)', 第6级照样数到 56",
          not log_has(e.logs, "标记开始变少(38->0)")
          and log_has(e.logs, "第6级 标记56个 (当前最佳 6级/56个)"))
    check("(S2) 未知级别不误导: 最佳=第6级/56 个, 并回退到第6级",
          log_has(e.logs, "自适应缩放: 最佳 6 级(56 个标记), 现在停在 6 级") and zp.zoom == 6,
          f"zoom={zp.zoom}")

    # ---- (S3) 全程截图失败 -> 不崩、不抛异常、继续平移找 ----
    zp = ZoomPage([None] * 12, zero_n=None)
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    check("(S3) 全程截图失败: 不崩不抛异常, 返回空结果",
          err is None and out == [], f"out={out!r} err={err!r}")
    check("(S3) 自适应缩放日志照常收尾(最佳 0 级, 停在 0 级)",
          log_has(e.logs, "自适应缩放: 最佳 0 级(0 个标记), 现在停在 0 级"))
    check("(S3) 放大级数上限 = ZOOM_MAX_STEPS(8), 不再放到第 12 级; 最佳=0 级所以原级退回",
          zp.zooms_in == A.ZOOM_MAX_STEPS == 8 and zp.zooms_out == 8
          and not log_has(e.logs, "第9级"),
          f"放大{zp.zooms_in}级 缩小{zp.zooms_out}级")
    check("(S3) 回退后截图失败仍继续(不跳过地区)",
          log_has(e.logs, "回退后截图失败, 仍按当前级别继续"))
    # ★ 2.11: 平移轮数 16 -> PAN_ROUNDS(8); ★ 第二批 §2: 死地区在平移阶段最多试 3 轮
    check("(S3) 平移按 PAN_ROUNDS=8 计轮, 且死地区最多试 3 轮(不再磨满 16 轮)",
          log_has(e.logs, "第1/8轮 截图失败(未知)")
          and log_has(e.logs, "第3/8轮 截图失败(未知)")
          and log_has(e.logs, "死地区, 最多试 3 轮")
          and not log_has(e.logs, "第4/8轮")
          and not log_has(e.logs, "/16轮"),
          f"轮次日志={[x for x in e.logs if '轮' in x][:5]}")
    check("(S3) 没有任何'未知'被当成 0 个标记",
          not log_has(e.logs, "标记0个") and log_has(e.logs, "第8级 截图失败(未知)"))
    # ★★ 死地区跳过的铁律: mk is None = 截图失败 = 标记数【未知】, 绝不算"空地区"
    #    (算进去的话, 连续 4 次截图故障就会白白中止一整轮采集)
    check("(S3) 截图失败(未知) 不算空地区: 不打'零标记零路段'/不触发'连续 4 个空地区'",
          not log_has(e.logs, "零标记零路段")
          and not log_has(e.logs, "连续 4 个空地区"))
    check("(S3) 地区正常收尾(采用 0 个路段), 没被当成'地区异常'",
          log_has(e.logs, "采用 0 个路段") and not log_has(e.logs, "[region] New York 异常"))

    # ---- (S4) 回退后只有 2 个标记: 告警但不跳过该地区 ----
    zp = ZoomPage([38, 38, 56, 56, 21, 1, 0, 0], confirm_n=2)
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    check("(S4) 回退后只有 2 个标记: 明确 warning",
          log_has(e.logs, "回退后只有 2 个标记, 仍继续(后面还会平移找)"))
    check("(S4) 标记少也不跳过地区: 照样选路段并采到 200",
          bool(e.calls["lb"]) and len(out or []) == 200, f"len={len(out or [])}")
    check("(S4) 确实回退到了最佳级别(第3级/56 个那次)",
          zp.confirm_level == 3 and zp.zoom == 3
          and log_has(e.logs, "自适应缩放: 最佳 3 级(56 个标记), 现在停在 3 级"),
          f"确认级={zp.confirm_level} zoom={zp.zoom}")
    # ★ 新增: ZOOM_MIN_STEPS=6 —— 第5级(21个, 明显变差)也不许停, 必须放到第6级才判
    check("(S4) ZOOM_MIN_STEPS=6: 第5级(56->21)不算数, 放到第6级(56->1)才停",
          A.ZOOM_MIN_STEPS == 6
          and log_has(e.logs, "第5级 标记21个")
          and not log_has(e.logs, "标记开始变少(56->21)")
          and log_has(e.logs, "第6级 标记1个")
          and log_has(e.logs, "标记开始变少(56->1), 停止放大"))

    # ---- (S5) 回退后截图失败: 告警但按当前级别继续 ----
    zp = ZoomPage([1, 1, 38, 56, 21, 1, 0, 0], confirm_n=None)
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100, page=zp)
    out, err = e.run()
    check("(S5) 回退后截图失败: 告警 + 继续(不跳过地区)",
          log_has(e.logs, "回退后截图失败, 仍按当前级别继续")
          and bool(e.calls["lb"]) and len(out or []) == 200, f"len={len(out or [])}")

    # ---- (S6) 真 find_markers: 截图失败返回 None(不是 []); 空图返回 [] ----
    A.find_markers = _reals["find_markers"]          # 用真实现(不截图 -> 桩 page)
    import base64 as _b64
    import io as _io
    from PIL import Image as _Im

    class ShotPage:
        """假 page: screenshot 按脚本"返图 / 抛超时", 并记录传进来的 timeout"""

        def __init__(self, raw=None, exc=None, cdp=None):
            self.raw, self.exc, self.calls = raw, exc, []
            self.cdp = cdp               # 非 None -> CDP 兜底能拿到图

        def screenshot(self, **k):
            self.calls.append(k.get("timeout"))
            if self.exc:
                raise self.exc
            return self.raw

        @property
        def context(self):
            _p = self

            class _Ctx:
                def new_cdp_session(self, _page):
                    class _Sess:
                        def send(self, _m, _a=None):
                            return {"data": _b64.b64encode(_p.cdp).decode()}
                    return _Sess()
            return _Ctx()

    _sp = ShotPage(exc=RuntimeError("Page.screenshot: Timeout 8000ms exceeded"))
    _r = A.find_markers(_sp)
    check("(S6) Playwright 截图连续失败 -> 返回 None(绝不是 [])", _r is None, f"返回={_r!r}")
    check("(S6) 单次截图超时 = 8000ms(不再是 12000/20000), 且只重试 2 轮",
          _sp.calls == [8000, 8000], f"timeouts={_sp.calls}")
    check("(S6) 日志: Playwright 失败 + CDP 兜底也试过 + 最终 'Playwright + CDP 都截不到'",
          log_has(CAP.lines, "[markers] Playwright 截图失败(1/2)")
          and log_has(CAP.lines, "[markers] Playwright 截图失败(2/2)")
          and log_has(CAP.lines, "[markers] CDP 截图失败(1/2)")
          and log_has(CAP.lines, "[markers] Playwright + CDP 都截不到, 本步跳过"))

    _buf = _io.BytesIO()
    _Im.new("RGB", (400, 400), (255, 255, 255)).save(_buf, "PNG")
    _r2 = A.find_markers(ShotPage(raw=_buf.getvalue()))
    check("(S6) 截到图但没有橙色标记 -> 返回 [](空列表, 与 None 区分)", _r2 == [],
          f"返回={_r2!r}")

    # ★ 新增: CDP 兜底真的能把 Playwright 超时救回来(真机 0918 全靠这条路径出图)
    _b2 = _io.BytesIO()
    _Im.new("RGB", (400, 400), (255, 255, 255)).save(_b2, "PNG")
    _sp2 = ShotPage(exc=RuntimeError("Page.screenshot: Timeout 8000ms exceeded"),
                    cdp=_b2.getvalue())
    _r3 = A.find_markers(_sp2)
    check("(S6) Playwright 超时 -> CDP 兜底抓到图 -> 照常返回标记(不是 None)",
          _r3 == [] and _sp2.calls == [8000],
          f"返回={_r3!r} timeouts={_sp2.calls}")

    # ---- (S7) 真 popup_athletes: 读不到 / 读到 0 都归一成 -1 并区分日志 ----
    A.popup_athletes = _reals["popup_athletes"]

    class AthPage:
        def __init__(self, v):
            self.v = v

        def evaluate(self, *a, **k):
            return self.v

    check("(S7) 真机读数 49,181 照常返回 49181", A.popup_athletes(AthPage(49181)) == 49181)
    check("(S7) 读不到(-1) -> -1, 日志写'读不到达人数'",
          A.popup_athletes(AthPage(-1)) == -1
          and log_has(CAP.lines, "[popup] 读不到达人数"))
    check("(S7) 读到 0 -> -1, 日志与'读不到'区分开",
          A.popup_athletes(AthPage(0)) == -1
          and log_has(CAP.lines, "[popup] 读到达人数=0(<=0"))
    check("(S7) 负数残留(-5) -> -1", A.popup_athletes(AthPage(-5)) == -1)
    check("(S7) 读数类型异常('x') -> -1", A.popup_athletes(AthPage("x")) == -1)

    # ==================== (S8) ★ 2.11 提速后的常量口径(源码静态核查) ====================
    _SRC = (ROOT / "主脚本" / "strava_ads.py").read_text(
        encoding="utf-8").splitlines()

    def _const_line(name):
        return next((x.strip() for x in _SRC if x.strip().startswith(name + " =")), "")

    _fm_i = next(i for i, x in enumerate(_SRC) if x.startswith("def find_markers("))
    # ★ 2026-09-19: 原来写死 _SRC[_fm_i:_fm_i + 40] —— 只要函数上方的注释/文档字符串
    #   长了几行, 关键代码就被挤出窗口, 断言会"因为注释变长"而误报失败(实测踩过)。
    #   改成按【下一个顶层 def/class】切块, 与注释长度彻底解耦。
    _fm_end = next((j for j in range(_fm_i + 1, len(_SRC))
                    if _SRC[j].startswith(("def ", "class ", "@"))), len(_SRC))
    _fm_blk = "\n".join(_SRC[_fm_i:_fm_end])

    check("(S8) PAN_ROUNDS = 8(旧 16 轮)", A.PAN_ROUNDS == 8
          and _const_line("PAN_ROUNDS").startswith("PAN_ROUNDS = 8"))
    check("(S8) ENOUGH_SEGMENTS = 12(采样目标; 旧 4 是先到先得)", A.ENOUGH_SEGMENTS == 12
          and _const_line("ENOUGH_SEGMENTS").startswith("ENOUGH_SEGMENTS = 12"))
    # ★ 2026-09-19 用户要求"精准找每个州人数最多的路段": 必须按达人数排名, 不再先到先得
    _all_src = "\n".join(_SRC)
    check("(S8) 选路段改成【按运动达人数排名取最大】",
          "seg_cands" in _all_src and "_ranked = sorted(" in _all_src
          and "seg_cands[sid] = n_ath" in _all_src,
          "seg_cands / 排名 代码在位")
    check("(S8) 达人数与粉丝数读取支持中文界面",
          "运动达人" in _all_src and "关注者" in _all_src,
          "中文标签已在读达人数/粉丝数的 JS 里")
    check("(S8) ZOOM_MAX_STEPS = 8 / ZOOM_MIN_STEPS = 6",
          A.ZOOM_MAX_STEPS == 8 and A.ZOOM_MIN_STEPS == 6
          and _const_line("ZOOM_MAX_STEPS").startswith("ZOOM_MAX_STEPS = 8")
          and _const_line("ZOOM_MIN_STEPS").startswith("ZOOM_MIN_STEPS = 6"))
    check("(S8) 平移循环用 range(PAN_ROUNDS), 不再写死 16",
          any("for rnd in range(PAN_ROUNDS)" in x for x in _SRC)
          and not any("range(16)" in x for x in _SRC))
    check("(S8) find_markers 里 timeout=8000 且只重试 2 轮, 旧值 12000/20000 已清干净",
          "page.screenshot(timeout=8000)" in _fm_blk
          and "for _try in range(2)" in _fm_blk
          and "timeout=12000" not in _fm_blk
          and "timeout=20000" not in _fm_blk
          and "return None" in _fm_blk)
    check("(S8) 旧死代码(见标记再多放 4 级 / ZOOM_EXTRA_STEPS)不存在",
          not any(k in x for x in _SRC
                  for k in ("ZOOM_EXTRA_STEPS", "再放大4级", "_first_z")))
    # ★ 选路段点击后的等待: 固定 sleep(1.8) -> 有界轮询 wait_text(timeout=1.8)
    check("(S8) 选路段点击后是有界轮询 wait_text(timeout=1.8), 不再固定 sleep(1.8)",
          any('wait_text(page,' in x for x in _SRC)
          and any("timeout=1.8, key=\"segpop\"" in x for x in _SRC)
          and not any("time.sleep(1.8)" in x for x in _SRC))

    # ==================== (S9) ★ 风控闸门 rate_gate ====================
    check("(S9) 闸门间隔: nav 6.0s / api 1.5s / act 0.6s",
          (A._RATE["nav"]["min_gap"], A._RATE["api"]["min_gap"],
           A._RATE["act"]["min_gap"]) == (6.0, 1.5, 0.6),
          f"{ {k: v['min_gap'] for k, v in A._RATE.items()} }")
    _waits = []
    _so_o = A.sleep_or_stop
    A.sleep_or_stop = lambda sec: _waits.append(sec)
    try:
        # ★ 2026-09-19 并发改造后必须显式清作用域: 前面的场景跑过 collect_regions,
        #   已经把"本线程的账号作用域"设上了; 不清的话 rate_gate 会走【按号桶】,
        #   下面写进默认桶的 last 就被忽略(实测算出 267 秒的离谱等待)。
        A.set_rate_scope("")
        A._RATE_BUCKETS.clear()
        A._RATE["act"]["last"] = time.time()          # 刚放过一个动作
        A.rate_gate("act")                            # 紧接着再来一个 -> 必须补等
        A._RATE["api"]["last"] = time.time() - 99     # 早就冷却好了
        A.rate_gate("api")                            # -> 不该等
    finally:
        A.sleep_or_stop = _so_o
    check("(S9) 超速补等(相邻动作 <0.6s 必须等) 且等待走 sleep_or_stop(可被停止键打断)",
          len(_waits) == 1 and 0 < _waits[0] <= 0.6, f"等待={_waits}")
    # ★ 新增: 按号分桶 —— 每个号各有一份独立预算(用户要的"并发真并行")
    _waits2 = []
    A.sleep_or_stop = lambda sec: _waits2.append(sec)
    try:
        A._RATE_BUCKETS.clear()
        A.set_rate_scope("seq3")
        A.rate_gate("act")            # 号3 用掉一次
        A.set_rate_scope("seq4")
        A.rate_gate("act")            # 号4 紧接着 -> 【不该等】(各自一份预算)
        A.set_rate_scope("seq3")
        A.rate_gate("act")            # 号3 再来 -> 【必须补等】
    finally:
        A.sleep_or_stop = _so_o
    check("(S9) 按号分桶: 号4 不受号3 的额度影响, 但号3 自己第二次要补等",
          len(_waits2) == 1 and 0 < _waits2[0] <= 0.6, f"等待={_waits2}")
    A.set_rate_scope("")
    A._RATE_BUCKETS.clear()
    check("(S9) 三种动作都被闸门接管(nav/api/act 全在表里, 不是只挡点击)",
          set(A._RATE) == {"nav", "api", "act"}
          and sum(1 for x in _SRC if 'rate_gate("' in x) >= 4,
          f"源码调用点={sum(1 for x in _SRC if 'rate_gate(\"' in x)}")

    # ==================== (S10) ★ 单号时间预算 collect_max_minutes ====================
    class Clock:
        """只用假 time(): 每次读数往前跳 step 秒; 其余属性委托真 time 模块。

        ★ 只对主线程生效: 引擎的停顿看门狗跑在子线程里(本自测已把它关掉,
          这里再兜一层), 绝不能让它读到被拨快的假时钟而 os._exit(9)。
        """

        def __init__(self, step):
            self.step, self.t = step, _real_time.time()

        def time(self):
            if threading.current_thread() is not threading.main_thread():
                return _real_time.time()
            v = self.t
            self.t += self.step
            return v

        def sleep(self, *_a, **_k):
            return None

        def __getattr__(self, k):
            return getattr(_real_time, k)

    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100,
            cfg_extra={"collect_max_minutes": None}, clock=Clock(15000))
    out, err = e.run()
    check("(S10) 缺省预算 = 240 分钟: 到点打 [quota] 已达单号时间上限 240 分钟 并 break",
          err is None and out == []
          and log_has(e.logs, "[quota] 已达单号时间上限 240 分钟, 停止采集")
          and not log_has(e.logs, "[region] ====="),
          f"out={out!r} err={err!r}")
    e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100,
            cfg_extra={"collect_max_minutes": 1}, clock=Clock(61))
    out, err = e.run()
    check("(S10) 配置 collect_max_minutes=1 生效: 上限 1 分钟就停, 不进任何地区",
          err is None and out == []
          and log_has(e.logs, "[quota] 已达单号时间上限 1 分钟, 停止采集")
          and not log_has(e.logs, "[region] ====="),
          f"out={out!r} err={err!r}")

    # ==================== (S11) ★ 死地区跳过 ====================
    # 零标记且最佳级别也零标记 -> 跳过平移; 连续 4 个 -> 停止采集
    zp = ZoomPage([0] * 8)
    e = Env(home="Chicago, Illinois", regions=["New York", "Wisconsin", "Iowa", "Ohio"],
            auto=False, rows=100, page=zp)
    out, err = e.run()
    _regs = [x for x in e.logs if x.startswith("[region] =====")]
    check("(S11) 零标记地区直接跳过平移(不打第N/8轮), 连续 4 个 -> 停止采集",
          err is None and out == [] and len(_regs) == 4
          and log_has(e.logs, "零标记零路段, 跳过平移(连续空 4 个)")
          and log_has(e.logs, "[region] 连续 4 个空地区, 停止采集")
          and not log_has(e.logs, "第1/8轮"),
          f"进了{len(_regs)}个地区")
    check("(S11) 跳过不是崩溃: 正常收尾(未达标), 没有 [region] 异常",
          log_has(e.logs, "[quota] 只采到 0/200 未达标")
          and not log_has(e.logs, "异常:"))

    # ==================== (S12) ★ append_task_url 判重 / 落盘失败 ====================
    _unit = TMP / "unit_task"
    _unit.mkdir(parents=True, exist_ok=True)
    _out_o, _seen_o = A.COLLECT_OUT, A.COLLECT_SEEN
    A.COLLECT_OUT = _unit / "out.txt"
    A.COLLECT_SEEN = _unit / "seen.json"
    try:
        if hasattr(A, "_OUT_HAVE"):
            A._OUT_HAVE["built"] = False
            A._OUT_HAVE["set"] = set()
        _t1 = A.new_task_ctx(target=200, mode="selftest")
        _s1 = A.new_account_ctx(_t1, "7")
        _u = "https://www.strava.com/athletes/unit1"
        _w1 = A.append_task_url(_s1, _u)
        _w2 = A.append_task_url(_s1, _u)
        _n1 = sum(1 for x in _s1["path"].read_text(encoding="utf-8").splitlines()
                  if x and not x.startswith("#"))
        check("(S12) 首写返回 True; 同一条第二次写返回 False 且不落第二行",
              _w1 is True and _w2 is False and _n1 == 1, f"{_w1}/{_w2}/行数{_n1}")
        if hasattr(A, "_OUT_HAVE"):
            A._OUT_HAVE["built"] = False       # 模拟下一次任务重建索引
            A._OUT_HAVE["set"] = set()
        _s2 = A.new_account_ctx(A.new_task_ctx(target=200, mode="selftest"), "8")
        _w3 = A.append_task_url(_s2, _u)
        check("(S12) 历史成果里已有(重建索引后) -> 返回 False(极致去重, 不计数不重写)",
              _w3 is False, f"返回={_w3}")
        _bad = {"t_start": _s2["t_start"], "tid": "99990101_000000", "seq": "9",
                "urls": {}, "path": _unit}      # path 是目录 -> 写入必失败
        _w4 = A.append_task_url(_bad, "https://www.strava.com/athletes/unit2")
        check("(S12) 落盘失败(路径是目录) -> 返回 False 且 ctx['write_err'] 有值 + 日志",
              _w4 is False and bool(_bad.get("write_err"))
              and log_has(CAP.lines, "[task] 落盘失败"),
              f"返回={_w4} write_err={_bad.get('write_err')!r}")
    finally:
        A.COLLECT_OUT, A.COLLECT_SEEN = _out_o, _seen_o
        shutil.rmtree(_unit, ignore_errors=True)

    # 落盘失败时【绝不向中心报 pass】(否则又造出"中心说采到了、本地没有"的缝)
    _unit_dir_ref = [TMP / "unit_bad"]
    _oof = A._open_task_file
    A._open_task_file = lambda ctx, kind="acct": _unit_dir_ref[0]
    _unit_dir_ref[0].mkdir(parents=True, exist_ok=True)
    try:
        e = Env(home="Chicago, Illinois", regions=["New York"], auto=False, rows=100,
                cfg_extra={})
        out, err = e.run()
    finally:
        A._open_task_file = _oof
        shutil.rmtree(_unit_dir_ref[0], ignore_errors=True)
    _pass_reported = [x for x in e.calls["finish"] if x[1] == "pass"]
    check("(S13) 落盘失败: 不计数(返回 0 条) + 日志'落盘失败, 本条不上报中心'",
          out == [] and log_has(e.logs, "落盘失败, 本条不上报中心"),
          f"out={out!r}")
    check("(S13) 落盘失败时没有给中心报 pass / 没写 collect",
          _pass_reported == [] and e.calls["collect"] == [],
          f"pass上报={len(_pass_reported)} collect={len(e.calls['collect'])}")

finally:
    time.sleep = _real_sleep
    for k, v in _reals.items():
        setattr(A, k, v)

# ---------------------------------------------------------------- 汇总
_fail = [n for n, ok in _results if not ok]
print("-" * 78)
print(f"用例: {len(_results)}  通过: {len(_results) - len(_fail)}  失败: {len(_fail)}")
for n in _fail:
    print("  [FAIL] " + n)

_logf = ROOT / "_自测_采集_ADS.log"
_logf.write_text("\n".join(CAP.lines), encoding="utf-8")
print(f"引擎完整日志({len(CAP.lines)}行)已写入: {_logf.name}")
shutil.rmtree(TMP, ignore_errors=True)
print("结果:", "全部通过" if not _fail else f"有 {len(_fail)} 项失败")
sys.exit(1 if _fail else 0)
