# -*- coding: utf-8 -*-
r"""200 人达标验收: 跑完后自动核对证据
用法: python -X utf8 _验收_200.py <本次运行开始时间戳>
  例: python -X utf8 _验收_200.py "2026-09-19 00:28"
核对:
  ① 引擎日志里有 达标 200/200(或最后一次 [quota] 合格数)
  ② 数据\collected_users.txt(历史总表) 总条数 >= 200 且**无重复**
  ③ 数据\collected_users_<时间戳>.txt(本次任务那一份, 按时间戳定位) 的条数与重复
  ④ 中心去重库 /export 里本次时间段的新增 pass 记录数
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

WS = Path(__file__).resolve().parent
SINCE = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d %H:%M")
DATA = WS / "数据"
OUT = DATA / "collected_users.txt"       # 历史总表(50+ 次任务累计, 不是"本次")
RUNLOG = WS / "_真机实跑.log"

# 任务成果文件: collected_users_<YYYYMMDD>_<HHMMSS>[_<号>].txt
# tid 是定宽零填充的 -> 字典序 == 时间序, 所以"tid 最大"就是"最近一次任务"
TASK_RE = re.compile(r"^collected_users_(\d{8}_\d{6})(?:_(\d+))?\.txt$")

FAILS = []


def ck(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def read_rows(p):
    """读成果文件 -> URL 列表(只留第一列)。

    ★ 必须这么读, 两个原因:
      1. 跳过 '#' 开头的行: 新版引擎会在每个成果文件头部写任务信息
         ("# 任务开始 ... / # 任务结束 ... / #   号 3: 68 条 (...)"), 那些不是链接,
         混进来会同时污染"总条数"和"重复数"两个判据;
      2. 只取第一列: 新版每行是 url\taid\tregion\tsegment\tage 多列,
         拿整行跟中心的 url 比对会一条都匹配不上(第一列恒为 URL, 向后兼容老文件)。
    """
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for x in txt.splitlines():
        x = x.strip()
        if not x or x.startswith("#"):
            continue
        rows.append(x.split("\t")[0].strip())
    return rows


def find_task_file():
    """按时间戳定位【本次任务】的成果文件: 数据/ 下 collected_users_*.txt 里 tid 最大的那个。

    为什么要按时间戳找, 而不是看历史总表: 总表是 50+ 次任务的累计(现在 2586 行,
    其中 959 行历史重复), 跟"这一次跑了多少、干不干净"毫无关系; 用户的硬需求是
    "每次任务一个带时间的文档", 验收就必须盯那一份。
    同一个 tid 下会同时存在号级明细(_<号>)和任务成品 -> 优先取成品(汇总件)。
    """
    cands = []
    for p in DATA.glob("collected_users_*.txt"):
        m = TASK_RE.match(p.name)
        if not m:
            continue
        cands.append((m.group(1), 0 if m.group(2) else 1, p.name, p))
    if not cands:
        return None
    cands.sort(key=lambda t: t[:3])         # (tid, 是否成品, 文件名) 升序
    return cands[-1][3]


print(f"=== 200 人达标验收 (运行起点 {SINCE}) ===")

# 看门狗/驱动日志里的 起止条数
start_n = end_n = None
if RUNLOG.exists():
    for line in RUNLOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"collected_users\.txt: (\d+) -> (\d+)", line)
        if m:
            start_n, end_n = int(m.group(1)), int(m.group(2))
        m2 = re.search(r"目标 200: (\S+)", line)
        if m2:
            ck("驱动脚本判定达标", "达标" in m2.group(1) and "未达标" not in m2.group(1), m2.group(1))
ck("驱动脚本有起止条数", start_n is not None and end_n is not None, f"{start_n} -> {end_n}")
if start_n is not None:
    ck("本次新增 == 200", end_n - start_n == 200, f"新增 {end_n - start_n}")

# ① 引擎日志
logs = sorted((WS / "主脚本" / "logs").glob("run_*.log"), key=lambda p: p.stat().st_mtime)
if logs:
    txt = logs[-1].read_text(encoding="utf-8", errors="replace")
    q = [int(x) for x in re.findall(r"\[quota\][^\n]*?(\d+)/200", txt)]
    ck("日志出现 [quota] 合格 200/200", (max(q) if q else 0) >= 200, f"最大 {max(q) if q else 0}")
    ck("日志出现 达标 字样", ("达标" in txt), "")

# ② 本地落盘: 历史总表(累计口径) —— 去重 + 无重复
lines = read_rows(OUT)
ck("collected_users.txt 总条数 >= 200", len(lines) >= 200, len(lines))
dup = len(lines) - len(set(lines))
ck("文件内无重复链接", dup == 0, f"重复 {dup} 条")

# ③ 本次任务那一份(按时间戳定位): 这才是"这次任务"的成果
print("--- 本次任务文件 ---")
TASK_OUT = find_task_file()
ck("找到本次任务成果文件(数据/collected_users_<时间戳>.txt)", TASK_OUT is not None,
   TASK_OUT.name if TASK_OUT else "数据/ 下还没有采集任务生成的文件")
if TASK_OUT is not None:
    tlines = read_rows(TASK_OUT)
    tdup = len(tlines) - len(set(tlines))
    ck(f"{TASK_OUT.name} 条数 >= 200", len(tlines) >= 200, f"{len(tlines)} 条")
    ck(f"{TASK_OUT.name} 内无重复链接", tdup == 0, f"重复 {tdup} 条")

# ④ 中心去重库
try:
    cfg = json.loads((WS / "配置" / "config.json").read_text(encoding="utf-8"))
    r = requests.get(cfg["claim_server"].rstrip("/") + "/export", params={"fmt": "json"},
                     headers={"X-API-Key": cfg["claim_key"]}, timeout=30)
    rows = r.json() if r.status_code == 200 else []
    ck("中心 /export 可用", r.status_code == 200, f"{r.status_code} 共 {len(rows)} 条")
    t0 = time.mktime(time.strptime(SINCE, "%Y-%m-%d %H:%M"))
    new = []
    for x in rows:
        try:
            if float(x.get("ts") or 0) >= t0:
                new.append(x)
        except Exception:
            continue
    ck("中心库本次时间段新增 pass >= 200", len(new) >= 200, f"新增 {len(new)} 条")
    # 本次新增的人是否都在本地文件里
    urls = {x.get("url") for x in new if x.get("url")}
    miss = [u for u in urls if u not in set(lines)]
    ck("中心新增的人都在本地文件里(不丢)", len(miss) == 0, f"缺 {len(miss)} 条 例:{miss[:3]}")
except Exception as e:
    ck("中心 /export 检查", False, str(e)[:80])

print()
print(f"结论: {'达标 ✓ 各项证据一致' if not FAILS else '有 %d 项不通过' % len(FAILS)}")
for f in FAILS:
    print("  ✗ " + f)
sys.exit(1 if FAILS else 0)
