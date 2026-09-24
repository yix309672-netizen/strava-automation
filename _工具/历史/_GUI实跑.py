# -*- coding: utf-8 -*-
"""用【真界面链路】跑采集: 完全照抄 界面\\ADS自动化.py 的 __main__ 加载方式,
然后点它自己的按钮「1.连接并加载」→「◎ 只采集」, 等它跑完。

用法: python -X utf8 _GUI实跑.py 3
产物: _GUI实跑.log(流程) + _GUI界面日志.txt(界面日志框原文)

为什么要这样跑: 之前是手搓 cfg 直接调引擎, 绕过了界面这一层。
按界面链路跑能顺带暴露: 引擎加载/os.chdir、_cfg() 传参、表格回填、
运行中按钮禁用/恢复、日志转发、停止按钮……
"""
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent
GUI = WS / "界面" / "ADS自动化.py"
OUT = WS / "_GUI实跑.log"
GUILOG = WS / "_GUI界面日志.txt"
SEQ = sys.argv[1] if len(sys.argv) > 1 else "3"
MAX_WAIT = 7200          # 采集最长等 2 小时


def out(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------- 按界面方式加载界面模块 ----------------
spec = importlib.util.spec_from_file_location("gui_ads", GUI)
gui = importlib.util.module_from_spec(spec)
sys.modules["gui_ads"] = gui
spec.loader.exec_module(gui)

# ---------------- 完全照抄界面 __main__ 的引擎加载 ----------------
ROOT = gui.ROOT
_mod = None
for _c in (ROOT / "strava_ads.py", ROOT / "主脚本" / "strava_ads.py",
           ROOT.parent / "主脚本" / "strava_ads.py", ROOT.parent / "strava_ads.py"):
    if _c.exists():
        _mod = _c
        break
if _mod is None:
    out("[错误] 找不到 strava_ads.py")
    sys.exit(1)
sys.path.insert(0, str(_mod.parent))
os.chdir(str(_mod.parent))
_s = importlib.util.spec_from_file_location("strava_ads", _mod)
SA = importlib.util.module_from_spec(_s)
sys.modules["strava_ads"] = SA
_s.loader.exec_module(SA)
gui.SA = SA                       # 界面按钮处理器用的是模块级 SA
out(f"[启动] 引擎: {_mod}   配置: {getattr(SA, 'ROOT', '?')}")

# ---------------- 建界面 + 日志转发(和 __main__ 一样) ----------------
app = gui.App()
app.withdraw()
_h = gui._GuiLogHandler(app.logq)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_lg = logging.getLogger("strava")
_lg.addHandler(_h)
_lg.setLevel(logging.INFO)
out(f"[界面] 已建窗口 {app.winfo_width()}x{app.winfo_height()}, 参数: "
    f"{ {k: v for k, v in app._cfg().items() if k in ('collect_regions', 'min_athletes', 'collect_target_per_account')} }")

state = {"phase": "load", "t0": time.time(), "n0": None}


def dump_gui_log():
    try:
        GUILOG.write_text(app.logt.get("1.0", "end"), encoding="utf-8")
        out(f"[界面] 界面日志框已存 -> {GUILOG.name}")
    except Exception as e:
        out(f"[界面] 存界面日志失败: {str(e)[:60]}")


def quota_now():
    try:
        logs = sorted((WS / "主脚本" / "logs").glob("run_*.log"), key=lambda p: p.stat().st_mtime)
        txt = logs[-1].read_text(encoding="utf-8", errors="replace")
        import re
        q = [int(x) for x in re.findall(r"\[quota\][^\n]*?(\d+)/200", txt)]
        return q[-1] if q else 0
    except Exception:
        return -1


def tick():
    el = time.time() - state["t0"]
    try:
        if state["phase"] == "load":
            rows = app.tree.get_children()
            if len(rows) >= 1:
                out(f"[界面] 「1.连接并加载」完成: 表格 {len(rows)} 行")
                app.var_from.set(str(SEQ))
                app.var_to.set(str(SEQ))
                out(f"[界面] 设定编号范围 {SEQ}~{SEQ}, 点「◎ 只采集」...")
                state["phase"] = "collect"
                state["t0"] = time.time()
                app.start_collect()            # ★ 等价于点「◎ 只采集」
            elif el > 180:
                out("[界面] 载入超时(180s), 放弃")
                dump_gui_log()
                app.quit()
                return
        elif state["phase"] == "collect":
            if not app.running:
                out(f"[界面] 采集结束(界面 running=False), 最后一次合格数 {quota_now()}/200")
                out(f"[界面] 按钮状态: 开始={app.btn_start['state']} 采集={app.btn_collect['state']} "
                    f"停止={app.btn_stop['state']}")
                dump_gui_log()
                app.quit()
                return
            if int(el) % 60 < 3 and int(el) > 3:
                out(f"[界面] 运行中(已 {int(el/60)} 分钟) 合格 {quota_now()}/200 "
                    f"按钮: 采集={app.btn_collect['state']} 停止={app.btn_stop['state']}")
            if el > MAX_WAIT:
                out("[界面] 超过 2 小时, 判定异常退出")
                dump_gui_log()
                app.quit()
                return
    except Exception as e:
        out(f"[界面] tick 异常: {type(e).__name__}: {str(e)[:80]}")
    app.after(1500, tick)


app.after(500, app.load_items)     # ★ 等价于点「1.连接并加载」
app.after(3000, tick)
app.mainloop()
dump_gui_log()
out(f"[界面] GUI 实跑结束, 最终合格 {quota_now()}/200")
