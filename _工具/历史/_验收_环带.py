# -*- coding: utf-8 -*-
"""验收脚本①: 第2条环带口径（独立于子代理自测, 由验收方手写）

用法:  python _验收_环带.py
判定:  全部 PASS -> 退出码 0; 任一 FAIL -> 退出码 1
"""
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
sys.path.insert(0, str(WS))

import geo_cities as G  # noqa: E402

CHI = G.resolve_center("Chicago, Illinois")
LA = G.resolve_center("Los Angeles, CA")

FAILS = []
N = [0]


def check(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def band(loc, center=None, exempt=False, **kw):
    return G.in_target_band(loc, center=center, exempt_max=exempt, **kw)


print("=== 常量 ===")
check("BAND_MIN_KM == 100", G.BAND_MIN_KM == 100.0, G.BAND_MIN_KM)
check("BAND_MAX_KM == 1000 (原800)", G.BAND_MAX_KM == 1000.0, G.BAND_MAX_KM)

print("\n=== 圆心识别(每号自己的所在地) ===")
check("resolve_center('Chicago, Illinois') 是城市级",
      CHI[3] == "city" and abs(CHI[0] - 41.8781) < 0.5, CHI)
check("resolve_center 洛杉矶可用", LA[3] == "city" and abs(LA[0] - 34.05) < 0.5, LA)
check("resolve_center 认不出的地名 -> conf=none, 坐标 None",
      G.resolve_center("Nowhereville, ZZ")[0] is None
      and G.resolve_center("Nowhereville, ZZ")[3] == "none")
check("resolve_center 空 -> none", G.resolve_center("")[3] == "none")

print("\n=== 环带判定: 圆心=芝加哥 ===")
ok, why, conf, d, label = band("Chicago, IL", CHI)
check("芝加哥本地 -> 淘汰(太近)", ok is False, f"{ok} {why}")
ok, why, conf, d, label = band("Milwaukee, Wisconsin", CHI)
check("密尔沃基131km -> 保留", ok is True and 100 < d < 200, f"{ok} {why}")
ok, why, conf, d, label = band("Buffalo, NY", CHI)
check("水牛城~850km -> 保留", ok is True, f"{ok} {why}")
ok, why, conf, d, label = band("New York, NY", CHI)
check("纽约市 ~1140km -> 不豁免时淘汰(>1000)", ok is False and d > 1000, f"{ok} {why}")
ok, why, conf, d, label = band("New York, NY", CHI, exempt=True)
check("纽约来源 -> 豁免上限后保留", ok is True, f"{ok} {why}")
ok, why, conf, d, label = band("Chicago, IL", CHI, exempt=True)
check("纽约来源但仍太近 -> 依旧淘汰(豁免只管上限)", ok is False, f"{ok} {why}")

print("\n=== 环带判定: 圆心=洛杉矶 ===")
ok, why, conf, d, label = band("Los Angeles, CA", LA)
check("洛杉矶本地 -> 淘汰", ok is False, f"{ok} {why}")
ok, why, conf, d, label = band("New York, NY", LA)
check("纽约市 距洛杉矶~3900km -> 不豁免淘汰", ok is False and d > 3000, f"{ok} {why}")
ok, why, conf, d, label = band("New York, NY", LA, exempt=True)
check("纽约来源豁免 -> 保留(否则洛杉矶号一个都采不到)", ok is True, f"{ok} {why}")

print("\n=== 不误杀 / 兜底 ===")
ok, why, conf, d, label = band("", CHI)
check("没填所在地 -> 不确定(保留)", ok is None, f"{ok} {why}")
ok, why, conf, d, label = band("Nowhereville, ZZ", CHI)
check("认不出的地名 -> 不确定(保留)", ok is None, f"{ok} {why}")
ok, why, conf, d, label = band("IL", CHI)
check("只给州 -> 州级粗判不确定(保留)", ok is None, f"{ok} {why}")
ok, why, conf, d, label = band("Milwaukee, Wisconsin")
check("向后兼容: 不传圆心 -> 仍可用(HUBS兜底)", ok is True, f"{ok} {why}")

print("\n=== 自动选州 states_in_band ===")
sts = G.states_in_band(CHI[0], CHI[1])
names = [s[1] for s in sts]
kms = [round(s[2]) for s in sts]
check("返回非空且按距离升序", len(sts) > 3 and kms == sorted(kms), list(zip(names[:6], kms[:6])))
check("全部在 100~1000km 内", all(100 <= s[2] <= 1000 for s in sts))
check("自动选区里没有把纽约算进来也不影响(纽约是必扫)",
      "New York" not in names or True, "New York in auto=" + str("New York" in names))

print("\n=== 纽约识别 ===")
for t in ("New York", "NY", "ny", "New York, NY", "纽约"):
    check(f"is_new_york({t!r})", G.is_new_york(t) is True)
check("is_new_york('Ohio') 为假", not G.is_new_york("Ohio"))
check("state_center('NY') 可用", G.state_center("NY") is not None, G.state_center("NY"))

print("\n================ 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for f in FAILS:
    print("  ✗ " + f)
sys.exit(1 if FAILS else 0)
