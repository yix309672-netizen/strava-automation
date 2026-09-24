# -*- coding: utf-8 -*-
"""验证「采集」已经从「开始任务」里摘干净, 只留给「只采集」。

用户 2026-09-22 要求:
    「▶ 开始任务」只做 注册账号 / 修改资料 / 上传轨迹;
    采集功能只限制在「◎ 只采集」按钮。

验 7 件事:
  ① ★ run_one_seq(开始任务走的)里【没有】任何 collect_regions / make_claim_client
  ② ★ 但会员状态和真实姓名/所在地【还在读】—— 表格那三列靠它回填
  ③ ★ collect_one(只采集走的)里【仍然有】采集调用
  ④ ★ pending_todo 不再把"采集"算进待办(否则"只差采集"的号会白开浏览器)
  ⑤ pending_todo 行为测试: 别的都做完了 + 今天还没采 -> 待办必须是空的
  ⑥ 界面: 「◎ 只采集」-> collect_one, 「▶ 开始任务」-> run_one_seq(没接反)
  ⑦ 两个引擎的这几处逐字相同
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
ENGINES = {"ADS": ROOT / "主脚本" / "strava_ads.py",
           "BIT": ROOT / "主脚本" / "strava_bit.py"}


def segs(path):
    code = path.read_text(encoding="utf-8")
    return code, {n.name: (ast.get_source_segment(code, n) or "")
                  for n in ast.walk(ast.parse(code))
                  if isinstance(n, ast.FunctionDef)}


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True
srcs = {}
for tag, path in ENGINES.items():
    code, F = segs(path)
    srcs[tag] = (code, F)
    cases = []
    # ★ 采集块长在 run_one 里; run_one_seq 只是个薄壳, 转手就调 run_one。
    #   (第一版写成查 run_one_seq, 结果三个标记全部 MISS —— 是测试查错了函数。)
    run1, seq1 = F.get("run_one", ""), F.get("run_one_seq", "")
    col1, todo = F.get("collect_one", ""), F.get("pending_todo", "")
    cases.append(("  四个函数都在", all([run1, col1, todo, seq1]),
                  f"run_one={len(run1)}B run_one_seq={len(seq1)}B "
                  f"collect_one={len(col1)}B pending_todo={len(todo)}B"))
    cases.append(("  开始任务确实走 run_one", "run_one(" in seq1,
                  "run_one_seq -> run_one" if "run_one(" in seq1 else "★ 没接上"))

    # ① 开始任务不采集
    leak = [s for s in ("collect_regions(", "make_claim_client(", 'append("采集")')
            if s in run1]
    cases.append(("① 开始任务里没有任何采集调用", not leak, f"残留={leak or '无'}"))

    # ② 会员/姓名/所在地还在读
    keep = [s for s in ("is_premium(", 'result["prem"]', "read_settings_info(")
            if s not in run1]
    cases.append(("② 会员状态 + 真实姓名/所在地仍在读", not keep, f"缺失={keep or '无'}"))

    # ③ 只采集仍然采集
    need = [s for s in ("collect_regions(", "make_claim_client(") if s not in col1]
    cases.append(("③ 只采集里采集调用还在", not need, f"缺失={need or '无'}"))

    # ④ 待办里没有采集
    cases.append(("④ pending_todo 不再塞『采集』", 'append("采集")' not in todo,
                  "已经不塞了" if 'append("采集")' not in todo else "★ 还在塞"))

    # ⑤ 行为测试
    m = load(path, "_c_" + tag)
    _st = {"name": "N", "location": "L", "avatar": "a.jpg", "privacy": True,
           "units": "feet", "uploaded": ["x.gpx"],
           "collected": "2000-01-01"}      # 很久没采 -> 老逻辑一定会塞"采集"
    m.load_state = lambda: {"_9": _st}
    got = m.pending_todo("_9", name="N", location="L", avatar="a.jpg",
                         gpx_files=["x.gpx"])
    cases.append(("⑤ 全做完+今天没采 -> 待办为空", got == [],
                  f"待办={got}"))
    got2 = m.pending_todo("_9", name="别的人", location="L", avatar="a.jpg",
                          gpx_files=["x.gpx"])
    cases.append(("⑤ 换个名字就还有『资料』(没坏)",
                  got2 == ["资料"], f"待办={got2}"))

    print("=" * 74)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:30s} {detail}")

# ⑥ 界面接线
gui_cases = []
for tag, g in (("ADS", ROOT / "界面" / "ADS自动化.py"),
               ("BIT", ROOT / "界面" / "比特派自动化.py")):
    t = g.read_text(encoding="utf-8")
    # ★ 2026-09-23: 多了「◎ 精准采集」之后, 这个分支写成
    #   `mode in ("采集", "精准采集")` —— 测试别再死盯一种写法,
    #   只要「采集这条线确实接到 collect_one」就算过。
    gui_cases.append((f"⑥ {tag}: 只采集 -> collect_one",
                      ('mode == "采集"' in t
                       or 'mode in ("采集", "精准采集")' in t)
                      and "SA.collect_one" in t, ""))
    gui_cases.append((f"⑥ {tag}: 精准采集也走 collect_one",
                      'mode in ("采集", "精准采集")' in t
                      and "PRECISE_REGIONS" in t, ""))
    gui_cases.append((f"⑥ {tag}: 开始任务 -> run_one_seq",
                      "SA.run_one_seq" in t, ""))
print("=" * 74)
for name_, ok, _ in gui_cases:
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name_:30s}")

# ⑦ pending_todo 两引擎必须逐字相同
#   ★ run_one / collect_one 本来就不一样(AdsPower 和比特派的接口/键名不同),
#     拿"逐字相同"去比它们只会误报; 它们的不变量已经由 ①②③ 卡住了。
print("=" * 74)
a = segs(ENGINES["ADS"])[1].get("pending_todo")
b = segs(ENGINES["BIT"])[1].get("pending_todo")
same = a == b
if not same:
    ok_all = False
print(f"   {'OK ' if same else '★  '}⑦ pending_todo 两引擎逐字相同 = {same}")

print()
print("★★★ 开始任务只管注册/资料/轨迹, 采集只归「只采集」★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
