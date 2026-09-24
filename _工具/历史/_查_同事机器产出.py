# -*- coding: utf-8 -*-
"""从【服务器数据】反推同事那边到底发生了什么。

手里有的线索:
  · 服务器有 `/export`(中心库全部记录) 和 `/stats`
  · 每条记录带 worker(机器号) 和 ts(时间)
  → 可以按【机器】和【时间】还原出每台同事机器干了什么:
      有没有连上中心? 有没有提交成果? 什么时候开始不干活了?

这比让同事操作可靠得多。
"""
import json
import time
import urllib.request
from collections import Counter, defaultdict


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

CFG = json.loads(open("配置/config.json", encoding="utf-8").read())
SRV = CFG["claim_server"].rstrip("/")
KEY = CFG["claim_key"]
H = {"X-API-Key": KEY}


def get(path, data=None, timeout=180):
    url = SRV + path
    if data is not None:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode(), headers={**H,
            "Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


print("=" * 82)
print("从服务器数据反推每台同事机器的情况")
print("=" * 82)

st = json.loads(get("/stats"))
print()
print("1) 中心库总览")
print("-" * 82)
print("  按状态: %s" % st.get("athletes_by_status"))
print("  总数  : %s" % st.get("athletes"))

# ---- 导出全部记录 ----
print()
print("2) 拉取全部记录(按机器/时间还原)...")
try:
    csv = get("/export")
except Exception as e:
    print("  ★ /export 失败: %s" % str(e)[:80])
    raise SystemExit(1)
lines = csv.splitlines()
print("  拿到 %d 行(含表头)" % len(lines))
if len(lines) < 2:
    print("  ★ 没有数据")
    raise SystemExit(0)
hdr = lines[0].split(",")
print("  列: %s" % hdr)
idx = {n: i for i, n in enumerate(hdr)}


def col(parts, name):
    i = idx.get(name)
    return parts[i] if (i is not None and i < len(parts)) else ""


rows = []
for l in lines[1:]:
    p = l.split(",")
    if len(p) < 2:
        continue
    rows.append(p)
print("  有效记录 %d 条" % len(rows))

# ---- 按机器号统计 ----
print()
print("3) 每台机器(worker)的产出")
print("-" * 82)
by_worker = defaultdict(lambda: {"n": 0, "first": None, "last": None,
                                 "ts": []})
for p in rows:
    wk = col(p, "worker") or "(空)"
    ts = col(p, "ts")
    d = by_worker[wk]
    d["n"] += 1
    if ts:
        try:
            t = float(ts)
        except Exception:
            t = None
        if t:
            d["ts"].append(t)
            if d["first"] is None or t < d["first"]:
                d["first"] = t
            if d["last"] is None or t > d["last"]:
                d["last"] = t


def fmt(t):
    return time.strftime("%m-%d %H:%M", time.localtime(t)) if t else "-"


print("  %-28s %7s  %-14s %-14s %s"
      % ("机器号", "条数", "最早", "最晚", "距今"))
now = time.time()
for wk, d in sorted(by_worker.items(), key=lambda x: -x[1]["n"]):
    ago = ""
    if d["last"]:
        h = (now - d["last"]) / 3600
        ago = "%.1f 小时前" % h if h < 48 else "%.1f 天前" % (h / 24)
    flag = ""
    if d["last"] and (now - d["last"]) > 24 * 3600:
        flag = "   ★ 超过一天没动静"
    print("  %-28s %7d  %-14s %-14s %s%s"
          % (wk, d["n"], fmt(d["first"]), fmt(d["last"]), ago, flag))

# ---- 最近 24 小时活跃度 ----
print()
print("4) 最近 24 小时每台机器的提交量(看谁停了)")
print("-" * 82)
cut = now - 24 * 3600
recent = Counter()
for p in rows:
    ts = col(p, "ts")
    if not ts:
        continue
    try:
        t = float(ts)
    except Exception:
        continue
    if t >= cut:
        recent[col(p, "worker") or "(空)"] += 1
if recent:
    for wk, n in recent.most_common():
        print("  %-28s %6d 条" % (wk, n))
    silent = [w for w in by_worker if w not in recent]
    if silent:
        print()
        print("  ★ 24 小时内【没有提交】的机器:")
        for w in silent:
            d = by_worker[w]
            print("     %-26s 最后一次 %s" % (w, fmt(d["last"])))
else:
    print("  ★ 最近 24 小时一条都没有 —— 所有机器都停了?")

# ---- 被拒的比例 ----
print()
print("5) 按状态看(是不是大量重复被拒)")
print("-" * 82)
by_status = Counter(col(p, "status") or "?" for p in rows)
for k, v in by_status.most_common():
    print("  %-12s %6d 条" % (k, v))
