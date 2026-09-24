# -*- coding: utf-8 -*-
"""界面层验证: 老配置(12 州/顺序打乱/门槛 200)下, 界面会不会自动纠正并显示新口径。

真起一次 Tk 窗口(立刻 withdraw, 不 mainloop), 用完就销毁。
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
OLD_REGIONS = ["Pennsylvania", "New York", "Indiana", "Michigan", "Wisconsin",
               "Iowa", "Missouri", "Ohio", "Kentucky", "Minnesota", "Tennessee",
               "West Virginia"]
OLD_CFG = {
    "adspower_key": "COLLEAGUE_KEY_KEEP_ME",
    "avatar_dir": "C:/同事/运动头像",
    "gpx_dir": "C:/同事/芝加哥运动",
    "accounts_json": "accounts.json",
    "collect_regions": OLD_REGIONS,
    "min_athletes": 200,
    "jobs": 1,
    "claim_server": "http://137.175.71.171:8000",
    "claim_key": "x",
}

PROBE = r'''
import importlib.util, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
p = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("guimod", p)
m = importlib.util.module_from_spec(spec)
sys.modules["guimod"] = m
spec.loader.exec_module(m)
app = m.App()
app.withdraw()
app.update()
out = {"regions": app._regions, "min_ath": app._min_ath,
       "jobs": app.var_jobs.get(), "target": app.var_target.get(),
       "key": app.var_key.get() if hasattr(app, "var_key") else None,
       "avdir": app.var_avdir.get()}
print("PROBE=" + json.dumps(out, ensure_ascii=False))
app.destroy()
'''

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: 期望 %r, 实际 %r" % (label, want, got))
    print("    %s %-30s %r" % ("OK  " if ok else "★FAIL", label, got))


def main():
    print("=" * 78)
    print("界面层验证: 老机器 12 州(顺序打乱)/门槛 200 -> 界面显示与配置都应对齐")
    print("=" * 78)
    for gui_src, gui_name in [("界面/ADS自动化.py", "ADS自动化.py"),
                              ("界面/比特派自动化.py", "比特派自动化.py")]:
        print()
        print("--- %s ---" % gui_name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="guitest_"))
        shutil.copy2(ROOT / gui_src, tmp / gui_name)
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps(OLD_CFG, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run([sys.executable, "-c", PROBE, str(tmp / gui_name)],
                               cwd=str(tmp), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=180,
                               env=env)
        except subprocess.TimeoutExpired:
            fails.append("%s 起界面超时" % gui_name)
            print("  ★FAIL 起界面超时")
            shutil.rmtree(tmp, ignore_errors=True)
            continue
        probe = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                probe = json.loads(line[6:])
        if probe is None:
            fails.append("%s 探测失败" % gui_name)
            print("  ★FAIL 探测失败, 输出尾部:")
            print(((r.stdout or "") + (r.stderr or ""))[-800:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        check("界面显示 采集州数", probe["regions"], ["New York"])
        check("界面显示 每段门槛", probe["min_ath"], 5000)
        check("界面显示 并发", probe["jobs"], "3")
        check("界面显示 目标人数", probe["target"], "200")
        # 头像目录: 界面【故意】只写本机桌面路径, 不跟随管理员(每台机器各自的目录),
        # 所以这里只检查"没被管理员的绝对路径污染", 不要求等于本地测试值。
        av = probe["avdir"]
        ok = ("C:/同事" not in av) and ("运动头像" in av)
        if not ok:
            fails.append("界面头像目录异常: %r" % av)
        print("    %s %-30s %r (本机默认, 符合预期)"
              % ("OK  " if ok else "★FAIL", "界面头像目录不跟管理员走", av))

        after = json.loads(cfg.read_text(encoding="utf-8"))
        check("磁盘 collect_regions", after.get("collect_regions"), ["New York"])
        check("磁盘 min_athletes", after.get("min_athletes"), 5000)
        check("磁盘 jobs", after.get("jobs"), 3)
        check("磁盘 _policy_rev", after.get("_policy_rev"), 2)
        check("磁盘 adspower_key 保留", after.get("adspower_key"), "COLLEAGUE_KEY_KEEP_ME")
        check("磁盘 avatar_dir 保留", after.get("avatar_dir"), "C:/同事/运动头像")
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    if fails:
        print("★ 失败 %d 项:" % len(fails))
        for f in fails:
            print("   - " + f)
        return 1
    print("✓ 界面层通过: 老配置一开界面就自动纠正, 显示 纽约 / 每段>=5000 / 并发3,")
    print("  同事的浏览器 key 和头像目录没被动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
