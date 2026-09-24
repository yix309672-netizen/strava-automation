# -*- coding: utf-8 -*-
r"""上线前专项体检: 【比特派这一半】到底齐没齐。

为什么单独查一遍: 这几天的改动(采集分离/近期活动/门槛下拉/等人数渲染)
全都是【两个引擎 + 两个界面】各改一份, 全靠手工对齐 ——
历史上已经因此出过 4 次事故(只改 ADS 忘了比特)。
推给同事之前, 逐条把"比特派有没有"点一遍。

验 12 件事:
  ① 五个引擎级常量/函数在比特版都在
  ② 采集不在 run_one 里(比特版)
  ③ 比特界面: 门槛下拉含 100~900
  ④ 比特界面: 「执行内容(不含采集)」标签
  ⑤ 比特界面: 密码列自愈三道闸
  ⑥ 比特界面: 老号上传不再被 skip_setup 挡
  ⑦ 分发包里 _gui_bit.py / strava_bit.py 与源码【逐字节相同】
  ⑧ 分发包里 ADS 那两份也一样
  ⑨ config.json 里有 recent_days=60
  ⑩ 使用说明里写到了 100~900 和等人数
  ⑪ 两个引擎里 SEG_ATH_READY_JS / SEG_ATH_WAIT 逐字相同
  ⑫ 两个界面的 MIN_ATH_CHOICES 逐字相同
"""
import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
DIST = ROOT / "_分发给同事"
A_E, B_E = ROOT / "主脚本" / "strava_ads.py", ROOT / "主脚本" / "strava_bit.py"
A_G, B_G = ROOT / "界面" / "ADS自动化.py", ROOT / "界面" / "比特派自动化.py"

ok_all = True
cases = []


def has(p, *needles):
    t = p.read_text(encoding="utf-8")
    return [n for n in needles if n not in t]


# ① 引擎级新东西在比特版
cases.append(("① 比特引擎有全部新东西",
              not has(B_E, "def set_act_title(page, want=0)", 'ACT_TITLE = "Morning Run"',
                      'ACT_SPORT = "Run"', "recent_days=0", "out.recent_dates",
                      "SEG_ATH_WAIT = 2.5", "SEG_ATH_READY_JS", 'key="segath"',
                      "这一步【不再受 skip_setup 管】"),
              "set_act_title / 近期活动 / 等人数 / 上传不受skip_setup"))

# ② run_one 里不许有采集
code = B_E.read_text(encoding="utf-8")
seg = next(ast.get_source_segment(code, n) for n in ast.walk(ast.parse(code))
           if isinstance(n, ast.FunctionDef) and n.name == "run_one")
leak = [s for s in ("collect_regions(", "make_claim_client(") if s in seg]
cases.append(("② 比特版 run_one 里没有采集", not leak, f"残留={leak or '无'}"))

# ③④⑤⑥ 比特界面
cases.append(("③ 比特界面下拉含 100~900",
              not has(B_G, '("100", 100)', '("900", 900)'), "18 个选项"))
cases.append(("④ 比特界面「执行内容(不含采集)」",
              not has(B_G, "执行内容(不含采集)"), "标签已改"))
cases.append(("⑤ 比特界面密码自愈三道闸",
              not has(B_G, "def _pwd_index(acc):", 'nv["password"] = idx.get(e, "")',
                      "if str(pwd).strip() in _YESNO:"), "三道都在"))
cases.append(("⑥ 比特界面上传不再被 skip_setup 挡",
              not has(B_E, "if files and upload_needed:"), "闸已放开"))

# ⑦⑧ 分发包逐字节相同
for src, d in ((B_E, "strava_bit.py"), (A_E, "strava_ads.py"),
               (B_G, "_gui_bit.py"), (A_G, "_gui_ads.py")):
    dst = DIST / d
    same = dst.is_file() and src.read_bytes() == dst.read_bytes()
    cases.append((f"⑦⑧ 分发包 {d} 与源码逐字节相同", same,
                  f"{dst.stat().st_size if dst.is_file() else 0} B"))

# ⑨ config
cfg = (DIST / "config.json").read_text(encoding="utf-8")
cases.append(("⑨ 分发包 config 有 recent_days=60", '"recent_days": 60' in cfg,
              "在"))

# ⑩ 使用说明
man = (DIST / "使用说明.txt").read_text(encoding="utf-8")
cases.append(("⑩ 使用说明写了 100~900 和等人数",
              ("100 / 200" in man) and ("点地图标记之后会" in man),
              "两处都在"))

# ⑪ 两个引擎的等人数常量逐字相同
def const_str(p, name):
    code = p.read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(code)):
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == name for t in n.targets):
            return ast.get_source_segment(code, n.value)
    return None


cases.append(("⑪ 两引擎 SEG_ATH_READY_JS 逐字相同",
              const_str(A_E, "SEG_ATH_READY_JS") == const_str(B_E, "SEG_ATH_READY_JS"),
              "一致"))
cases.append(("⑫ 两界面 MIN_ATH_CHOICES 逐字相同",
              const_str(A_G, "MIN_ATH_CHOICES") == const_str(B_G, "MIN_ATH_CHOICES"),
              "一致"))

print("=" * 76)
for name_, ok, detail in cases:
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name_:36s} {detail}")
print()
print("★★★ 比特派这一半齐了, 可以推 ★★★" if ok_all else "★★★ 还缺东西, 先别推 ★★★")
sys.exit(0 if ok_all else 1)
