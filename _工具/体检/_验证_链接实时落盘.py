# -*- coding: utf-8 -*-
"""验证「链接实时更新至文档」。

两份文档都必须【写一条就立刻有一条】:
  ① 当天成果文件  链接-YYYYMMDD.txt
  ② 累计总表      collected_users.txt
以前 ② 只在任务结束(finalize_task)时才合并一次 —— 任务没结束或被强杀时
去看总表, 一条都没多, 看着就像"没在采"。

另外必须验:
  ③ 一条链接只写一次(两份都不重复)
  ④ 同一个链接再来一次要被去重挡掉
  ⑤ p 和总表是同一个文件时(创建失败的兜底路径)不能写两遍
"""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")


def load_engine(tag, name, tmp):
    src = ROOT / "主脚本" / name
    shutil.copy2(src, tmp / name)
    (tmp / "config.json").write_text("{}", encoding="utf-8")
    for dep in ("geo_cities.py", "claim_client.py"):
        if (ROOT / dep).is_file():
            shutil.copy2(ROOT / dep, tmp / dep)
    sys.path.insert(0, str(tmp))
    spec = importlib.util.spec_from_file_location("_e_" + tag, tmp / name)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_e_" + tag] = m
    spec.loader.exec_module(m)
    return m


def lines(p):
    if not p.is_file():
        return []
    return [x.strip() for x in p.read_text(encoding="utf-8",
                                           errors="replace").splitlines()
            if x.strip() and not x.startswith("#")]


ok_all = True
U1 = "https://www.strava.com/athletes/111111111"
U2 = "https://www.strava.com/athletes/222222222"

for tag, name in (("ADS", "strava_ads.py"), ("BIT", "strava_bit.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_rt_"))
    m = load_engine(tag, name, tmp)
    cases = []

    daily = m._daily_path()
    total = Path(m.COLLECT_OUT)
    task = m.new_task_ctx(target="t", mode="cli", worker="w")
    sub = m.new_account_ctx(task, "1")

    # ① 写一条 -> 两份文档都立刻要有
    r1 = m.append_task_url(sub, U1)
    d_after1, t_after1 = lines(daily), lines(total)
    cases.append(("写一条后 当天文件 立刻有",
                  r1 is True and U1 in d_after1, f"文件行数={len(d_after1)}"))
    cases.append(("写一条后 累计总表 立刻有",
                  U1 in t_after1, f"总表行数={len(t_after1)}"))

    # ② 再写一条 -> 两份都各自 +1
    r2 = m.append_task_url(sub, U2)
    d_after2, t_after2 = lines(daily), lines(total)
    cases.append(("第二条后 两份都 +1",
                  r2 is True and len(d_after2) == 2 and len(t_after2) == 2,
                  f"当天={len(d_after2)} 总表={len(t_after2)}"))

    # ③ 都不能有重复
    cases.append(("两份文档都没有重复行",
                  len(set(d_after2)) == len(d_after2)
                  and len(set(t_after2)) == len(t_after2),
                  f"当天唯={len(set(d_after2))}/{len(d_after2)}"
                  f" 总表唯={len(set(t_after2))}/{len(t_after2)}"))

    # ④ 同一条再来 -> 去重挡住, 两份都不长
    r3 = m.append_task_url(sub, U1)
    d_after3, t_after3 = lines(daily), lines(total)
    cases.append(("重复链接被去重挡住",
                  r3 is False and len(d_after3) == 2 and len(t_after3) == 2,
                  f"返回={r3} 当天={len(d_after3)} 总表={len(t_after3)}"))

    # ⑤ 兜底路径: 当天文件"创建失败"时 p 就是总表 —— 绝不能写两遍
    tmp2 = Path(tempfile.mkdtemp(prefix="_rt2_"))
    m2 = load_engine(tag + "2", name, tmp2)
    m2._daily_path = lambda when=None: (_ for _ in ()).throw(
        RuntimeError("模拟: 当天文件创建失败"))
    total2 = Path(m2.COLLECT_OUT)
    t2 = m2.new_task_ctx(target="t", mode="cli", worker="w")
    s2 = m2.new_account_ctx(t2, "1")
    U3 = "https://www.strava.com/athletes/333333333"
    m2.append_task_url(s2, U3)
    got = [x for x in lines(total2) if x == U3]
    cases.append(("兜底路径不写两遍", len(got) == 1, f"该链接出现 {len(got)} 次"))

    print("=" * 72)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:26s} {detail}")

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)

print()
print("★★★ 两份文档都是实时的, 且不重复、不双写 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
