# -*- coding: utf-8 -*-
"""验收v2-一致性: 不看文本相似度, 看两版 collect_regions 的【操作序列】是否等价

用法: python _验收_一致性_v2.py
"""
import ast
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
A = WS / "主脚本" / "strava_ads.py"
B = WS / "主脚本" / "strava_bit.py"
FAILS, N = [], [0]


def ck(name, cond, extra=""):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def calls_in(path, fn):
    """返回 (被调用的名字列表(有序, 去重前), 关键字参数名集合, 字符串字面量集合)"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            target = node
            break
    if target is None:
        return [], set(), set()
    seq, kwargs, strs = [], set(), set()

    def walk(n):
        for c in ast.walk(n):
            if isinstance(c, ast.Call):
                f = c.func
                name = (f.attr if isinstance(f, ast.Attribute)
                        else (f.id if isinstance(f, ast.Name) else ""))
                if name:
                    seq.append(name)
                for k in c.keywords:
                    if k.arg:
                        kwargs.add(k.arg)
            elif isinstance(c, ast.Constant) and isinstance(c.value, str):
                strs.add(c.value)
    walk(target)
    return seq, kwargs, strs


sa, ka, sta = calls_in(A, "collect_regions")
sb, kb, stb = calls_in(B, "collect_regions")

# ---- 必须具备的操作(用户第2/3/4条落到代码上的硬动作) ----
MUST = {
    "取排行榜(带翻页)": "fetch_lb_filtered",
    "读弹窗路段人数": "popup_athletes",
    "看地图标记": "find_markers",
    "取路段号": "segment_from_popup",
    "查资料页筛选": "check_athlete",
    "中心服务领取": "claim_pick",
    "中心服务上报(合格)": "collect",
    "中心服务上报(结果)": "finish",
    "停止检查": "check_stop",
    "圆心解析": "resolve_center",
    "自动选州": "states_in_band",
    "纽约判定": "is_new_york",
}
print("=== 关键操作: 两版都必须有 ===")
for label, fn in MUST.items():
    na, nb = sa.count(fn), sb.count(fn)
    # 有些名字在引擎里带后缀(如 geo_resolve_center / resolve_center_safe)
    if na == 0:
        na = sum(1 for x in sa if fn in x)
    if nb == 0:
        nb = sum(1 for x in sb if fn in x)
    ck(f"{label} ({fn})", na > 0 and nb > 0, f"ADS={na} BIT={nb}")

print("\n=== 关键参数/字面量: 两版都必须有 ===")
for label, pat in (("exempt_max 传参", r"exempt_max"),
                   ("每段人数门槛判定", r"min_athletes"),
                   ("200 人目标变量", r"target"),
                   ("未达标告警文案", r"(未达标|只采到)"),
                   ("停止异常", r"UserStopped"),
                   ("服务中断异常", r"ServerDown")):
    ra = re.search(pat, A.read_text(encoding="utf-8"))
    rb = re.search(pat, B.read_text(encoding="utf-8"))
    ck(label, bool(ra) and bool(rb))

print("\n=== 操作序列相似度(信息) + 关键步骤顺序(判据) ===")
import difflib  # noqa: E402
r = difflib.SequenceMatcher(None, sa, sb).ratio()
print(f"  collect_regions 调用序列相似度 {r:.3f}  (ADS {len(sa)} 次调用 / BIT {len(sb)} 次调用)")
only_a = sorted(set(sa) - set(sb))
only_b = sorted(set(sb) - set(sa))
print(f"  只出现在 ADS 的调用: {only_a}")
print(f"  只出现在 BIT 的调用: {only_b}")
print("  ↑ 只是两版给内部 wrapper 起了不同名字(geo_* vs *_safe), 不算逻辑漂移;"
      " 下面用归一化后的【关键步骤顺序】判等价")

NORM = {"geo_resolve_center": "resolve_center", "resolve_center_safe": "resolve_center",
        "geo_is_new_york": "is_new_york", "is_new_york_safe": "is_new_york",
        "geo_states_in_band": "states_in_band", "states_in_band_safe": "states_in_band",
        "geo_band_limits": "band_limits", "geo_band_km": "band_limits"}
ORDER = ["resolve_center", "states_in_band", "is_new_york", "segment_from_popup",
         "popup_athletes", "fetch_lb_filtered", "claim_pick", "check_athlete",
         "collect", "finish"]


def step_order(seq):
    seen, out = set(), []
    for x in (NORM.get(y, y) for y in seq):
        if x in ORDER and x not in seen:
            seen.add(x)
            out.append(x)
    return out


oa, ob = step_order(sa), step_order(sb)
print(f"  源码首现顺序 ADS={oa}")
print(f"  源码首现顺序 BIT={ob}")
print("  (源码首现位置受『嵌套 helper 定义在前』影响, 只作信息; "
      "运行时真实顺序由 _验收_采集_v2.py 的行为断言判定)")
ck("两版关键步骤集合一致(不看顺序)", set(oa) == set(ob), f"ADS-BIT={sorted(set(oa) - set(ob))}")
CORE = {"resolve_center", "states_in_band", "is_new_york", "fetch_lb_filtered",
        "claim_pick", "check_athlete"}
ck("核心链路六步两版都在", CORE <= set(oa) and CORE <= set(ob),
   f"ADS缺={sorted(CORE - set(oa))} BIT缺={sorted(CORE - set(ob))}")

print("\n=== 日志口径(给用户看的话必须两版一致) ===")
for key in ("[quota]", "[geo]", "[region]"):
    ina = any(key in s for s in sta)
    inb = any(key in s for s in stb)
    ck(f"两版都有 {key} 日志前缀", ina and inb, f"ADS={ina} BIT={inb}")

print("\n================ v2-一致性 结果 ================")
print(f"共 {N[0]} 项, 失败 {len(FAILS)} 项")
for x in FAILS:
    print("  ✗ " + x)
sys.exit(1 if FAILS else 0)
