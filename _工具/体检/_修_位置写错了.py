# -*- coding: utf-8 -*-
"""把指定号在 数据/task_state.json 里的 location 记录清掉, 让引擎下一轮重做「改位置」。

为什么需要这个:
    引擎记进 task_state 的是【它想写的值】("Los Angeles, California"),
    不是 Strava 真正存下来的值。地名联想的第一个候选会被它盲点,
    于是可能存成 "Bahía de los Ángeles, Baja California Mexico"(墨西哥) 或
    "Lake Los Angeles, California" —— 记录看着完全正确, 实际是错的,
    于是 pending_todo 永远认为"位置已完成", 这个号再也修不回来。
    清掉 location 这一项, 下一轮跑批就会把「位置」重新排进待办。

用法:
    python _修_位置写错了.py --win 84,85,90,91,92,94,95,100           # 只看
    python _修_位置写错了.py --win 84,85,90,91,92,94,95,100 --apply   # 清掉
"""
import argparse, json, shutil, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

WS = Path(__file__).resolve().parents[2]
ST = WS / "数据" / "task_state.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", required=True, help="窗口号, 逗号分隔, 如 84,85,90")
    ap.add_argument("--apply", action="store_true", help="真写(默认只看)")
    a = ap.parse_args()
    wins = [x.strip() for x in a.win.split(",") if x.strip()]

    data = json.loads(ST.read_text(encoding="utf-8"))
    todo, miss = [], []
    for w in wins:
        k = "ads_" + w
        st = data.get(k)
        if not isinstance(st, dict):
            miss.append(w)
            continue
        if "location" in st:
            todo.append((k, st.get("location")))

    print(f"状态文件: {ST}")
    print(f"要看 {len(wins)} 个号;  有 location 记录要清的 {len(todo)} 个;  "
          f"状态里没有的 {len(miss)} 个 {miss}")
    for k, v in todo:
        print(f"   {k:10s} 清掉 location = {v!r}")
    if not todo:
        print("没有要清的。")
        return 0
    if not a.apply:
        print("\n[dry] 没写。加 --apply 才清。")
        return 0

    bak = ST.with_name(ST.name + ".bak_before_清位置_" + time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(ST, bak)
    for k, _ in todo:
        data[k].pop("location", None)
    tmp = ST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ST)
    print(f"\n已清 {len(todo)} 个号的 location 记录。备份: {bak.name}")
    print("下一轮跑这些号时会重新做「位置」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
