# -*- coding: utf-8 -*-
"""验证: 只采美国境内 —— 尤其是【德国的号不能被采进来】。

2026-09-25 用户实测报:"采集的怎么还有德国的账号呢"。
跑一遍发现 `is_us_location` 漏了两条路:
    ① 只写城市名 -> 撞上美国同名小镇, 判成"确定美国"
         Berlin(NH) Hamburg(PA) Munich(ND) Stuttgart(AR) Cologne(NJ)
    ② 认不出(None) -> us_only_strict 没开时一律保留
         "Germany" 单独一个词、"Frankfurt" 美国没这个镇
修法: 加 _FOREIGN_CITY / _FOREIGN_COUNTRY 两张"确定境外"表 + 打开严格模式。

这个脚本必须能挡住"以后又放开" —— 两张表被删/被改宽, 或者严格模式被关掉, 都要报出来。
"""
import importlib.util, json, os, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
ok_all = True


def case(name, ok, detail=""):
    global ok_all
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name:34s} {detail}")


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


# 必须淘汰的(德国 + 其它明显境外) / 必须保留的(正常美国)
FOREIGN = ["Berlin, Germany", "Berlin", "Hamburg", "Hamburg, Germany", "Munich",
           "Munich, Germany", "Stuttgart", "Cologne", "Frankfurt", "Dresden",
           "Germany", "Deutschland", "Bavaria, Germany", "Paris", "London",
           "Toronto", "Vancouver", "Amsterdam", "Zurich", "Tokyo", "Sydney"]
US = ["Chicago, Illinois", "New York, NY", "Chicago", "Denver", "Boston",
      "Los Angeles, California", "Austin, Texas", "Seattle"]

os.chdir(str(ROOT / "主脚本"))
for eng, tag in (("strava_ads.py", "ADS"), ("strava_bit.py", "BIT")):
    print(f"===== {tag} =====")
    m = load(ROOT / "主脚本" / eng, "us_" + tag)
    miss = [x for x in FOREIGN if m.is_us_location(x) is not False]
    case("德国等境外一律淘汰", not miss, f"漏网={miss or '无'}")
    killed = [x for x in US if m.is_us_location(x) is not True]
    case("正常美国人不受影响", not killed, f"误杀={killed or '无'}")
    case("城市名撞车已被拦住(Berlin)",
         m.is_us_location("Berlin") is False, "不再靠美国同名小镇")
    case("裸国家名已被拦住(Germany)",
         m.is_us_location("Germany") is False, "不再落到'认不出'")
    src = (ROOT / "主脚本" / eng).read_text(encoding="utf-8")
    case("两张境外表都在", "_FOREIGN_CITY = {" in src and "_FOREIGN_COUNTRY = {" in src)
    # ★★ 2026-09-25 用户要求:「所有采集地区锁死美国地区。别的国家一律不要。」★★
    #   硬锁: check_athlete 里【不再读 config】。以前是
    #   CFG.get("us_only_strict", False) —— 严格模式默认关, 关着就放行"认不出"的,
    #   德国号正是这么进来的。有人把 config 改回去这条断言就会红。
    case("美国锁不读 config(硬锁)",
         'us_only = bool(CFG.get(' not in src
         and 'us_only_strict = bool(CFG.get(' not in src)
    case("硬锁的两个默认值都是 True",
         "if us_only is None:\n        us_only = True" in src
         and "if us_only_strict is None:\n        us_only_strict = True" in src)
    # 认不出的必须淘汰(靠 strict)。
    # ★ 用例不能用 "Atlantis" —— 美国真有 Atlantis, FL, 判 True 是对的。
    #   要一个【两张表都没有、美国城市表也查不到】的串才会返回 None。
    case("认不出的返回「认不出」(由 strict 兜)",
         m.is_us_location("Qqzzxwv") is None, "乱串 -> None, strict 一开就淘汰")

# 严格模式: 认不出的一律淘汰 —— 第二层保险
c = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
case("us_only 开着", c.get("us_only") is True)
case("us_only_strict 开着(认不出一律淘汰)", c.get("us_only_strict") is True,
     f"us_only_strict={c.get('us_only_strict')!r}")

print()
print("=" * 74)
print("★★★ 只采美国境内: 德国号进不来了, 美国人不受影响 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
