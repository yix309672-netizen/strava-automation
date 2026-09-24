# -*- coding: utf-8 -*-
"""验证: 任务跑过 00:00 之后, 链接要写进【新一天】的文件。

用户原话:「链接-20260920.txt 实时更新每天这里的链接。」

原来的 bug: _open_task_file 第一句是
    if ctx.get("path"): return ctx["path"]
把【任务开始那天】的文件路径缓存死了。任务一旦跑过 00:00:
    · 今天该有的新文件一直是空的
    · 界面上的"今日 N 条"读的是今天的新文件 -> 一直显示 0
看着就像"采了没记上"。

这里把 _daily_path 换成一个可控的"假时钟", 模拟跨零点。
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


def body(p):
    if not p.is_file():
        return []
    return [x.strip() for x in p.read_text(encoding="utf-8",
                                           errors="replace").splitlines()
            if x.strip() and not x.startswith("#")]


def raw(p):
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


ok_all = True
A1 = "https://www.strava.com/athletes/100000001"
A2 = "https://www.strava.com/athletes/100000002"
A3 = "https://www.strava.com/athletes/100000003"

for tag, name in (("ADS", "strava_ads.py"), ("BIT", "strava_bit.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_mid_"))
    m = load_engine(tag, name, tmp)
    d1 = tmp / "链接-20260920.txt"
    d2 = tmp / "链接-20260921.txt"

    # 可控的"假时钟": 先指向 20 号, 后面切成 21 号
    clock = {"day": d1}
    m._daily_path = lambda when=None: clock["day"]

    task = m.new_task_ctx(target="t", mode="cli", worker="w")
    sub = m.new_account_ctx(task, "1")
    cases = []

    # ① 20 号: 写两条
    m.append_task_url(sub, A1)
    m.append_task_url(sub, A2)
    ok1 = (body(d1) == [A1, A2] and not d2.exists())
    cases.append(("20 号写两条 -> 都进 20 号文件",
                  ok1, f"20号={len(body(d1))}条 21号存在={d2.exists()}"))

    # ② 同一天再写一条: 还是同一个文件, 且【不能多出一个日期头】
    m.append_task_url(sub, A3)
    heads = raw(d1).count("# 采集日期")
    ok2 = (body(d1) == [A1, A2, A3] and heads == 1)
    cases.append(("同一天继续追加(只有一个日期头)",
                  ok2, f"20号={len(body(d1))}条 日期头={heads}个"))

    # ③ ★ 跨零点: 之后必须写进 21 号
    clock["day"] = d2
    B1 = "https://www.strava.com/athletes/200000001"
    m.append_task_url(sub, B1)
    ok3 = (B1 in body(d2) and B1 not in body(d1))
    cases.append(("跨零点后 写进新一天的文件",
                  ok3, f"20号={len(body(d1))}条 21号={len(body(d2))}条"))

    # ④ 20 号那条不能被改坏(旧文件保持原样)
    ok4 = (body(d1) == [A1, A2, A3])
    cases.append(("旧文件保持原样", ok4, f"20号={body(d1)}"[:60]))

    # ⑤ ctx["path"] 要跟着换(界面/日志报的路径才对)
    ok5 = (str(sub.get("path") or "").endswith("链接-20260921.txt"))
    cases.append(("ctx['path'] 跟着换", ok5, f"path={Path(str(sub.get('path'))).name}"))

    print("=" * 72)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:30s} {detail}")

    shutil.rmtree(tmp, ignore_errors=True)

print()
print("★★★ 跨零点会自己换到新一天的文件 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
