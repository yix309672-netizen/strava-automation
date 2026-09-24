# -*- coding: utf-8 -*-
"""查: 同事那台机器的"机器号"是怎么定的 —— 中心库里那台叫 PC01 的为什么不再出现。

服务器数据: PC01 只有 4 条, 最后一次 09-18 03:14(2.2 天前), 之后再没提交。
其他机器都在正常提交。

重点看 auto_worker_id: 它决定"这台机器在中心叫什么", 而机器号变了
= 在中心眼里就是【另一台机器】, 去重记录对不上。
"""
import pathlib
import re


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

print("=" * 80)
print("1) auto_worker_id 的实现(两个引擎)")
print("=" * 80)
for f in ("主脚本/strava_ads.py", "主脚本/strava_bit.py"):
    s = pathlib.Path(f).read_text(encoding="utf-8")
    m = re.search(r"^def auto_worker_id\(.*?(?=^def )", s, re.M | re.S)
    if not m:
        print("  ★ %s 里没找到" % f)
        continue
    print()
    print("  --- %s ---" % pathlib.Path(f).name)
    for l in m.group(0).splitlines():
        if l.strip() and not l.strip().startswith("#"):
            print("     " + l.rstrip()[:96])

print()
print("=" * 80)
print("2) 机器号是怎么拼出来的(去掉注释看纯代码)")
print("=" * 80)
s = pathlib.Path("主脚本/strava_ads.py").read_text(encoding="utf-8")
m = re.search(r"^def auto_worker_id\(.*?(?=^def )", s, re.M | re.S)
if m:
    code = [l for l in m.group(0).splitlines()
            if l.strip() and not l.strip().startswith("#")]
    for l in code:
        print("  " + l.rstrip()[:96])

print()
print("=" * 80)
print("3) 界面传下去的 hint 是什么(collect_one / run_one_seq)")
print("=" * 80)
for f in ("主脚本/strava_ads.py",):
    t = pathlib.Path(f).read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(t):
        if "make_claim_client(" in l and "def " not in l:
            print("  L%-5d %s" % (i + 1, l.strip()[:96]))
        if "_hint" in l and "=" in l and "PC" in l:
            print("  L%-5d %s" % (i + 1, l.strip()[:96]))

print()
print("=" * 80)
print("4) 中心库里各机器号的构成")
print("=" * 80)
print("  已知: DESKTOP-5G6SMV5_bit / DESKTOP-5G6SMV5_ads / DESKTOP-D3H1JIF_ads / PC01")
print("  · DESKTOP-xxx_ads|bit  来自 auto_worker_id(主机名 + 后缀)")
print("  · PC01                 来自界面传的 hint(_hint = PC{seq:02d})")
print()
print("  ★ 也就是说: 同一个物理机器, 走不同入口会得到【不同的机器号】:")
print("      界面『开始任务』 -> auto_worker_id  -> DESKTOP-XXX_ads")
print("      界面『只采集』   -> hint=PC{seq}    -> PC01 / PC02 ...")
print("    这在中心看来是两台机器 —— 去重记录、租约都是分开的。")
