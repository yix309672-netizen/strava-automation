# -*- coding: utf-8 -*-
"""真机实跑: 走界面「◎ 只采集」同一条路径(collect_one), 目标 200 个合格用户
用法: python -X utf8 _真机实跑.py 3
输出: 屏幕 + _真机实跑.log
"""
import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

WS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sa", WS / "主脚本" / "strava_ads.py")
sa = importlib.util.module_from_spec(spec)
sys.modules["sa"] = sa
spec.loader.exec_module(sa)

SEQ = sys.argv[1] if len(sys.argv) > 1 else "3"
OUT = WS / "数据" / "collected_users.txt"
LOGP = WS / "_真机实跑.log"
STALL_MIN = 6


def out(msg=""):
    line = str(msg)
    print(line, flush=True)
    try:
        with open(LOGP, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def lines():
    """总表条数: '#' 开头的是新版引擎写在成果文件头部的任务信息, 不是链接, 必须跳过。"""
    try:
        return len([x for x in OUT.read_text(encoding="utf-8").splitlines()
                    if x.strip() and not x.strip().startswith("#")])
    except Exception:
        return -1


def start_watchdog():
    """★ 卡死看门狗: 引擎日志超过 STALL_MIN 分钟没有增长就判为卡死并退出。
    为什么要: 00:02 那次截图调用永久阻塞, 日志 11 分钟没有任何输出,
    看起来像"还在干活", 实际整轮已经死了(连"停止"都点不动)。"""
    logf = WS / "主脚本" / "logs" / f"run_{time.strftime('%Y%m%d')}.log"

    def loop():
        last_size, last_change = -1, time.time()
        while True:
            time.sleep(20)
            try:
                sz = logf.stat().st_size if logf.exists() else -1
            except Exception:
                sz = -1
            if sz != last_size:
                last_size, last_change = sz, time.time()
            elif time.time() - last_change > STALL_MIN * 60:
                out(f"!!! 看门狗: 引擎日志已 {STALL_MIN} 分钟没有增长, 判定卡死 -> 退出(exit 9)")
                os._exit(9)

    threading.Thread(target=loop, daemon=True).start()


def main():
    rows = json.loads((WS / "数据" / "ads_results.json").read_text(encoding="utf-8"))
    r = rows.get(str(SEQ)) or {}
    out("=" * 78)
    out(f"真机实跑 {time.strftime('%H:%M:%S')} 环境={SEQ} 账号={r.get('email')} "
        f"已知会员={r.get('prem')}")
    start_watchdog()
    cfg = dict(sa.CFG)
    cfg.update({
        "collect_regions": sa.CFG.get("collect_regions") or ["New York"],
        "min_athletes": 5000,
        "max_followers": 200,
        "collect_target_per_account": 200,
        "segs_per_region": 0,
        "geo_filter": True,
        "auto_close": True,
    })
    out(f"本次参数: target={cfg['collect_target_per_account']} "
        f"min_athletes={cfg['min_athletes']} regions={cfg['collect_regions']}")
    n0 = lines()
    t0 = time.time()
    res = None
    try:
        # ★ 界面「◎ 只采集」走的就是 collect_one(seq, cfg);
        #   不要用 run_one_seq(那是「▶ 开始任务」, 会先跑资料/隐私/轨迹)
        res = sa.collect_one(int(SEQ), cfg)
    except Exception as e:
        out(f"!! 实跑异常: {type(e).__name__}: {str(e)[:200]}")
        traceback.print_exc()
    dt = (time.time() - t0) / 60.0
    n1 = lines()
    out("")
    out(f"结果: {json.dumps(res, ensure_ascii=False) if res else '(无返回)'}")
    out(f"collected_users.txt: {n0} -> {n1}  (本次新增 {n1 - n0} 条)")
    out(f"耗时: {dt:.1f} 分钟")
    out(f"目标 200: {'达标 ✓' if (n1 - n0) >= 200 else '未达标 ✗'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
