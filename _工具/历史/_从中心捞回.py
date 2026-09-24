# -*- coding: utf-8 -*-
r"""成果找回: 把中心去重库里【本地文件还没有】的合格记录补进 数据\collected_users.txt

为什么需要: 采集结果是"跑完才批量落盘"的老行为(或进程中途崩了)时,
本地 collected_users.txt 可能缺记录, 而中心库是【实时】记录的 ——
重跑又会被中心去重直接跳过, 这批人就会卡在"中心采过、本地没有"的缝里。
本工具从中心 /export 把缺的补回来。

用法:
    python -X utf8 _从中心捞回.py                        # 只看有多少缺的, 不写
    python -X utf8 _从中心捞回.py --write                # 真的追加进本地文件
    python -X utf8 _从中心捞回.py --write --since "2026-09-19 00:00"
"""
import json
import sys
import time
from pathlib import Path

import requests

WS = Path(__file__).resolve().parent
OUT = WS / "数据" / "collected_users.txt"
WRITE = "--write" in sys.argv
SINCE = ""
if "--since" in sys.argv:
    SINCE = sys.argv[sys.argv.index("--since") + 1]


def read_urls(p):
    """读成果文件 -> URL 列表。

    ★ 跳过 '#' 开头的行: 新版引擎在每个成果文件头部写任务信息
      ("# 任务开始/结束 ... / #   号 3: 68 条"), 那不是链接 ——
      当成链接会既算错"本地已有"的条数, 又可能把它当成"中心缺的"再补一遍。
    ★ 只取第一列: 新版每行是 url\taid\tregion\tsegment\tage 多列,
      整行去重会把同一个人按不同附加列算成两条。
    """
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    out = []
    for x in txt.splitlines():
        x = x.strip()
        if not x or x.startswith("#"):
            continue
        out.append(x.split("\t")[0].strip())
    return out


def main():
    cfg = json.loads((WS / "配置" / "config.json").read_text(encoding="utf-8"))
    url = cfg["claim_server"].rstrip("/") + "/export"
    r = requests.get(url, params={"fmt": "json"},
                     headers={"X-API-Key": cfg["claim_key"]}, timeout=60)
    if r.status_code != 200:
        print(f"中心库读取失败: {r.status_code} {r.text[:150]}")
        return 1
    rows = r.json()
    print(f"中心库记录: {len(rows)} 条")

    t0 = 0.0
    if SINCE:
        t0 = time.mktime(time.strptime(SINCE, "%Y-%m-%d %H:%M"))
        rows = [x for x in rows if float(x.get("ts") or 0) >= t0]
        print(f"按时间过滤(>= {SINCE}): {len(rows)} 条")

    local_lines = read_urls(OUT)
    have = set(local_lines)

    seen, missing = set(), []
    for x in rows:
        u = (x.get("url") or "").strip()
        if not u or u in have or u in seen:
            continue
        seen.add(u)
        missing.append(x)

    print(f"本地已有: {len(have)} 条 / 需要补回: {len(missing)} 条")
    for x in missing[:10]:
        print(f"   {x.get('url')}  {x.get('name','')}  [{x.get('region','')} {x.get('segment','')} {x.get('age','')}]")
    if len(missing) > 10:
        print(f"   ... 还有 {len(missing) - 10} 条")

    if not missing:
        print("本地不缺, 无需补写")
        return 0
    if not WRITE:
        print("\n(这是预演。确认无误后加 --write 真的补写)")
        return 0

    bak = OUT.with_suffix(".bak_recover")
    if OUT.exists():
        bak.write_text(OUT.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"已备份原文件 -> {bak.name}")
    with open(OUT, "a", encoding="utf-8") as f:
        for x in missing:
            f.write(x["url"] + "\n")
    n = len(read_urls(OUT))
    print(f"已补写 {len(missing)} 条, 现在文件共 {n} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
