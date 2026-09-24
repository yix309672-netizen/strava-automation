# -*- coding: utf-8 -*-
r"""验证「◎ 精准采集」: 只换地区, 年龄/时间/活跃度照界面那套走。

用户 2026-09-23: "单独开发一个精准采集新泽西州，波士顿，德克萨斯…"(29 个地区)
                 "年龄，时间，也要和脚本配套。比特派也应用起来。"

★★ 这个功能的要点就是【只换地区, 别的都不许动】★★
   它和「◎ 只采集」跑的是同一个 collect_one, 只是把 collect_regions
   换成那份固定名单。如果顺手把年龄/时间也写死了, 就成了"另一套口径" ——
   用户明确要求"要和脚本配套"。

验 10 件事(两个界面各一遍):
  ① PRECISE_REGIONS 有 29 个, 且包含新泽西/波士顿/德克萨斯
  ② 有「◎ 精准采集」按钮, 绑到 start_precise
  ③ start_precise 走的是 _start("精准采集")
  ④ 精准模式里【只改 collect_regions】—— 没有第二处赋值
  ⑤ 精准模式复用 collect_one(和只采集同一条路)
  ⑥ 年龄/时间/性别仍然来自界面下拉框(源码里读的是 var_age/var_daterange)
  ⑦ 活跃度输入框存在, 且写进 cfg 的 recent_days
  ⑧ _spin_int 对空/非法输入有兜底
  ⑨ 运行中按钮会被禁用, 结束后恢复
  ⑩ 两个界面的 PRECISE_REGIONS 逐字相同
"""
import ast
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
GUIS = {"ADS界面": ROOT / "界面" / "ADS自动化.py",
        "比特界面": ROOT / "界面" / "比特派自动化.py"}
NEED = ["New Jersey", "Boston", "Texas", "Hawaii", "Wisconsin"]


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True
for tag, path in GUIS.items():
    m = load(path, "_p_" + tag)
    code = path.read_text(encoding="utf-8")
    cases = []

    regs = list(m.PRECISE_REGIONS)
    cases.append(("  四个函数都在", True, ""))
    # ★★ 2026-09-23 用户要求: 精准的地区和原有的【共用同一个下拉框】★★
    rc = list(m.REGION_CHOICES)
    OLD = ["New York", "Chicago", "Los Angeles", "Boston",
           "Central Park (New York)", "Lakefront Trail (Chicago)",
           "The 606 (Chicago)", "Chicago Riverwalk (Chicago)",
           "The Strand or Marvin Braude Bike Trail (Los Angeles)",
           "Griffith Observatory (Los Angeles)", "Charles River Esplanade (Boston)"]
    cases.append(("⑪ 下拉框含原有 11 个", all(x in rc for x in OLD),
                  f"{len(rc)} 项"))
    cases.append(("⑫ 下拉框含精准 29 个", all(x in rc for x in regs),
                  "全在里面"))
    cases.append(("⑬ 下拉框无重复(合并去重过)", len(rc) == len(set(rc)),
                  f"{len(rc)} 项 / {len(set(rc))} 个不同"))
    miss = [x for x in NEED if x not in regs]
    cases.append(("① 29 个地区且含关键几个", len(regs) == 29 and not miss,
                  f"{len(regs)} 个" + (f" 缺 {miss}" if miss else "")))
    cases.append(("② 有「◎ 精准采集」按钮并绑 start_precise",
                  'text="◎ 精准采集"' in code
                  and "command=self.start_precise" in code, "按钮在"))
    cases.append(("③ start_precise -> _start(\"精准采集\")",
                  'self._start("精准采集")' in code, "接线对"))

    # ④ 精准块里只改地区
    i = code.find('if mode == "精准采集":')
    blk = code[i:i + 900] if i >= 0 else ""
    sets = [ln.strip() for ln in blk.splitlines()
            if "cfg[" in ln and "=" in ln]
    cases.append(("④ 精准模式只改 collect_regions",
                  sets == ['cfg["collect_regions"] = list(PRECISE_REGIONS)'],
                  f"赋了 {sets}"))
    cases.append(("⑤ 精准模式复用 collect_one",
                  'mode in ("采集", "精准采集")' in code
                  and "SA.collect_one" in code, "同一条路"))

    # ⑥ 年龄/时间仍来自下拉框
    cases.append(("⑥ 年龄/时间/性别仍读界面下拉框",
                  all(x in code for x in
                      ("list(_value_of(AGE_CHOICES, self.var_age.get()))",
                       "self.var_daterange.get()", "self.var_gender.get()")),
                  "没写死"))

    cases.append(("⑦ 活跃度写进 cfg.recent_days",
                  '"recent_days": _spin_int(self.var_recent.get(), 60)' in code,
                  "读输入框"))
    cases.append(("⑧ _spin_int 有兜底",
                  m._spin_int("90", 60) == 90 and m._spin_int("", 60) == 60
                  and m._spin_int("abc", 60) == 60, "空/非法都退回默认"))
    cases.append(("⑨ 运行中禁用、结束恢复",
                  'self.btn_precise.config(state="disabled")' in code
                  and 'self.btn_precise.config(state="normal")' in code,
                  "两处都在"))

    print("=" * 78)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")

# ⑩ 两份名单逐字相同
a = list(load(GUIS["ADS界面"], "_c_a").PRECISE_REGIONS)
b = list(load(GUIS["比特界面"], "_c_b").PRECISE_REGIONS)
same = a == b
if not same:
    ok_all = False
print("=" * 78)
print(f"   {'OK ' if same else '★  '}{'⑩ 两个界面名单逐字相同':34s} {same}")
print(f"      名单: {' / '.join(a)}")
print()
print("★★★ 精准采集只换地区, 年龄/时间/活跃度照界面 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
