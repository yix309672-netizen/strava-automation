# -*- coding: utf-8 -*-
"""验证合并后的 geo_cities, 以及"只要美国境内"的判定到底对不对。

★ 一次说清 lookup 与 is_us_location 的分工(我上一版测试就错在这里):
    lookup()          —— 只按【城市名】查坐标, 【故意不看国家部分】。
                          所以 "Paris, France" 会命中美国阿肯色州的 Paris。
                          这是设计如此(它只管坐标, 不管国别)。
    is_us_location()  —— 才管国别。它【先看地区段】:
                          "Paris, France" 的地区段是 France -> 直接判境外,
                          根本不会去用 lookup 的结果。
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import geo_cities as g  # noqa: E402


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

PASS, FAIL = [], []


def ck(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-46s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


print("=" * 80)
print("一、geo_cities 合并结果")
print("=" * 80)
print("    CITY_XY 键数 = %d" % len(g.CITY_XY))
ck("CITY_XY 键数 >= 50000", len(g.CITY_XY) >= 50000, True)
ck("州表仍是 51 个", len(g.STATE_NAME2ABBR), 51)

print()
print("    lookup() 抽查(它只管坐标, 不管国别):")
for loc, want_conf in (("Wahiawa, Hawaii", "city"),
                       ("Wahiawa", "city"),
                       ("Truth or Consequences, New Mexico", "city"),
                       ("Cut Bank, Montana", "city"),
                       ("Medicine Lodge, Kansas", "city"),
                       ("Chicago, Illinois", "city"),
                       ("Vientiane", "none"),
                       ("Beijing, China", "none")):
    la, lo, conf, matched = g.lookup(loc)
    ck("%s -> %s" % (loc, want_conf), conf, want_conf)

print()
print("    同名小镇不能互相抢(裸键只在全国唯一时才加):")
for loc, want_st in (("Springfield, Illinois", "il"),
                     ("Springfield, Missouri", "mo"),
                     ("Springfield, Massachusetts", "ma"),
                     ("Springfield", None)):
    la, lo, conf, matched = g.lookup(loc)
    if want_st is None:
        ck("Springfield(裸) 有坐标即可", la is not None, True)
    else:
        _, _, st = g.CITY_XY.get(matched, (0, 0, "?"))
        ck("%s 落到 %s" % (loc, want_st), st, want_st)

# ---------------- is_us_location ----------------
print()
print("=" * 80)
print("二、is_us_location() —— 只要美国境内")
print("=" * 80)
spec = importlib.util.spec_from_file_location(
    "eng", ROOT / "主脚本" / "strava_ads.py")
m = importlib.util.module_from_spec(spec)
sys.modules["eng"] = m
spec.loader.exec_module(m)

CASES = [
    # (位置, 期望)  True=美国 / False=境外 / None=认不出
    ("Chicago, Illinois", True),
    ("North Chicago, Illinois", True),
    ("New York, NY", True),
    ("North Hills , CA", True),
    ("Wahiawa, Hawaii", True),          # ★ 小地方, 靠州名规则
    ("Wahiawa", True),                  # ★ 裸名, 靠补全后的表
    ("Truth or Consequences, New Mexico", True),
    ("Cut Bank, Montana", True),
    ("Medicine Lodge, Kansas", True),
    ("Chicago, Illinois, United States", True),   # 三段式
    ("Chicago, Illinois, USA", True),             # 美国别称
    ("Paris, France", False),           # ★ lookup 会命中美国 Paris, 但这里必须判境外
    ("Toronto, Ontario", False),        # ★ 同上(美国有个 Toronto, Ohio)
    ("Vientiane, Laos", False),
    ("London, England", False),
    ("Beijing, China", False),
    ("Vientiane", None),                # 只有城市名且不在美国表 -> 认不出(默认保留)
    ("", None),
]
for loc, want in CASES:
    got = m.is_us_location(loc)
    ck("%-36s -> %s" % (repr(loc)[:36], {True: "美国", False: "境外", None: "认不出"}[want]),
       got, want)

print()
print("=" * 80)
if FAIL:
    print("★ 失败 %d 项:" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("✓ 通过 %d 项: 美国地名表已补全(%d 键) · 国别判定 True/False/None 三态正确"
      % (len(PASS), len(g.CITY_XY)))
