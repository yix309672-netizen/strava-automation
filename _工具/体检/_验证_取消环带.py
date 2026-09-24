# -*- coding: utf-8 -*-
r"""验证「取消环带距离，只要美国境内就采」。

用户 2026-09-23: "把环带距离取消。只要是美国境内的都采集。"

★★ 做法不是删代码, 而是把环带放成 0 ~ 20000km ★★
   in_target_band 有个关键性质: 它【只因为"太近/太远"淘汰人】——
   认不出位置、只认到州, 都返回"不确定=保留"(见 geo_cities 里那个函数)。
   所以上限一放大, 距离这关永远通过, 只剩"美国境内"那一道。
   顺带: states_in_band(0, 20000) 自然返回【全美所有州】, 采集州扩展不用改。

验 8 件事(两个引擎各一遍):
  ① config 里 geo_band_min_km=0 / geo_band_max_km=20000
  ② 引擎读出来就是 0 / 20000(★ 不能被 `or` 把 0 吃掉)
  ③ 圆心在洛杉矶、人在芝加哥(2800km) -> 保留(旧环带会判"太远")
  ④ 圆心在芝加哥、人也在芝加哥(0km)   -> 保留(旧环带会判"太近")
  ⑤ 人在多伦多 -> 照样淘汰(美国境内这条不能松)
  ⑥ 认不出位置 -> 保留(不误杀)
  ⑦ states_in_band(0, 20000) 覆盖全美(>=50 个州)
  ⑧ 源码里没有 `geo_band_*_km") or ...` 那种会吃掉 0 的写法
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
CHI = (41.878, -87.630, "Chicago")
LA = (34.052, -118.244, "Los Angeles")


class FakePage:
    def __init__(self, m, loc):
        self.m, self.loc = m, loc

    def evaluate(self, js, *_a):
        if js == self.m.JS_READ_LOC:
            return {"loc": self.loc}
        return {"followers": 10, "following": 5, "recent_dates": [], "four_week": 3}


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    m.rate_gate = lambda *a, **k: None
    m.goto_retry = lambda *a, **k: None
    m.wait_text = lambda *a, **k: True
    m.check_stop = lambda *a, **k: None
    m.CFG = {"geo_band_min_km": 0, "geo_band_max_km": 20000,
             "us_only": True, "us_only_strict": False}
    return m


def no_comments(p):
    """去掉注释【和 docstring】后的源码。

    ★ 必须连 docstring 一起去掉: 新函数为了讲清根因, 会把旧写法原样引一遍
      ("老写法 `CFG.get("geo_band_min_km") or 100` 会把 0 变成 100") ——
      只剥 # 注释的话, 会把自己的说明文档当成残留代码报出来(刚踩过)。
    """
    import ast
    src = p.read_text(encoding="utf-8")
    drop = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                drop.add(tok.start[0])
    except Exception:
        pass
    try:
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) \
                    and isinstance(n.value.value, str):
                drop.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    except Exception:
        pass
    return "\n".join(l for i, l in enumerate(src.splitlines(), 1) if i not in drop)


ok_all = True
for tag, path in ENGINES.items():
    m = load(path, "_g_" + tag)
    cases = []

    band = (m.geo_band_km() if hasattr(m, "geo_band_km")
            else m.geo_band_limits(m.CFG["geo_band_min_km"], m.CFG["geo_band_max_km"]))
    cases.append(("② 引擎读出 0 / 20000(0 没被吃掉)", band == (0.0, 20000.0),
                  f"得到 {band}"))

    def chk(loc, center):
        return m.check_athlete(FakePage(m, loc), "1", 200, geo_filter=True,
                               us_only=True, us_only_strict=False,
                               center=center, recent_days=0)

    ok3, why3 = chk("Chicago, Illinois", LA)
    cases.append(("③ 圆心洛杉矶·人在芝加哥 -> 保留", ok3 is True, f"{why3}"))
    ok4, why4 = chk("Chicago, Illinois", CHI)
    cases.append(("④ 圆心芝加哥·人也在芝加哥 -> 保留", ok4 is True, f"{why4}"))
    ok5, why5 = chk("Toronto, Ontario, Canada", CHI)
    cases.append(("⑤ 人在多伦多 -> 照样淘汰", ok5 is False, f"{why5}"))
    ok6, why6 = chk("", CHI)
    cases.append(("⑥ 认不出位置 -> 保留(不误杀)", ok6 is True, f"{why6}"))

    code = no_comments(path)
    bad = ('geo_band_min_km") or' in code) or ('geo_band_max_km") or' in code)
    cases.append(("⑧ 没有会吃掉 0 的 `or` 写法", not bad,
                  "★ 还在" if bad else "已改成显式判空"))

    print("=" * 78)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")

# ⑦ 全美覆盖(直接用 geo_cities)
try:
    import geo_cities as GC
    sts = GC.states_in_band(41.878, -87.630, 0, 20000)
    old = GC.states_in_band(41.878, -87.630, 100, 1000)
    print("=" * 78)
    print(f"   {'OK ' if len(sts) >= 50 else '★  '}"
          f"{'⑦ 环带放开后覆盖全美':34s} {len(sts)} 个州(旧环带只有 {len(old)} 个)")
    if len(sts) < 50:
        ok_all = False
except Exception as e:
    print(f"   ★ ⑦ 跑不了 geo_cities: {str(e)[:80]}")
    ok_all = False

print("=" * 78)
cfg = (ROOT / "配置" / "config.json").read_text(encoding="utf-8")
dcfg = (ROOT / "_分发给同事" / "config.json").read_text(encoding="utf-8")
c1 = '"geo_band_min_km": 0' in cfg and '"geo_band_max_km": 20000' in cfg
c2 = '"geo_band_min_km": 0' in dcfg and '"geo_band_max_km": 20000' in dcfg
if not (c1 and c2):
    ok_all = False
print(f"   {'OK ' if c1 else '★  '}{'① 项目 config 已是 0/20000':34s} {c1}")
print(f"   {'OK ' if c2 else '★  '}{'① 发行 config 已是 0/20000':34s} {c2}")
print()
print("★★★ 环带已取消, 只剩「美国境内」这一条 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
