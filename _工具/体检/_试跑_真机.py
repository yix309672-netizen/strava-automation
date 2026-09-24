# -*- coding: utf-8 -*-
"""试跑: 用真引擎、真窗口、真服务器跑一次【只采集】。

目的: 验证今天改的东西在真机上确实生效 ——
  · 多余标签页自动关闭(close_extra_pages)
  · 关掉控制台快速编辑(_disable_quick_edit)
  · 成果文件照常逐条写进 数据\链接-日期.txt

★ 目标只设 5 个人, 几分钟就能跑完, 不会吃掉太多共享名额。
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
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

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
ENG = ROOT / "主脚本" / "strava_bit.py"
SEQ = int(sys.argv[1]) if len(sys.argv) > 1 else 13
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 5

# ★ 引擎的 ROOT = 引擎文件所在目录, 所以直接从 主脚本\ 加载 ——
#   这样它的 数据\ 就是项目里那个真目录, 成果写进真文件。
sys.path.insert(0, str(ROOT / "主脚本"))
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("strava_bit", ENG)
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_bit"] = SA
spec.loader.exec_module(SA)

cfg = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
cfg["collect_target_per_account"] = TARGET
cfg["jobs"] = 1
cfg["collect_max_minutes"] = 12          # 安全阀: 最多跑 12 分钟
cfg["location"] = cfg.get("location") or "Chicago, Illinois"

daily = SA._daily_path()
before = 0
if daily.is_file():
    before = sum(1 for x in daily.read_text(encoding="utf-8",
                                            errors="replace").splitlines()
                 if x.strip() and not x.startswith("#"))

print("=" * 70)
print(f"引擎    : {ENG.name}")
print(f"窗口    : seq={SEQ}")
print(f"目标    : {TARGET} 人")
print(f"地区    : {cfg.get('collect_regions')}")
print(f"成果文件: {daily}")
print(f"跑之前  : {before} 条")
print(f"开始时间: {time.strftime('%H:%M:%S')}")
print("=" * 70, flush=True)

task = SA.new_task_ctx(target=TARGET, mode="tryrun", worker="tryrun")
t0 = time.time()
try:
    r = SA.collect_one(SEQ, cfg, task)
    print("\n>>> collect_one 返回:", json.dumps(r, ensure_ascii=False)[:400])
except Exception as e:
    import traceback
    print("\n>>> 抛异常:", type(e).__name__, str(e)[:200])
    traceback.print_exc()
finally:
    try:
        SA.finalize_task(task)
    except Exception:
        pass

after = 0
if daily.is_file():
    after = sum(1 for x in daily.read_text(encoding="utf-8",
                                           errors="replace").splitlines()
                if x.strip() and not x.startswith("#"))
print()
print("=" * 70)
print(f"耗时    : {(time.time()-t0)/60:.1f} 分钟")
print(f"跑之后  : {after} 条  (本次新增 {after-before})")
print(f"结束时间: {time.strftime('%H:%M:%S')}")
print("=" * 70)
