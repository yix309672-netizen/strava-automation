# -*- coding: utf-8 -*-
"""一次性：把本地历史成果回灌中心服务（审计发现 1627 人里约 1019 人中心"查无此人"）

为什么会有这个缺口：
    这批人是老引擎的 `collect_users` 通道采到的 —— 那条路【只写本地文件、不向中心
    登记】。后果是别的机器在排行榜上再碰到他们时，中心仍然答"没见过"，于是被
    重复采集一遍。

⚠⚠ 但【回灌本身有真实副作用，不要无脑跑】—— 这是本脚本最重要的提示 ⚠⚠
    老的 `collect_users` 通道（strava_ads.py:2123-2309）是"只读排行榜、直接抓链接"的，
    它【没有】做任何合格性筛选（不看粉丝/关注、不看位置、不走领取）。所以这 1176 人
    里必然混着不合条件的人。把他们 `POST /collected` 登记成"成果"，等于：
        ① 把未经验证的人写进中心成果库；
        ② 从此 20 台同事机器再碰到他们时会被去重挡住，永远不会补验。
    也就是说：**回灌能消除"重复采集"，代价是可能固化"错误成果"。**

    审计的 `方案_dedup.md` 步骤 12 建议回灌，但它没有把这层取舍写出来。真正稳妥的做法
    是二选一，由你拍板：
      A. 不回灌 —— 让这 1176 人保持"中心未知"，被别的机器重采一次（浪费一点时间，
         但结果是【正确】的）；
      B. 回灌，但只回灌【中心已判 reject 之外】且你人工抽样确认合格的那部分。
    默认行为 = 只对账（dry-run），不做任何写入。

安全性：
    * 服务端 `POST /collected` 走 `INSERT OR IGNORE`（claim_store.py:209-215），aid 是
      主键 —— 脚本【幂等】，重复执行不会产生重复行，也不会覆盖已有成果。
    * 真正写入必须显式加 `--write`；默认只拉 /export 对账、打印差集。

用法：
    python -X utf8 _回灌中心_历史成果.py             # 只对账，不写（默认）
    python -X utf8 _回灌中心_历史成果.py --write     # 真回灌(会跳过中心已判 reject 的人)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL_RE = re.compile(r"https://www\.strava\.com/athletes/(\d+)")


def _find_data_dir():
    """与引擎 _find_data_dir() 同口径: 平铺=本目录; 分层包=数据/"""
    if (ROOT / "config.json").exists():
        return ROOT
    for c in (ROOT / "数据", ROOT.parent / "数据"):
        if c.is_dir():
            return c
    return ROOT


DATA = _find_data_dir()
OUT = DATA / "collected_users.txt"


def load_local():
    """返回 {aid: url}（保序）。跳过 '#' 注释行，只取第一列。"""
    if not OUT.exists():
        print(f"★ 找不到成果文件: {OUT}")
        return {}
    d = {}
    for line in OUT.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split("\t")[0]
        m = URL_RE.fullmatch(line)
        if m:
            d[m.group(1)] = line
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="真的回灌(不带这个参数只对账, 不写中心库)")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条(调试用)")
    a = ap.parse_args()

    try:
        from claim_client import ClaimClient, resolve_worker_id
    except Exception as e:
        print(f"★ 导入 claim_client 失败: {e}")
        return 2

    cfg = {}
    for c in (ROOT / "config.json", ROOT / "配置" / "config.json"):
        if c.exists():
            try:
                cfg = json.loads(c.read_text(encoding="utf-8"))
                break
            except Exception:
                pass
    server = (cfg.get("claim_server") or "").strip()
    key = (cfg.get("claim_key") or "").strip()
    if not server:
        print("★ config.json 里没有 claim_server")
        return 2

    local = load_local()
    print(f"本地成果文件 : {OUT}")
    print(f"本地唯一人数 : {len(local)}")

    cli = ClaimClient(server, resolve_worker_id("backfill"), key,
                      cache_file=str(DATA / "claim_cache_backfill.json"))
    h = cli.ping()
    if not h:
        print(f"★ 中心服务不可达: {server}")
        return 2
    print(f"中心服务     : {server}  {h}")

    # 中心【成果表】里已有的人（/known 查的是 athletes 表, 口径不同, 必须用 /export）
    rows = cli._get("/export", {"fmt": "json"}) or []
    central = {}
    for r in rows:
        if isinstance(r, dict) and r.get("aid"):
            central[str(r["aid"])] = r
    print(f"中心成果表   : {len(central)} 人")

    missing = [aid for aid in local if aid not in central]

    # ★ 中心已判 reject 的人【绝不能】回灌成"成果" —— 否则等于把被淘汰的人
    #   写进成果库, 还会挡住别人重新验证。先查出来, 从回灌清单里剔除。
    rejects, _k = [], {}
    try:
        _k = cli.refresh_known(list(local.keys())) or {}
        rejects = [aid for aid in local if (_k.get(aid) or {}).get("status") == "reject"]
    except Exception as e:
        print(f"(reject 对账跳过: {str(e)[:60]})")
    missing = [x for x in missing if x not in set(rejects)]

    print()
    print("=" * 66)
    print(f"中心查无此人 : {len(missing)} 人  ({len(missing)/max(1,len(local))*100:.1f}%)")
    print("=" * 66)
    if rejects:
        print(f"中心已判淘汰、却仍在本地交付文件里: {len(rejects)} 人"
              f"（前 5 个: {rejects[:5]}）")
        print("  → 已从回灌清单剔除(不把淘汰者登记成成果)")
        print("  → 建议人工确认后再决定要不要从交付文件里也剔除")

    # ★★ 2026-09-19 用户要求: "把 1627 和服务器的数据对比去重, 然后保留没重复的"。
    #   这里把【中心成果表里没有的(= 本地独有)】写成一份纯链接清单, 一个 URL 一行,
    #   不带任何附加列(与新的任务文件格式一致)。文件名带时间戳, 可直接拿去用。
    _uniq_p = DATA / f"本地独有_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        with open(_uniq_p, "w", encoding="utf-8") as f:
            for _aid in missing:
                f.write(local[_aid] + "\n")
        print()
        print("=" * 66)
        print(f"★ 本地独有(中心没有的) {len(missing)} 条  ->  {_uniq_p.name}")
        print("=" * 66)
        print(f"    完整路径: {_uniq_p}")
        print(f"    口径: 本地 {len(local)} 条 | 中心成果表 {len(central)} 条 | "
              f"其中中心已判淘汰 {len(rejects)} 条(已剔除)")
    except Exception as e:
        print(f"★ 独有清单写入失败: {str(e)[:80]}")

    if not missing:
        print("\n无需回灌。")
        return 0

    todo = missing[:a.limit] if a.limit else missing
    if not a.write:
        print(f"\n【dry-run】将回灌 {len(todo)} 人。确认无误后加 --write 真跑。")
        print(f"  前 5 个: {[local[x] for x in todo[:5]]}")
        return 0

    ok = dup = err = 0
    t0 = time.time()
    for i, aid in enumerate(todo, 1):
        try:
            # ★ ClaimClient.collect() 的 worker 取自实例(self.worker), 不是形参 ——
            #   传 worker= 会 TypeError。
            _r = cli.collect(aid, local[aid], region="backfill")
            # 服务端返回 {"ok":True,"inserted":ins}; store.collect 是 INSERT OR IGNORE
            # (claim_store.py:209-215), inserted=False 说明中心本来就有这条
            if isinstance(_r, dict) and _r.get("inserted") is False:
                dup += 1
            else:
                ok += 1
        except Exception as e:
            err += 1
            if err <= 3:
                print(f"  [err] {aid}: {str(e)[:60]}")
        if i % 200 == 0:
            print(f"  ...{i}/{len(todo)}  新增{ok} 已存在{dup} 失败{err}  "
                  f"{time.time()-t0:.0f}s")
        time.sleep(0.01)
    print()
    print(f"回灌完成: 新增 {ok} / 中心已有 {dup} / 失败 {err} / 共 {len(todo)}  "
          f"耗时 {time.time()-t0:.0f}s")
    print("复核: 重跑一次本脚本(不带 --write)，'中心查无此人' 应降到接近 0。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
