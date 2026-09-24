# -*- coding: utf-8 -*-
"""验证: 同事那台"12 个州 / 每段>=200"的老机器, 换上新引擎后会不会自动纠正。

刻意制造了用户现场的确切条件:
  * collect_regions = 12 个州, 而且【顺序打乱】(上一版列表全等的判据就是死在这里)
  * min_athletes = 200, jobs = 1
  * config.json 里再塞几个"同事自己的东西", 检查它们【绝不能被动】

只测本次改动的东西, 不跑整套自测(用户明确要求)。
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent
ENGINES = ["strava_ads.py", "strava_bit.py"]

# ★ 顺序和上一版常量里的完全不同 —— 这正是现场"条件恒为假"的原因
OLD_REGIONS = ["Pennsylvania", "New York", "Indiana", "Michigan", "Wisconsin",
               "Iowa", "Missouri", "Ohio", "Kentucky", "Minnesota", "Tennessee",
               "West Virginia"]

OLD_CFG = {
    "adspower_key": "COLLEAGUE_KEY_KEEP_ME",
    "bitbrowser_key": "BIT_KEY_KEEP_ME",
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
    "claim_key": "x",
    "auto_close": False,
}

KEEP = ["adspower_key", "bitbrowser_key", "avatar_dir", "gpx_dir", "windows",
        "accounts_json", "human", "auto_close", "claim_server", "claim_key"]

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: 期望 %r, 实际 %r" % (label, want, got))
    print("    %s %-34s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


def main():
    print("=" * 78)
    print("验证: 老机器(12 州/顺序打乱/门槛 200) -> 换上新引擎后自动纠正")
    print("=" * 78)

    for eng in ENGINES:
        print()
        print("--- %s ---" % eng)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="policy_"))
        shutil.copy2(ROOT / "主脚本" / eng, tmp / eng)
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps(OLD_CFG, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        before_key = json.loads(cfg.read_text(encoding="utf-8"))

        env = dict(**__import__("os").environ)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, "-c", "import %s" % eng[:-3]],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180,
                           env=env)
        if r.returncode != 0:
            fails.append("%s 导入失败: %s" % (eng, (r.stderr or "")[-400:]))
            print("  ★FAIL 导入失败")
            print((r.stderr or "")[-600:])
            continue
        for line in (r.stdout or "").splitlines():
            if "管理员口径" in line or "现在:" in line:
                print("    引擎日志 | " + line.strip())

        after = json.loads(cfg.read_text(encoding="utf-8"))

        check("collect_regions", after.get("collect_regions"), ["New York"])
        check("min_athletes", after.get("min_athletes"), 5000)
        check("jobs", after.get("jobs"), 3)
        check("_policy_rev", after.get("_policy_rev"), 2)

        print("    -- 同事自己的东西必须原样保留 --")
        for k in KEEP:
            check(k, after.get(k), before_key.get(k))

        print("    -- 再跑一次必须幂等(不该反复改) --")
        m1 = cfg.stat().st_mtime_ns
        t1 = cfg.read_text(encoding="utf-8")
        subprocess.run([sys.executable, "-c", "import %s" % eng[:-3]],
                       cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, env=env)
        same = cfg.read_text(encoding="utf-8") == t1
        if not same:
            fails.append("%s 不是幂等: 第二次跑又改了 config" % eng)
        print("    %s 第二次内容不变" % ("OK  " if same else "★FAIL"))

        print("    -- 版本号已对齐后, 同事自己改的值不能被覆盖 --")
        cur = json.loads(cfg.read_text(encoding="utf-8"))
        cur["collect_regions"] = ["California"]
        cur["jobs"] = 2
        cfg.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        subprocess.run([sys.executable, "-c", "import %s" % eng[:-3]],
                       cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, env=env)
        manual = json.loads(cfg.read_text(encoding="utf-8"))
        check("手动改的 collect_regions 保留", manual.get("collect_regions"), ["California"])
        check("手动改的 jobs 保留", manual.get("jobs"), 2)

        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    if fails:
        print("★ 失败 %d 项:" % len(fails))
        for f in fails:
            print("   - " + f)
        return 1
    print("✓ 全部通过: 老机器换上新引擎后, 采集口径自动变成 纽约/每段5000/并发3,")
    print("  同事自己的 key、目录、窗口列表一个都没被动; 且不会反复覆盖他的手动设置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
