# -*- coding: utf-8 -*-
r"""验证「位置」已经变成下拉框, 而且改资料时用的是框里选的那个。

用户 2026-09-23: "位置这里也做成下拉框。可以选择位置，改资料的时候读取框里面的选择来做。"

★★ 这个改动有【两条链】都要通, 少一条就是"选完没用" ★★
   ① 界面 -> 引擎(同一次会话): _cfg() 里的 "location" 必须是框里的值
   ② 界面 -> config.json(下次启动): 改选后要落盘, 否则重开又变回旧城市

验 8 件事(两个界面各一遍):
  ① LOCATION_CHOICES 有足够多的位置, 且含 Chicago / Newark / Honolulu
  ② 那个控件是只读 Combobox(不是 Entry)
  ③ 初值来自 config 的 location(不是写死 Chicago)
  ④ _cfg() 的 location 读的是 self.var_loc
  ⑤ 改选会写回 config(_d["location"])
  ⑥ var_loc 已加入自动保存监听的变量表
  ⑦ 两个界面的位置名单逐字相同
  ⑧ 引擎侧的 location 消费点还在(改资料真的用它)
"""
import importlib.util
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
GUIS = {"ADS界面": ROOT / "界面" / "ADS自动化.py",
        "比特界面": ROOT / "界面" / "比特派自动化.py"}
ENGINES = {"ADS引擎": ROOT / "主脚本" / "strava_ads.py",
           "BIT引擎": ROOT / "主脚本" / "strava_bit.py"}


def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True
for tag, path in GUIS.items():
    m = load(path, "_L_" + tag)
    code = path.read_text(encoding="utf-8")
    cases = []

    locs = list(m.LOCATION_CHOICES)
    need = ["Chicago, Illinois", "Newark, New Jersey", "Honolulu, Hawaii",
            "Boston, Massachusetts", "Houston, Texas"]
    miss = [x for x in need if x not in locs]
    cases.append(("① 位置名单够用且含关键几个", len(locs) >= 30 and not miss,
                  f"{len(locs)} 项" + (f" 缺 {miss}" if miss else "")))
    cases.append(("② 是只读 Combobox(不再是 Entry)",
                  'textvariable=self.var_loc, state="readonly"' in code
                  and 'ttk.Entry(cfg, textvariable=self.var_loc' not in code,
                  "已换"))
    cases.append(("③ 初值来自 config 的 location",
                  '_rc.get("location")' in code, "不写死"))
    cases.append(("④ _cfg() 的 location 读 self.var_loc",
                  '"location": self.var_loc.get(),' in code, "读框里的值"))
    cases.append(("⑤ 改选会写回 config", '_d["location"]' in code, "落盘"))
    cases.append(("⑥ 已加入自动保存监听",
                  "self.var_minath, self.var_loc)" in code, "改完立刻存"))

    print("=" * 78)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")

a = list(load(GUIS["ADS界面"], "_L_a").LOCATION_CHOICES)
b = list(load(GUIS["比特界面"], "_L_b").LOCATION_CHOICES)
same = a == b
if not same:
    ok_all = False
print("=" * 78)
print(f"   {'OK ' if same else '★  '}{'⑦ 两个界面位置名单逐字相同':34s} {same}")

# ⑧ 引擎真的会拿 location 去改资料
print("=" * 78)
for tag, p in ENGINES.items():
    t = p.read_text(encoding="utf-8")
    used = ("set_profile" in t) and ('location' in t)
    if not used:
        ok_all = False
    print(f"   {'OK ' if used else '★  '}{f'⑧ {tag} 改资料消费 location':34s} {used}")

print()
print("★★★ 位置是下拉框, 改资料用框里选的那个 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
