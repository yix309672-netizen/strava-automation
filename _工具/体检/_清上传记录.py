# -*- coding: utf-8 -*-
"""清掉"已上传过"的记账, 让轨迹可以重传。

★ 什么时候要用它
    「上传的活动标题一律 Morning Run」这个改动, 只对【还没传的】账号生效 ——
    引擎靠 数据/task_state.json 里的 uploaded 列表判断"这条传过了", 传过的
    就直接跳过。所以已经传完的那几批, 老活动还叫 Afternoon/Evening Run。
    想返工就得两步:
        ① 先去 Strava 把那些活动删掉(不删就会新旧两批并存)
        ② 再跑本工具清掉记账, 然后正常再跑一次"仅上传轨迹"
    ★ 顺序不能反: 光清记账不删活动, 引擎看到活动数>0 会直接跳过上传。

用法:
    python _清上传记录.py                 # 只看, 列出每个窗口传了多少
    python _清上传记录.py --win _2,_15    # 只清这两个窗口(先自动备份)
    python _清上传记录.py --all           # 清全部窗口
"""
import json
import shutil
import sys
import time
from pathlib import Path


def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。"""
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent


for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = _find_project_root(__file__)
STATE = ROOT / "数据" / "task_state.json"
WINS = [w.strip() for w in sys.argv[sys.argv.index("--win") + 1].split(",")] \
    if "--win" in sys.argv and len(sys.argv) > sys.argv.index("--win") + 1 else []
ALL = "--all" in sys.argv

if not STATE.is_file():
    print(f"★ 找不到 {STATE}")
    sys.exit(1)
d = json.loads(STATE.read_text(encoding="utf-8"))

rows = [(k, len(v.get("uploaded") or [])) for k, v in d.items()
        if isinstance(v, dict) and v.get("uploaded")]
print(f"状态文件: {STATE}")
print(f"有上传记账的窗口共 {len(rows)} 个, 合计 {sum(n for _, n in rows)} 条:")
for k, n in rows:
    print(f"   {k:>6}  {n} 条")

if not WINS and not ALL:
    print()
    print("(未改动 —— 加 --win _2,_15 或 --all 才真的清)")
    raise SystemExit(0)

targets = [k for k, _ in rows] if ALL else [w for w in WINS]
todo = [k for k in targets if k in d and (d[k].get("uploaded") or [])]
if not todo:
    print()
    print("★ 没有匹配的窗口(名字要对得上, 比如 _2 / 2)")
    raise SystemExit(1)

bak = STATE.with_name(STATE.name + f".bak_before_清上传_{time.strftime('%Y%m%d_%H%M%S')}")
shutil.copy2(STATE, bak)
n = 0
for k in todo:
    n += len(d[k].get("uploaded") or [])
    d[k]["uploaded"] = []
tmp = STATE.with_name(STATE.name + ".tmp")
tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
import os
os.replace(tmp, STATE)
print()
print(f"已清空 {len(todo)} 个窗口的记账(共 {n} 条): {todo}")
print(f"备份: {bak.name}")
print()
print("★ 别忘了: 先去 Strava 把那些老活动删掉 —— 不删, 引擎看到活动数>0 会直接跳过上传。")
