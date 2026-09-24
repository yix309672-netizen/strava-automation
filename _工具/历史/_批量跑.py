# -*- coding: utf-8 -*-
r"""把这 6 个账号跑完（真开浏览器、真改资料、真传轨迹）

编号 34/35/36/37/42/44 —— 它们只做过采集，资料/隐私/单位/头像都没做。
今天已经采集过（collected=2026-09-18），所以采集步骤会自动跳过。

用界面真实代码路径：逐个点 start_task()，等这个跑完再跑下一个。
每跑完一个，记录表格那一行，用来验证"数据有没有自动填进表格"。
"""
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
os.environ["PYTHONIOENCODING"] = "utf-8"

SEQS = ["34", "35", "36", "37", "42", "44"]
PER_MAX = 12 * 60          # 单个账号最多等 12 分钟
LOGF = WS / "_批量跑.log"
RESULT = WS / "_批量跑结果.json"

buf = []
rows_before = {}
rows_after = {}


def log(m):
    m = (str(m).replace("\u25b6", ">").replace("\u25cf", "*")
         .replace("\u25a0", "#").replace("\u2715", "x").replace("\u27f3", "R"))
    buf.append(m)
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------- 初始化（照界面 __main__）
GUI = WS / "界面" / "ADS自动化.py"
spec = importlib.util.spec_from_file_location("rbg", GUI)
mod = importlib.util.module_from_spec(spec)
sys.modules["rbg"] = mod
spec.loader.exec_module(mod)
ROOT = mod.ROOT
_m = None
for c in (ROOT / "strava_ads.py", ROOT / "主脚本" / "strava_ads.py",
          ROOT.parent / "主脚本" / "strava_ads.py"):
    if c.exists():
        _m = c
        break
sys.path.insert(0, str(_m.parent))
os.chdir(str(_m.parent))
s = importlib.util.spec_from_file_location("strava_ads", _m)
SA = importlib.util.module_from_spec(s)
sys.modules["strava_ads"] = SA
s.loader.exec_module(SA)
mod.SA = SA

app = mod.App()
app.withdraw()
h = mod._GuiLogHandler(app.logq)
h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                 datefmt="%H:%M:%S"))
logging.getLogger("strava").addHandler(h)
logging.getLogger("strava").setLevel(logging.INFO)
for _ in range(30):
    app.update()
    time.sleep(0.02)

log("=== 连接并加载 ===")
app.load_items()
t0 = time.time()
while time.time() - t0 < 120:
    app.update()
    time.sleep(0.05)
    if app.tree.exists(SEQS[0]):
        break
log("  表格 %d 行" % len(app.tree.get_children()))

app.var_jobs.set("1")          # 串行，避免 AdsPower 限速
app.var_close.set(True)

ok_n = 0
for i, seq in enumerate(SEQS, 1):
    log("")
    log("#" * 64)
    log("#  [%d/%d] 账号 %s" % (i, len(SEQS), seq))
    log("#" * 64)
    if not app.tree.exists(seq):
        log("  ★ 表格里没有 %s，跳过" % seq)
        continue
    v0 = app.tree.item(seq, "values")
    rows_before[seq] = list(v0)
    log("  跑之前: 登录=%r 名字=%r 城市=%r 活动=%r 会员=%r 隐私=%r"
        % (v0[4], v0[5], v0[6], v0[7], v0[8], v0[9]))

    app.var_from.set(seq)
    app.var_to.set(seq)
    app.logt.delete("1.0", "end")
    app.running = False
    app.stop_flag.clear()
    SA.STOP_EVENT.clear()
    app.start_task()

    seen = 0
    t0 = time.time()
    while True:
        app.update()
        try:
            lines = [x for x in app.logt.get("1.0", "end").splitlines()
                     if x.strip()]
        except Exception:
            lines = []
        while seen < len(lines):
            log("  | " + lines[seen])
            seen += 1
        el = time.time() - t0
        if not app.running and el > 5:
            log("  --- %s 结束，耗时 %.0f 秒 ---" % (seq, el))
            break
        if el > PER_MAX:
            log("  ★ %s 超过 %d 分钟，停止" % (seq, PER_MAX // 60))
            app.stop_task()
            t2 = time.time()
            while time.time() - t2 < 60:
                app.update()
                time.sleep(0.05)
            break
        time.sleep(0.2)

    for _ in range(60):          # 等回填的队列排空
        app.update()
        time.sleep(0.03)
    v = app.tree.item(seq, "values")
    rows_after[seq] = list(v)
    log("  跑之后: 登录=%r 名字=%r 城市=%r 活动=%r 会员=%r 隐私=%r"
        % (v[4], v[5], v[6], v[7], v[8], v[9]))
    if any(str(x).strip() for x in v[4:10]):
        ok_n += 1
    app._save_results()

log("")
log("#" * 64)
log("#  汇总：%d/%d 个账号的表格被自动填上" % (ok_n, len(SEQS)))
log("#" * 64)

# 落盘
try:
    saved = json.loads((mod.RES_FILE).read_text(encoding="utf-8"))
except Exception:
    saved = {}
out = {}
for seq in SEQS:
    out[seq] = {"before": rows_before.get(seq),
                "after": rows_after.get(seq),
                "saved": saved.get(seq)}
RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                  encoding="utf-8")
LOGF.write_text("\n".join(buf), encoding="utf-8")
log("")
log("结果 -> %s" % RESULT.name)
log("日志 -> %s" % LOGF.name)

try:
    app.destroy()
except Exception:
    pass
