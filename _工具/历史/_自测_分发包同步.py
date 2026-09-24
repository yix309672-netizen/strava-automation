# -*- coding: utf-8 -*-
"""分发包同步自测 —— 校验 _分发给同事/ 是否与最新脚本一致

默认【只读】: 只算哈希 / 读 config / grep 源码, 不改任何文件。
上传相关的动作只在显式加 --with-dryrun 时才做(那条会写 _待发布.zip)。

用法:
    python _自测_分发包同步.py                # 只读体检
    python _自测_分发包同步.py --with-dryrun  # 额外跑 发布更新.py --dry-run

★ 本脚本永不修改 主脚本/ 界面/ 数据/ —— 只读它们。
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent
PKG = WS / "_分发给同事"

# 5 对: 源 -> 包内副本
PAIRS = (
    (WS / "主脚本" / "strava_ads.py",        PKG / "strava_ads.py"),
    (WS / "主脚本" / "strava_bit.py",        PKG / "strava_bit.py"),
    (WS / "geo_cities.py",                   PKG / "geo_cities.py"),
    (WS / "界面" / "ADS自动化.py",            PKG / "_gui_ads.py"),
    (WS / "界面" / "比特派自动化.py",         PKG / "_gui_bit.py"),
)

# 应进包的缺陷修复标记 (在【副本】里 grep)
# ★ 2026-09-19 改造后标记更新:
#   `_rec["written"]` 这个旧标记随"任务上下文"改造消失了 —— 原写法是
#   `_rec["written"] = True`(先占位后赋值), 现在是 `"written": True` 直接写在
#   dict 字面量里, 所以旧标记永远 grep 不到。真正要证明的"采到一条立刻落盘"
#   现在由 `append_task_url(...)` 承担(而且新增了判重: 返回 False 就不计数),
#   所以标记换成 append_task_url —— 它同时证明"逐条落盘"与"写前判重"两件事,
#   比旧标记更严, 不是放宽。
DEFECTS = (
    ("ZOOM_MIN_STEPS",            "缩放下限 6"),
    ("ZOOM_MAX_STEPS = 8",        "缩放上限 8"),
    ("_cdp_grab",                 "CDP 截图兜底"),
    ("page_alive",                "断线不再误判非会员"),
    ("append_task_url(",          "采到一条就落盘 + 写前判重"),
    ("int(str(seq).strip())",     "seq 类型兜底"),
    ("new_task_ctx",              "每次任务独立带时间戳的 txt"),
    ("finalize_task",             "任务收尾汇总"),
    ("rate_gate(",                "风控速率闸门(提速不越界)"),
    ("collect_max_minutes",       "单号全局时间预算(防跑不完)"),
)
DEFECT_FILES = ("strava_ads.py", "strava_bit.py")

# config.json 必须匹配的新口径
WANT_CFG = {
    "collect_regions": ["New York"],
    "min_athletes": 5000,
    "collect_target_per_account": 200,
    "collect_auto_regions": True,
    "geo_band_min_km": 100,
    "geo_band_max_km": 1000,
    "ny_exempt_max_km": True,
    "lb_max_pages": 8,
    "segs_per_region": 0,
    "geo_filter": True,
}
MUST_ABSENT = ("check_per_segment",)
MUST_EMPTY = ("adspower_key", "bitbrowser_key")
# claim_* 是共享的, 必须保持非空原值
MUST_KEEP = ("claim_server", "claim_key")

fails = []


def log(m=""):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check(ok, label, detail=""):
    log("  [%s] %s%s" % ("OK" if ok else "!!", label, ("  " + detail) if detail else ""))
    if not ok:
        fails.append(label)
    return ok


# ---------------- A. 5 对逐字节一致 ----------------
log("=== A. 5 对脚本哈希 (SHA256 前 12 位) ===")
for src, dst in PAIRS:
    if not src.is_file():
        check(False, "%s 源文件不存在" % src)
        continue
    if not dst.is_file():
        check(False, "%s 副本不存在" % dst.name)
        continue
    a, b = sha(src), sha(dst)
    check(a == b, "%-16s src=%s dst=%s" % (dst.name, a[:12], b[:12]))

# ---------------- B. config.json 口径 ----------------
log("")
log("=== B. config.json 口径 ===")
cfg_p = PKG / "config.json"
try:
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
except Exception as e:
    cfg = None
    check(False, "config.json 读取/解析失败: %s" % str(e)[:80])

if cfg is not None:
    for k, v in WANT_CFG.items():
        got = cfg.get(k, "<MISSING>")
        check(got == v, "%-28s = %r" % (k, got), "" if got == v else "应为 %r" % (v,))
    for k in MUST_ABSENT:
        check(k not in cfg, "不含 %s" % k)
    for k in MUST_EMPTY:
        check(cfg.get(k, None) == "", '%s == ""' % k, "实际 %r" % (cfg.get(k),))
    for k in MUST_KEEP:
        check(bool(str(cfg.get(k) or "").strip()), "%s 保持非空原值" % k)

# ---------------- C. 缺陷是否真的进包 ----------------
log("")
log("=== C. 关键缺陷是否进包 (grep 副本) ===")
for name in DEFECT_FILES:
    f = PKG / name
    if not f.is_file():
        check(False, "%s 不存在" % name)
        continue
    text = f.read_text(encoding="utf-8", errors="ignore")
    for needle, desc in DEFECTS:
        n = text.count(needle)
        check(n > 0, "%-14s %-26s x%d  (%s)" % (name, needle, n, desc))

# ---------------- D. 可选: 打包体检 ----------------
if "--with-dryrun" in sys.argv:
    log("")
    log("=== D. python 发布更新.py --dry-run ===")
    r = subprocess.run([sys.executable, str(WS / "发布更新.py"), "--dry-run"],
                       cwd=str(WS), capture_output=True)
    out = (r.stdout or b"").decode("utf-8", "replace")
    log(out.rstrip())
    if r.stderr:
        log("[stderr] " + (r.stderr or b"").decode("utf-8", "replace").rstrip())
    check(r.returncode == 0, "发布更新.py --dry-run 退出码 = %d" % r.returncode)
    check("体检" in out and "干净" in out, "体检 : 干净")

log("")
if fails:
    log("!!! 未通过 %d 项: %s" % (len(fails), " | ".join(fails)))
    sys.exit(1)
log("=== 全部通过: 分发包与最新脚本一致 ===")
sys.exit(0)
