# -*- coding: utf-8 -*-
r"""把剩下没跑过的账号全部跑完（真开浏览器、真改资料、真传轨迹、真采集）

用法：
    python _批量跑2.py                # 默认跑 3,38,39,40,41,43,45,46,47,48,49,50,51,52
    python _批量跑2.py 38 39 40       # 指定编号

和 _批量跑.py 的唯一区别：
  * 账号列表从命令行来（默认是"检查出来没跑过的那批"）
  * 日志/结果写 _批量跑2.log / _批量跑2结果.json，不覆盖上一批的验收证据
  * 单个账号超时放宽到 25 分钟（新号要做 onboarding + 资料 + 传轨迹 + 采集）

走的是界面真实代码路径：逐个调 start_task()，等这个跑完再跑下一个。
每跑完一个，记录表格那一行 —— 用来验证"数据有没有自动填进表格"。
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

DEFAULT_SEQS = ["3", "38", "39", "40", "41", "43",
                "45", "46", "47", "48", "49", "50", "51", "52"]
SEQS = [a for a in sys.argv[1:] if a.strip()] or DEFAULT_SEQS
PER_MAX = 25 * 60          # 单个账号最多等 25 分钟
LOGF = WS / "_批量跑2.log"
RESULT = WS / "_批量跑2结果.json"

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
spec = importlib.util.spec_from_file_location("rbg2", GUI)
mod = importlib.util.module_from_spec(spec)
sys.modules["rbg2"] = mod
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

# ★ 确认跑的是"带真名读取"的新引擎, 否则整批验证没意义
assert hasattr(SA, "read_settings_name"), "引擎不是新版: 缺 read_settings_name"

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
log("  本批账号: %s" % ",".join(SEQS))
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
skip_n = 0
for i, seq in enumerate(SEQS, 1):
    log("")
    log("#" * 64)
    log("#  [%d/%d] 账号 %s" % (i, len(SEQS), seq))
    log("#" * 64)
    if not app.tree.exists(seq):
        log("  ★ 表格里没有 %s，跳过" % seq)
        skip_n += 1
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
    if str(v[4]).strip() == "是" and str(v[5]).strip():
        ok_n += 1
    app._save_results()

log("")
log("#" * 64)
log("#  汇总：%d/%d 个账号 登录=是 且 名字已自动填入"
    % (ok_n, len(SEQS) - skip_n))
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
