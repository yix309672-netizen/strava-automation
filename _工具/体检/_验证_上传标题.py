# -*- coding: utf-8 -*-
"""验证上传前的「标题 + 类型」设置(用假页面, 不需要浏览器)。

★★ 为什么最后落在改上传页、而不是改素材文件 ★★
   在真页面上探过, 上传页每个文件一张卡片, 卡片上自带:
       <input name="name">                                  <- Strava 已自动填好
       <div class="... sport-type"><div class="selection">Workout</div>
   Strava 自动填的是「时间段 + 活动类型」, 默认类型 Workout; 而那个"时间段"
   是按【账号所在时区】算的 —— 实测本地早上 07:38 的素材被填成
   "Afternoon Workout"。所以改素材里的时间/名字都管不住标题。

★★ 为什么必须按"可见"等 ★★
   真机验证抓到: 解析没完成时表单是 display:none, 输入框 count 得到 3 个、
   fill 却一张一张等到 30 秒超时。而且 form.good 永远带 hidden 类
   (靠内联 display:block 显示), 所以只能 :visible, 不能 :not(.hidden)。

本脚本验 10 件事:
  ① 每张卡片的标题都被填成 Morning Run
  ② 每张卡片的类型都被点成 Run
  ③ 卡片逐个出现也要全部设上(等它稳, 不是看一眼就动手)
  ④ 有重复文件(可见卡片少于本批数量)时不死等, 能设几张设几张
  ⑤ 一张卡片都没有时返回 0, 不抛异常
  ⑥ 用的是 fill()/click(), 不是 JS 赋 value
  ⑦ 按 :visible 等卡片, 而不是数个数
  ⑧ 必须在点"保存并查看"之前调用, 且带上本批数量
  ⑨ 旧路子(_retime/_stage 改素材文件)已彻底清掉
  ⑩ 两个引擎逐字相同
"""
import ast
import importlib.util
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
TITLE, SPORT = "Morning Run", "Run"


class _FakeTime:
    """time.time() 每次 +1 秒、sleep 空转 —— 等卡片的循环不会真等 30 秒。"""
    def __init__(self):
        self.t = 0.0

    def time(self):
        self.t += 1.0
        return self.t

    def sleep(self, _s):
        pass


class _Loc:
    """假的 playwright Locator, 只认 set_act_title 用到的那几个方法。"""

    def __init__(self, page, path, idx=None):
        self.p, self.path, self.idx = page, path, idx

    def count(self):
        # 只有顶层 "form.good:visible" 有意义(其余都是卡片内部的子选择器)
        if ">>" not in self.path and "form.good" in self.path:
            return self.p.next_visible()
        return self.p.visible

    def nth(self, i):
        return _Loc(self.p, self.path, i)

    @property
    def first(self):
        return _Loc(self.p, self.path, self.idx)

    def locator(self, sel):
        return _Loc(self.p, self.path + " >> " + sel, self.idx)

    def fill(self, v):
        self.p.fills.append((self.idx, v))

    def click(self, timeout=None):
        self.p.clicks.append((self.idx, self.path))


class _Page:
    def __init__(self, visible=3, appear=None):
        self.visible = visible
        self.seq = list(appear or [])
        self.fills, self.clicks = [], []

    def next_visible(self):
        if self.seq:
            self.visible = self.seq.pop(0)
        return self.visible

    def locator(self, sel):
        return _Loc(self, sel)


def _upload_gate(path):
    """从 run_one 里揪出"真正去上传"那个 if 的判断表达式(body 里有 upload_gpx)。"""
    code = path.read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(code)):
        if isinstance(n, ast.If):
            if "upload_gpx(" in (ast.get_source_segment(code, n) or ""):
                return ast.get_source_segment(code, n.test) or ""
    return ""


def _fn_src(path, name):
    code = path.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(code))
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(code, node)


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True
for tag, path in (("ADS", ROOT / "主脚本" / "strava_ads.py"),
                  ("BIT", ROOT / "主脚本" / "strava_bit.py")):
    m = load(path, "_t_" + tag)
    m.time = _FakeTime()
    cases = []

    # ①②③ 一批 3 张, 卡片逐个出现: 0,0,1,2,3
    pg = _Page(visible=0, appear=[0, 0, 1, 2, 3])
    got = m.set_act_title(pg, 3)
    cases.append(("① 3 张卡片的标题都填了",
                  len(pg.fills) == 3 and all(v == TITLE for _, v in pg.fills),
                  f"{pg.fills}"))
    sel = [c for c in pg.clicks if c[1].endswith(".selection")]
    run = [c for c in pg.clicks if f"li[data-value='{SPORT}']" in c[1]]
    cases.append(("② 3 张卡片都点开了类型下拉", len(sel) == 3, f"{len(sel)} 次"))
    cases.append((f"② 3 张卡片都点了 {SPORT}", len(run) == 3, f"{len(run)} 次"))
    cases.append(("③ 卡片逐个出现也全设上", got == 3 and len(pg.fills) == 3,
                  f"返回 {got}, 填了 {len(pg.fills)} 张"))

    # ④ 有重复文件: 本批 5 个, 只有 2 张可见 -> 不死等, 设 2 张
    m.time = _FakeTime()
    pg2 = _Page(visible=2)
    got2 = m.set_act_title(pg2, 5)
    cases.append(("④ 可见卡片少于本批时不死等", got2 == 2 and len(pg2.fills) == 2,
                  f"返回 {got2}(本批 5)"))
    cases.append(("④ 也没卡到 30 秒上限", m.time.t < 30, f"耗时 {m.time.t:.0f} 秒(假时钟)"))

    # ⑤ 一张都没有
    m.time = _FakeTime()
    pg3 = _Page(visible=0)
    try:
        got3 = m.set_act_title(pg3, 3)
        cases.append(("⑤ 没卡片时返回 0 且不抛异常", got3 == 0 and not pg3.fills,
                      f"返回 {got3}"))
    except Exception as e:
        cases.append(("⑤ 没卡片时返回 0 且不抛异常", False, f"抛了 {e!r}"))

    # ⑥⑦⑧⑨ 看源码
    src = path.read_text(encoding="utf-8")
    body = _fn_src(path, "set_act_title")
    cases.append(("⑥ 用的是 fill()/click()",
                  ".fill(" in body and ".click(" in body and ".value =" not in body,
                  "没用 JS 赋 value"))
    cases.append(("⑦ 按 :visible 等卡片", ":visible" in body,
                  "form.good:visible" if ":visible" in body else "★ 没按可见过滤"))
    ug = _fn_src(path, "upload_gpx")
    # ★ 2026-09-24 起标题跟素材走: 调用点变成 set_act_title(page, len(batch), *sport_of(batch))
    i_call = ug.find("set_act_title(page, len(batch)")
    saves = [x for x in (ug.find('"保存并查看"'), ug.find('"Save & View"')) if x > 0]
    i_save = min(saves) if saves else 10 ** 9
    cases.append(("⑧ 在点『保存并查看』之前调用且带本批数量",
                  ug.count("set_act_title(") == 1 and 0 < i_call < i_save
                  and "sport_of(batch)" in ug,
                  f"位置 {i_call} < 保存按钮 {i_save}"))
    stale = [s for s in ("_retime(", "_stage(", "_prepare(", "MORNING_H") if s in src]
    cases.append(("⑨ 旧的改素材路子已清干净", not stale, f"残留={stale or '无'}"))
    # ⑪ ★ 老号也得能上传: 上传那一步不能被 skip_setup 挡住
    gate = _upload_gate(path)
    cases.append(("⑪ 上传不再被 skip_setup 挡住",
                  bool(gate) and "skip_setup" not in gate, f"判断式 = {gate}"))
    cases.append(("   ACT_TITLE / ACT_SPORT 默认值对(兜底)",
                  m.ACT_TITLE == TITLE and m.ACT_SPORT == SPORT,
                  f"{m.ACT_TITLE!r} / {m.ACT_SPORT!r}"))
    # ⑫ ★ 2026-09-24 用户要"洛杉矶骑行轨迹": 素材是什么运动就写什么标题/类型。
    #    以前写死 Run, Sport="Biking" 的 TCX 会被强行改成跑步。
    import tempfile
    _td = Path(tempfile.mkdtemp())
    (_td / "ride.tcx").write_text('<Activity Sport="Biking">', encoding="utf-8")
    (_td / "run.tcx").write_text('<Activity Sport="Running">', encoding="utf-8")
    (_td / "junk.tcx").write_text("not xml at all", encoding="utf-8")
    _ride = m.sport_of([_td / "ride.tcx"])
    _run = m.sport_of([_td / "run.tcx"])
    cases.append(("⑫ 骑行素材 -> Morning Ride / Ride",
                  _ride == ("Morning Ride", "Ride"), f"{_ride}"))
    cases.append(("⑬ 跑步素材 -> Morning Run / Run",
                  _run == ("Morning Run", "Run"), f"{_run}"))
    cases.append(("⑭ 认不出的素材退回跑步(老行为)",
                  m.sport_of([_td / "junk.tcx"]) == (TITLE, SPORT)
                  and m.sport_of([]) == (TITLE, SPORT)
                  and m.sport_of(None) == (TITLE, SPORT),
                  "乱文件/空/None 都退回"))

    print("=" * 74)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:32s} {detail}")

# ⑩ 两个引擎逐字相同
a = _fn_src(ROOT / "主脚本" / "strava_ads.py", "set_act_title")
b = _fn_src(ROOT / "主脚本" / "strava_bit.py", "set_act_title")
if a != b:
    ok_all = False
print("=" * 74)
print(f"   {'OK ' if a == b else '★  '}{'⑩ 两个引擎逐字相同':32s} {a == b}")

# ⑮ sport_of 也必须两边一样(标题跟素材走之后, 它才是决定类型的那段)
sa = _fn_src(ROOT / "主脚本" / "strava_ads.py", "sport_of")
sb = _fn_src(ROOT / "主脚本" / "strava_bit.py", "sport_of")
if sa != sb or not sa:
    ok_all = False
print(f"   {'OK ' if sa and sa == sb else '★  '}{'⑮ sport_of 两边逐字相同':32s} {bool(sa) and sa == sb}")

print()
print("★★★ 标题/类型跟着素材走: 骑行 Morning Ride/Ride, 跑步 Morning Run/Run ★★★"
      if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
