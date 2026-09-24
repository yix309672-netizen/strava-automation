# -*- coding: utf-8 -*-
"""全链路验证: 完全复刻同事那台"更新了但采集还是 12 个州"的机器, 走一遍真实流程。

复刻的现场条件(全部来自用户反馈):
  * 机器上装的是【老发行包】: 12 个州 / 每段>=200 / 并发 1
  * 机器上装的是【老 update.py】: 合并配置的策略是"只补缺失的键, 绝不覆盖已有值"
    —— 这正是"每段门槛变成 5000、采集州却还是 12 个"的直接原因:
       min_athletes 是大小比较能触发, collect_regions 是列表全等就不触发;
       而老 update.py 连这个都做不到, 它一个已有值都不改。
  * 机器上有同事自己的东西: 浏览器 key、头像目录、窗口列表 —— 必须原样保留

流程: 老机器的 启动.bat -> update.py --auto -> 下载最新包并替换 -> 再开界面/跑引擎
只测本次改动, 不跑整套自测。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
DIST = ROOT / "_分发给同事"

OLD_REGIONS = ["Pennsylvania", "New York", "Indiana", "Michigan", "Wisconsin",
               "Iowa", "Missouri", "Ohio", "Kentucky", "Minnesota", "Tennessee",
               "West Virginia"]

OLD_CFG = {
    "adspower_key": "COLLEAGUE_KEY_KEEP_ME",
    "adspower_api": "http://127.0.0.1:50325",
    "avatar_dir": "C:/同事/运动头像",
    "gpx_dir": "C:/同事/芝加哥运动",
    "windows": ["_3", "_7"],
    "accounts_json": "accounts.json",
    "human": {"delay_min": 0.4, "delay_max": 1.4},
    "collect_regions": OLD_REGIONS,
    "collect_auto_regions": True,
    "min_athletes": 200,
    "max_followers": 200,
    "jobs": 1,
    "collect_target_per_account": 200,
    "claim_server": "http://137.175.71.171:8000",
    "claim_key": "g1jVQg7y_K5UOtfHUgUEg6seJ4WeKJjAUGJt7shPYvk",
    "auto_close": False,
}

KEEP = ["adspower_key", "adspower_api", "avatar_dir", "gpx_dir", "windows",
        "accounts_json", "human", "auto_close", "claim_server", "claim_key"]

OLD_MARK = "OLD_PACKAGE_2026_09_18"
OLD_GUARD = '# -*- coding: utf-8 -*-\n"""老发行包占位: %s"""\nX = 1\n' % OLD_MARK

# ★ 忠实复刻【老 update.py】的行为: 文件照换, 但配置只补缺失的键
OLD_UPDATER = r'''# -*- coding: utf-8 -*-
"""老版 update.py (复刻现场) —— 配置合并策略是"只补缺失的键, 绝不覆盖已有值"。"""
import hashlib, io, json, os, sys, urllib.request, zipfile
from pathlib import Path


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
BASE = Path(__file__).resolve().parent
PROTECTED = {"config.json", "accounts.json", "bit_accounts.json", "ads_accounts.json",
             "bit_results.json", "ads_results.json", "collected_users.txt",
             "collected_seen.json", "task_state.json", "scan_results.json",
             "python_path.txt"}
PP = ("claim_cache_", "upload_counter_", "collected_users_", "链接-",
      "._pkg", ".")
cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
srv = str(cfg["claim_server"]).rstrip("/")
hdr = {"X-API-Key": cfg.get("claim_key", "")}
req = urllib.request.Request(srv + "/pkg/manifest", headers=hdr)
man = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
req = urllib.request.Request(srv + "/pkg/latest.zip", headers=hdr)
blob = urllib.request.urlopen(req, timeout=180).read()
zf = zipfile.ZipFile(io.BytesIO(blob))
done = []
for info in zf.infolist():
    if info.is_dir():
        continue
    name = Path(info.filename).name
    if name == "config.json" or name in PROTECTED or any(name.startswith(p) for p in PP):
        continue
    data = zf.read(info)
    (BASE / name).write_bytes(data)
    done.append(name)
remote = json.loads(zf.read("config.json").decode("utf-8"))
local = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
added = [k for k in remote if k not in local]          # ★ 只补缺失
for k in added:
    local[k] = remote[k]
(BASE / "config.json").write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
print("OLD_UPDATE done=%d added=%s" % (len(done), added))
'''

PROBE = r'''
import importlib.util, json, pathlib, sys
p = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("guimod", p)
m = importlib.util.module_from_spec(spec)
sys.modules["guimod"] = m
spec.loader.exec_module(m)
app = m.App(); app.withdraw(); app.update()
print("PROBE=" + json.dumps({"regions": app._regions, "min_ath": app._min_ath,
                             "jobs": app.var_jobs.get()}, ensure_ascii=False))
app.destroy()
'''

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: 期望 %r, 实际 %r" % (label, want, got))
    print("    %s %-32s %r" % ("OK  " if ok else "★FAIL", label, got))


def run(cmd, cwd, timeout=240):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)


def main():
    print("=" * 78)
    print("全链路验证: 老机器(12 州/门槛 200/老 update.py) 走一遍真实更新流程")
    print("=" * 78)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="colleague_e2e_"))
    print("  模拟目录: %s" % tmp)

    # ---- 1. 搭一台"老机器"
    print("\n[1] 搭建老机器(老代码 + 老配置)")
    for f in ("strava_ads.py", "strava_bit.py", "_gui_ads.py", "_gui_bit.py"):
        (tmp / f).write_text(OLD_GUARD, encoding="utf-8")
    (tmp / "update.py").write_text(OLD_UPDATER, encoding="utf-8")
    (tmp / "config.json").write_text(
        json.dumps(OLD_CFG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("    老配置: 采集州 %d 个 %s" % (len(OLD_REGIONS), OLD_REGIONS[:3] + ["..."]))
    print("            min_athletes=%s jobs=%s _policy_rev=%r"
          % (OLD_CFG["min_athletes"], OLD_CFG["jobs"], OLD_CFG.get("_policy_rev")))

    # ---- 2. 跑老 update.py (等价于同事双击 启动.bat)
    print("\n[2] 跑老 update.py --auto (等价于同事双击 启动.bat)")
    r = run([sys.executable, "update.py"], tmp)
    line = [x for x in (r.stdout or "").splitlines() if x.startswith("OLD_UPDATE")]
    print("    " + (line[0] if line else "(没有输出)"))
    if r.returncode != 0:
        print(((r.stdout or "") + (r.stderr or ""))[-600:])
        fails.append("老 update.py 执行失败")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    # ---- 3. 文件应该换新了
    print("\n[3] 代码文件应该被换成新版")
    for f in ("strava_ads.py", "strava_bit.py", "_gui_ads.py", "_gui_bit.py", "update.py"):
        t = (tmp / f).read_text(encoding="utf-8", errors="replace")
        good = OLD_MARK not in t
        if not good:
            fails.append("%s 没有被替换" % f)
        print("    %s %-18s %s" % ("OK  " if good else "★FAIL", f,
                                   "已换成新版" if good else "还是老的"))
    for m, f in (("enforce_admin_policy()", "strava_ads.py"),
                 ("_ADMIN_POLICY_REV = 2", "_gui_ads.py")):
        t = (tmp / f).read_text(encoding="utf-8", errors="replace")
        ok = m in t
        if not ok:
            fails.append("%s 缺 %s" % (f, m))
        print("    %s %-18s 含 %s" % ("OK  " if ok else "★FAIL", f, m))

    # ---- 4. 老更新器改不动已有值 —— 这就是现场现象
    print("\n[4] 老更新器对【已存在的键】无能为力(复刻现场现象)")
    c4 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
    check("采集州 仍是 12 个(老更新器改不动)", c4.get("collect_regions"), OLD_REGIONS)
    check("_policy_rev 必须仍然缺失", c4.get("_policy_rev"), None)

    # ---- 5. 新引擎自动纠正
    print("\n[5] 新引擎(每个任务都会跑)自动纠正")
    r = run([sys.executable, "-c", "import strava_ads"], tmp)
    if r.returncode != 0:
        print(((r.stdout or "") + (r.stderr or ""))[-800:])
        fails.append("新引擎导入失败")
    else:
        for ln in (r.stdout or "").splitlines():
            if "管理员口径" in ln or "现在:" in ln:
                print("    引擎日志 | " + ln.strip())
    c5 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
    check("collect_regions", c5.get("collect_regions"), ["New York"])
    check("min_athletes", c5.get("min_athletes"), 5000)
    check("jobs", c5.get("jobs"), 3)
    check("_policy_rev", c5.get("_policy_rev"), 2)
    print("    -- 同事自己的东西必须一个都没动 --")
    for k in KEEP:
        check(k, c5.get(k), OLD_CFG.get(k))

    # ---- 6. 新界面显示
    print("\n[6] 新界面显示(同事打开界面看到的)")
    r = run([sys.executable, "-c", PROBE, str(tmp / "_gui_ads.py")], tmp)
    probe = None
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("PROBE="):
            probe = json.loads(ln[6:])
    if probe is None:
        print(((r.stdout or "") + (r.stderr or ""))[-800:])
        fails.append("界面探测失败")
    else:
        check("界面 采集州", probe["regions"], ["New York"])
        check("界面 每段门槛", probe["min_ath"], 5000)
        check("界面 并发", probe["jobs"], "3")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 78)
    if fails:
        print("★ 失败 %d 项:" % len(fails))
        for f in fails:
            print("   - " + f)
        return 1
    print("✓ 全链路通过:")
    print("  同事双击 启动.bat -> 代码换成新版(含新 update.py / 新界面 / 新引擎)")
    print("  -> 引擎或界面一跑, 采集口径自动变成 纽约 / 每段>=5000 / 并发3")
    print("  -> 他的浏览器 key、头像目录、窗口列表一个都没被动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
