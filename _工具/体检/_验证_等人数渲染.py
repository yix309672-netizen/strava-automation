# -*- coding: utf-8 -*-
r"""验证「点完地图标记要等人数渲染出来再读」。

用户 2026-09-22: "脚本点击路线的时候要有延迟。不然点一下就采样了。
                人数都没出来显示就是0"

★★ 问题在哪 ★★
   采集时点地图上的标记, 原流程是:
       page.mouse.click(...)
       wait_text(..., key="segpop")     <- 只等【弹窗里的路段链接】
       sid = segment_from_popup(page)
       n_ath = popup_athletes(page)     <- ★ 立刻读人数
   链接比人数先渲染出来, 所以这一步经常读到 -1, 上层记 0 ——
   日志看着像"这个路段没人", 其实只是还没画出来。

★★ 怎么验 ★★
   拿一个【假页面】: 前几次问"人数出来了吗"都回答"没有", 之后才回答"有了"。
   然后按源码里的顺序调引擎自己的 wait_text + popup_athletes:
     · 不先等 -> 读到 -1(复现用户看到的现象)
     · 先等   -> 读到真实数字
   这样验的是真代码, 不是我在测试里重写一遍。

验 7 件事(两个引擎各一遍):
  ① 先 wait_text 再读 -> 拿到真实人数
  ② 不 wait 直接读    -> -1（复现"显示就是0"）
  ③ 空标记(永远等不到)-> 等满超时也不报错, 读数仍是 -1
  ④ wait_text 用到的判定式来自模块常量 SEG_ATH_READY_JS(不是各写一份)
  ⑤ 源码里 wait_text(key="segath") 必须在 popup_athletes 之前
  ⑥ SEG_ATH_WAIT 有值且能被 config 覆盖
  ⑦ 两个引擎这三点逐字相同
"""
import importlib.util
import io
import sys
import tokenize
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
ENGINES = {"ADS": ROOT / "主脚本" / "strava_ads.py",
           "BIT": ROOT / "主脚本" / "strava_bit.py"}
REAL_COUNT = 179318


class FakePage:
    """假页面: 前 ready_after 次问"人数出来了吗"都说没有, 之后说有。"""

    def __init__(self, ready_after=3):
        self.ready_after = ready_after
        self.asks = 0
        self.reads = 0

    def evaluate(self, js, *_a):
        if "var t = document.body.innerText" in js:      # popup_athletes 的读取
            self.reads += 1
            return REAL_COUNT if self.asks > self.ready_after else -1
        if "test(document.body.innerText" in js:          # wait_text 的判定
            self.asks += 1
            return self.asks > self.ready_after
        return 0


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    # ★ 假时钟必须【会走】: 固定返回 0.0 的话, wait_text 里的
    #   `time.time() >= end` 永远不成立 -> 空标记那条会死循环(踩过)。
    box = {"t": 0.0}

    def _now():
        box["t"] += 0.5
        return box["t"]

    m.time = type("T", (), {"time": staticmethod(_now),
                            "sleep": staticmethod(lambda _s: None)})()
    return m


def no_comments(p):
    src = p.read_text(encoding="utf-8")
    drop = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                drop.add(tok.start[0])
    except Exception:
        pass
    return "\n".join(l for i, l in enumerate(src.splitlines(), 1) if i not in drop)


ok_all = True
for tag, path in ENGINES.items():
    m = load(path, "_a_" + tag)
    cases = []

    # ① 先等再读
    pg = FakePage(ready_after=3)
    m.wait_text(pg, m.SEG_ATH_READY_JS, timeout=2.5, key="segath")
    got = m.popup_athletes(pg)
    cases.append(("① 先等再读 -> 拿到真实人数", got == REAL_COUNT,
                  f"读到 {got}(问了 {pg.asks} 次)"))

    # ② 不等直接读（复现旧现象）
    pg2 = FakePage(ready_after=3)
    got2 = m.popup_athletes(pg2)
    cases.append(("② 不等直接读 -> -1(复现显示0)", got2 == -1,
                  f"读到 {got2}"))

    # ③ 空标记: 永远等不到
    pg3 = FakePage(ready_after=10 ** 9)
    m.wait_text(pg3, m.SEG_ATH_READY_JS, timeout=0.4, key="segath")
    got3 = m.popup_athletes(pg3)
    cases.append(("③ 空标记等满超时也不炸, 仍是 -1", got3 == -1,
                  f"读到 {got3}"))

    # ④ 判定式是模块常量
    cases.append(("④ 判定式来自 SEG_ATH_READY_JS", isinstance(m.SEG_ATH_READY_JS, str)
                  and "athletes" in m.SEG_ATH_READY_JS,
                  f"{len(m.SEG_ATH_READY_JS)} 字符"))

    # ⑤ 源码顺序: 先 wait(segath) 再 popup_athletes
    code = no_comments(path)
    i_wait = code.find('key="segath"')
    i_read = code.find("n_ath = popup_athletes(page)")
    cases.append(("⑤ 源码里先等(segath)再读", 0 < i_wait < i_read,
                  f"等@ {i_wait} < 读@ {i_read}"))

    # ⑥ 常量有值 + 可被 config 覆盖
    cases.append(("⑥ SEG_ATH_WAIT 有默认值", float(m.SEG_ATH_WAIT) > 0,
                  f"{m.SEG_ATH_WAIT} 秒"))
    cases.append(("⑥ 能被 config 的 seg_ath_wait 覆盖",
                  'CFG.get("seg_ath_wait")' in code, "读 CFG"))

    print("=" * 78)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:32s} {detail}")

# ⑦ 两边常量逐字相同
a = load(ENGINES["ADS"], "_c_a")
b = load(ENGINES["BIT"], "_c_b")
same = (a.SEG_ATH_READY_JS == b.SEG_ATH_READY_JS
        and float(a.SEG_ATH_WAIT) == float(b.SEG_ATH_WAIT))
if not same:
    ok_all = False
print("=" * 78)
print(f"   {'OK ' if same else '★  '}{'⑦ 两个引擎常量逐字相同':32s} {same}")
print()
print("★★★ 点完标记会等人数画出来再读 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
