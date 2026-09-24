# -*- coding: utf-8 -*-
"""验证界面上的采集计数: 「本次 N/M · 今日 T」, 以及跨零点自动翻页。

真要起一次 Tk(和 _验证_同事拿到能用.py 一样的做法), 然后:
  ① 写一个假的当天成果文件 -> 看计数对不对(# 注释和空行不算)
  ② 设好本次目标和起点 -> 看显示是不是 "本次 N/M · 今日 T"
  ③ 把 _task_day 改成另一天 -> 模拟过了十二点, 看"本次"有没有归零重算
"""
import importlib.util
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
ok_all = True

for tag, gui in (("ADS", ROOT / "界面" / "ADS自动化.py"),
                 ("BIT", ROOT / "界面" / "比特派自动化.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_cnt_"))
    daily = tmp / "链接-20260920.txt"
    # 3 条真链接 + 1 行注释 + 1 空行
    daily.write_text("# 采集日期 2026-09-20\n"
                     "https://www.strava.com/athletes/1\n"
                     "https://www.strava.com/athletes/2\n"
                     "\n"
                     "https://www.strava.com/athletes/3\n",
                     encoding="utf-8")

    # ★ 界面模块里 SA 只在 __main__ 里赋值, 直接 import 是没有的 ——
    #   所以这里自己把引擎加载进来再挂上去(和界面真正跑起来时一样的用法)。
    #   引擎要拷进沙箱再加载, 否则会往项目的 主脚本\logs\ 里写日志。
    eng_src = ROOT / "主脚本" / ("strava_ads.py" if tag == "ADS" else "strava_bit.py")
    import shutil as _sh
    _sh.copy2(eng_src, tmp / eng_src.name)
    (tmp / "config.json").write_text("{}", encoding="utf-8")
    for dep in ("geo_cities.py", "claim_client.py"):
        if (ROOT / dep).is_file():
            _sh.copy2(ROOT / dep, tmp / dep)
    sys.path.insert(0, str(tmp))
    espec = importlib.util.spec_from_file_location("_eng_" + tag, tmp / eng_src.name)
    eng = importlib.util.module_from_spec(espec)
    sys.modules["_eng_" + tag] = eng
    espec.loader.exec_module(eng)

    spec = importlib.util.spec_from_file_location("_g_" + tag, gui)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_g_" + tag] = m
    spec.loader.exec_module(m)

    # 把引擎的"当天文件"指到我们的假文件
    eng._daily_path = lambda when=None: daily
    m.SA = eng

    app = m.App()
    app.withdraw()          # 别弹窗占屏幕

    results = []

    # ① 计数
    n = app._count_today()
    ok1 = (n == 3)
    results.append(("数链接(# 和空行不算)", n, 3, ok1))

    # ② 本次 + 今日
    app._task_goal = 3000
    app._task_base = 1
    app._task_day = "20260920"
    app._tick_today()
    txt = app.lbl_today.cget("text")
    ok2 = (txt == "本次 2/3000 · 今日 3")
    results.append(("本次进度显示", txt, "本次 2/3000 · 今日 3", ok2))

    # ③ 过了十二点: 换一天(新文件从 0 开始)
    daily2 = tmp / "链接-20260921.txt"
    daily2.write_text("https://www.strava.com/athletes/9\n", encoding="utf-8")
    eng._daily_path = lambda when=None: daily2
    # ★ _task_day 必须是【和今天真的不一样】的一天, 否则条件不成立, 不会翻页。
    #   第一版这里写了今天(20260920), 于是把正确的实现验成了失败 —— 是测试错了。
    app._task_day = "20260101"
    app._task_base = 5                  # 昨天留下的旧起点, 翻页后必须作废
    app._tick_today()
    txt2 = app.lbl_today.cget("text")
    # 新的一天: 今日=1, 本次起点归 0 -> 本次 1/3000
    ok3 = (txt2 == "本次 1/3000 · 今日 1")
    results.append(("跨零点翻页", txt2, "本次 1/3000 · 今日 1", ok3))

    # ④ 没有任务时只显示今日
    app._task_goal = 0
    eng._daily_path = lambda when=None: daily
    app._tick_today()
    txt3 = app.lbl_today.cget("text")
    ok4 = (txt3 == "今日 3 条")
    results.append(("空闲时显示", txt3, "今日 3 条", ok4))

    # ⑤ ★ 实时性: 追加一条链接后, 【下一次 tick 立刻】就要反映出来
    #    (用户要求「链接改成实时更新」; 以前 5 秒一次, 看着像不动)
    with open(daily, "a", encoding="utf-8") as fh:
        fh.write("https://www.strava.com/athletes/4\n")
    app._tick_today()
    txt4 = app.lbl_today.cget("text")
    ok5 = (txt4 == "今日 4 条")
    results.append(("新链接立刻反映", txt4, "今日 4 条", ok5))

    # ⑥ 文件没变时不能乱跳(走的是"指纹没变就用上次的数"那条路)
    app._tick_today()
    txt5 = app.lbl_today.cget("text")
    ok6 = (txt5 == "今日 4 条")
    results.append(("没变化时保持稳定", txt5, "今日 4 条", ok6))

    # ⑦ 刷新间隔必须是 1000ms(1 秒), 不能退回 5000
    src = Path(gui).read_text(encoding="utf-8", errors="replace")
    ok7 = ("self.after(1000, self._tick_today)" in src
           and "self.after(5000, self._tick_today)" not in src)
    results.append(("刷新间隔 = 1 秒", "1000" if ok7 else "非1000", "1000", ok7))

    app.destroy()
    print(f"===== {tag} =====")
    for name, got, want, ok in results:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name:20s} 得到 {got!r:28s} 期望 {want!r}")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("★★★ 采集计数显示正确, 跨零点会自己翻页 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
