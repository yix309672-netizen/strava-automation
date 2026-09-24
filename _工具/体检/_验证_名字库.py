# -*- coding: utf-8 -*-
"""验证名字库接得上、且编号不撞名字。

用户给了 1000 个名字要求放进脚本。原来只有 50 个(编号 1 和 51 会撞同一个)。
这里验:
  ① 名字库能读到, 数量对
  ② name_for_seq(1..N) 取出来的名字【互不相同】(N 取到 500, 够用)
  ③ 编号超出去也不报错(取模绕回来)
  ④ english_names(n) 还兼容老调用方(返回前 n 个)
  ⑤ 名字库丢了要能退回内置的 50 个, 而不是返回空
"""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")


def load(tag, fname, tmp, drop_bank=False):
    for n in ("strava_" + ("ads" if "ads" in fname else "bit") + ".py",
              "name_bank.py", "geo_cities.py", "claim_client.py"):
        src = ROOT / "主脚本" / n
        if src.is_file() and not (drop_bank and n == "name_bank.py"):
            shutil.copy2(src, tmp / n)
    (tmp / "config.json").write_text("{}", encoding="utf-8")
    sys.path.insert(0, str(tmp))
    spec = importlib.util.spec_from_file_location("_e_" + tag, tmp / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_e_" + tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True
for tag, fname in (("ADS", "strava_ads.py"), ("BIT", "strava_bit.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_nm_"))
    m = load(tag, fname, tmp)
    cases = []

    # ① 名字库
    n = len(m.NAMES)
    cases.append(("读到名字库", n >= 900, f"{n} 个"))

    # ② 前 500 个编号互不相同
    got = [m.name_for_seq(i) for i in range(1, 501)]
    uniq = len(set(got))
    cases.append(("编号 1..500 名字不重复", uniq == 500, f"唯 {uniq}/500"))

    # ③ 超范围不报错
    try:
        a = m.name_for_seq(n + 1)
        b = m.name_for_seq(99999)
        ok3 = bool(a) and bool(b)
    except Exception as e:
        ok3 = False
        a = f"抛了 {type(e).__name__}"
    cases.append(("编号超出去不报错", ok3, f"第{n+1}个={a!r}"))

    # ④ english_names 兼容
    e50 = m.english_names(50)
    eall = m.english_names()
    cases.append(("english_names(50) 兼容", len(e50) == 50, f"{len(e50)} 个"))
    cases.append(("english_names() 返回全部", len(eall) >= 900, f"{len(eall)} 个"))

    # ⑤ 掉名字库 -> 退回内置 50 个, 不能是空
    #   ★ 光清 sys.modules 不够: 第一个临时目录也在 sys.path 里, 而它【有】
    #     name_bank.py, import 顺着路径照样能找到。必须把之前加的临时目录
    #     从 sys.path 里摘掉, 才真的是"丢失"场景。
    sys.modules.pop("name_bank", None)
    _td = tempfile.gettempdir()
    sys.path[:] = [p for p in sys.path if not str(p).startswith(_td)]
    tmp2 = Path(tempfile.mkdtemp(prefix="_nm2_"))
    m2 = load(tag + "b", fname, tmp2, drop_bank=True)
    ok5 = len(m2.NAMES) == 50 and bool(m2.name_for_seq(1))
    cases.append(("名字库丢失时退回 50 个兜底", ok5,
                  f"兜底 {len(m2.NAMES)} 个, seq1={m2.name_for_seq(1)!r}"))

    print("=" * 74)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:26s} {detail}")
    print(f"   样例: " + " | ".join(m.name_for_seq(i) for i in (1, 2, 3, 51, 999)))

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)

print()
print("★★★ 名字库接好了, 编号不再撞名字 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
