# -*- coding: utf-8 -*-
r"""验证「每段人数门槛」下拉框：100~900 也要能真的生效。

用户 2026-09-22: "采集门槛设置每段100 200 … 900 的也要采集。下拉框设置一下。"

★★ 为什么光加选项不够 ★★
   从"界面选好"到"引擎真的用上", 中间有三道闸会把低值顶回去:
     ① 界面   : `if 0 < _ma_now < 200: 改成 200`(还会写回磁盘)
     ② 引擎   : 同款 `if 0 < _v < 200`(启动时纠正 config)
     ③ 地板   : resolve_min_athletes 里 `v < floor` 就抬到 floor
   任何一道没放开, 表现都是"选了没用"。所以这里逐条验。

验 9 件事:
  ① 两个界面的下拉框都含 100~900
  ② ③ 界面/引擎里旧的 `< 200` 写法已经消失
  ④ 引擎里 `arg or CFG or FLOOR` 那种串写法已经消失(它会把 0 吃掉)
  ⑤ resolve_min_athletes(100) 地板 100 -> 100
  ⑥ resolve_min_athletes(100) 地板 0   -> 100
  ⑦ resolve_min_athletes(50)  地板 100 -> 100(无意义的低值仍被抬)
  ⑧ resolve_min_athletes(0)   地板 2000 -> 0(★不设门槛不被抬走)
  ⑨ resolve_min_athletes(2000) 地板 2000 -> 2000(原口径没被破坏)
"""
import ast
import importlib.util
import io
import re
import sys
import tokenize
from pathlib import Path


def code_only(p):
    """去掉注释后的源码。

    ★ 必须这么做: 新注释里为了讲清根因会把【旧写法原样引一遍】
      ("这里不能写 `min_athletes or CFG.get(..) or FLOOR`") ——
      拿正则直接扫全文, 会把自己的注释当成残留代码报出来(踩过)。
    """
    src = p.read_text(encoding="utf-8")
    drop = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                drop.add(tok.start[0])
    except Exception:
        pass
    return "\n".join(l for i, l in enumerate(src.splitlines(), 1) if i not in drop)


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
GUIS = {"ADS界面": ROOT / "界面" / "ADS自动化.py",
        "比特界面": ROOT / "界面" / "比特派自动化.py"}
ENGINES = {"ADS引擎": ROOT / "主脚本" / "strava_ads.py",
           "比特引擎": ROOT / "主脚本" / "strava_bit.py"}
WANT = [100, 200, 300, 400, 500, 600, 700, 800, 900]

ok_all = True
cases = []

# ① 下拉框含 100~900
for tag, p in GUIS.items():
    code = p.read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(code))
                if isinstance(n, ast.Assign) and any(
                    getattr(t, "id", "") == "MIN_ATH_CHOICES" for t in n.targets))
    vals = [v for v in ast.literal_eval(node.value)
            if isinstance(v, (tuple, list)) and len(v) == 2]
    got = {int(x[1]) for x in vals}
    miss = [v for v in WANT if v not in got]
    cases.append((f"① {tag} 下拉框含 100~900", not miss,
                  f"共 {len(got)} 个选项" + (f" 缺 {miss}" if miss else "")))
    cases.append((f"    {tag} 0/1000/2000 仍在", {0, 1000, 2000} <= got,
                  f"含 {sorted({0, 1000, 2000} & got)}"))

# ②③ 旧写法必须消失(★ 剥掉注释再查, 否则会被自己的注释误导)
for tag, p in {**GUIS, **ENGINES}.items():
    code = code_only(p)
    old = "0 < _ma_now < 200" in code or "0 < _v < 200" in code
    cases.append((f"②③ {tag} 旧的 `< 200` 已清掉", not old,
                  "★ 还在" if old else "已放开到 100"))

# ④ 引擎里不能再用 or 串
for tag, p in ENGINES.items():
    code = code_only(p)
    bad = bool(re.search(r"min_athletes(_arg)?\s+or\s+CFG\.get", code))
    cases.append((f"④ {tag} 没有 `or CFG.get` 串写法", not bad,
                  "★ 还在" if bad else "已改成显式判空"))

# ⑤~⑨ 行为
for tag, p in ENGINES.items():
    spec = importlib.util.spec_from_file_location("_q_" + tag, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_q_" + tag] = m
    spec.loader.exec_module(m)

    def rma(v, floor):
        m.CFG = {"min_athletes_floor": floor}
        return m.resolve_min_athletes(v)

    cases.append((f"⑤ {tag} 门槛100 地板100 -> 100", rma(100, 100) == 100,
                  f"得到 {rma(100, 100)}"))
    cases.append((f"⑥ {tag} 门槛100 地板0   -> 100", rma(100, 0) == 100,
                  f"得到 {rma(100, 0)}"))
    cases.append((f"⑦ {tag} 门槛50  地板100 -> 100", rma(50, 100) == 100,
                  f"得到 {rma(50, 100)}(无意义低值仍被抬)"))
    cases.append((f"⑧ {tag} 门槛0   地板2000 -> 0", rma(0, 2000) == 0,
                  f"得到 {rma(0, 2000)}(不设门槛不被抬走)"))
    cases.append((f"⑨ {tag} 门槛2000 地板2000 -> 2000", rma(2000, 2000) == 2000,
                  f"得到 {rma(2000, 2000)}"))

print("=" * 78)
for name_, ok, detail in cases:
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")
print()
print("★★★ 100~900 的门槛现在真的能生效 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
