# -*- coding: utf-8 -*-
"""真机跑一个号的【全部流程】(等价于界面点「▶ 开始任务」)。

为什么不用命令行: strava_ads.py 的命令行入口按 --from/--to 跑, 但它读
配置/accounts.json 找账号; 而界面上填的账号在 配置/ads_accounts.json 里
(100 号只在后者里)。所以这里照界面的做法来: 读 ads_accounts.json ->
run_one_seq(seq, email, pwd, cfg, task)。

用法:
    python _试跑_ADS全流程.py 100          # 跑第 100 号
    python _试跑_ADS全流程.py 100 5        # 第 100 号, 每号目标 5 人
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
SEQ = str(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 200

sys.path.insert(0, str(ROOT / "主脚本"))
spec = importlib.util.spec_from_file_location(
    "strava_ads", ROOT / "主脚本" / "strava_ads.py")
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = SA
spec.loader.exec_module(SA)

cfg = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
acc = json.loads((ROOT / "配置" / "ads_accounts.json").read_text(encoding="utf-8"))
a = acc.get(SEQ) or {}
EM, PW = str(a.get("email") or ""), str(a.get("password") or "")
if not (EM and PW):
    print(f"★ ads_accounts.json 里没有 {SEQ} 号的账号密码, 跑不了")
    sys.exit(2)

cfg["collect_target_per_account"] = TARGET
cfg["jobs"] = 1
cfg["task_mode"] = "全部(资料+隐私+轨迹)"
print("=" * 72)
print(f"引擎    : strava_ads.py")
print(f"编号    : {SEQ}   账号: {EM}")
print(f"执行内容: {cfg['task_mode']}")
print(f"每号目标: {TARGET} 人    地区: {cfg.get('collect_regions')}")
print(f"年龄/时间/性别: {cfg.get('collect_age_groups')} / "
      f"{cfg.get('collect_date_range')} / {cfg.get('collect_gender')}")
print(f"开始    : {time.strftime('%H:%M:%S')}")
print("=" * 72, flush=True)

task = SA.new_task_ctx(target=TARGET, mode="全流程试跑", worker="tryrun")
t0 = time.time()
try:
    r = SA.run_one_seq(SEQ, EM, PW, cfg, task)
    print("\n>>> run_one_seq 返回:", json.dumps(r, ensure_ascii=False)[:500])
except Exception as e:
    import traceback
    print("\n>>> 抛异常:", type(e).__name__, str(e)[:200])
    traceback.print_exc()
finally:
    try:
        SA.finalize_task(task)
    except Exception:
        pass

print()
print("=" * 72)
print(f"耗时: {(time.time() - t0) / 60:.1f} 分钟   结束: {time.strftime('%H:%M:%S')}")
print("=" * 72)
