# -*- coding: utf-8 -*-
"""验证:「每段」下拉框 —— 界面能选、引擎真的按选的走(不被地板抬回去)。

要证的正是最可能踩的那个坑:
    界面选了 2000 -> 引擎地板 5000 -> 悄悄抬回 5000 -> "选了没用"
所以两头都要测:
  A. 界面: 下拉框在不在、默认值、改选后 _cfg() 和 config.json 是不是都变了
  B. 引擎: resolve_min_athletes() 在各种地板配置下的实际返回值
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-48s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


PROBE = r'''
import importlib.util, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
gui = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec)
sys.modules["gm"] = m
spec.loader.exec_module(m)
app = m.App(); app.withdraw(); app.update()
r = {}
r["has_var"] = hasattr(app, "var_minath")
r["labels"] = [x[0] for x in m.MIN_ATH_CHOICES]
r["vals"] = [x[1] for x in m.MIN_ATH_CHOICES]
r["default_label"] = app.var_minath.get() if r["has_var"] else None
try:
    r["cfg_before"] = {k: app._cfg().get(k)
                       for k in ("min_athletes", "min_athletes_floor")}
except Exception as e:
    r["cfg_err"] = str(e)[:80]
# 改成 2000
app.var_minath.set("2000"); app.update()
try:
    r["cfg_after"] = {k: app._cfg().get(k)
                      for k in ("min_athletes", "min_athletes_floor")}
except Exception as e:
    r["cfg_err2"] = str(e)[:80]
print("PROBE=" + json.dumps(r, ensure_ascii=False))
try:
    app.destroy()
except Exception:
    pass
'''


def load_engine(name):
    spec = importlib.util.spec_from_file_location(
        "e_" + name, ROOT / "主脚本" / ("strava_%s.py" % name))
    m = importlib.util.module_from_spec(spec)
    sys.modules["e_" + name] = m
    spec.loader.exec_module(m)
    return m


def main():
    print("=" * 82)
    print("验证:「每段」人数门槛下拉框")
    print("=" * 82)

    # ---------------- A. 界面 ----------------
    for gui_src, gui_name in (("界面/ADS自动化.py", "ADS自动化.py"),
                              ("界面/比特派自动化.py", "比特派自动化.py")):
        print()
        print("--- A. 界面 %s ---" % gui_name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="minath_"))
        shutil.copy2(ROOT / gui_src, tmp / gui_name)
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({
            "adspower_key": "KEEP_ME", "avatar_dir": "C:/同事/头像",
            "collect_regions": ["New York"], "min_athletes": 5000,
            "jobs": 3, "_policy_rev": 2,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, "-c", PROBE, str(tmp / gui_name)],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=200, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            FAIL.append(gui_name + " 探测失败")
            print("  ★FAIL 探测失败:")
            print(((r.stdout or "") + (r.stderr or ""))[-900:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        check("下拉框存在", res["has_var"], True)
        check("默认显示 5000 那项", res["default_label"], "5000 (原有口径, 默认)")
        check("选项里有 0(不设门槛)", 0 in res["vals"], True)
        check("改选前 min_athletes", (res.get("cfg_before") or {}).get("min_athletes"), 5000)
        check("改选后 min_athletes", (res.get("cfg_after") or {}).get("min_athletes"), 2000)
        check("★ 改选后 min_athletes_floor 也变成 2000",
              (res.get("cfg_after") or {}).get("min_athletes_floor"), 2000)
        after = json.loads(cfg.read_text(encoding="utf-8"))
        check("已写回磁盘 min_athletes", after.get("min_athletes"), 2000)
        check("已写回磁盘 min_athletes_floor", after.get("min_athletes_floor"), 2000)
        check("同事自己的 key 没被动", after.get("adspower_key"), "KEEP_ME")
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- B. 引擎地板 ----------------
    for name in ("ads", "bit"):
        print()
        print("--- B. 引擎 strava_%s.py / resolve_min_athletes() ---" % name)
        m = load_engine(name)
        CFG = m.CFG

        # ① 没配 floor -> 维持老行为(抬到 5000)
        CFG.pop("min_athletes_floor", None)
        check("① 未配 floor, 选 2000 -> 抬到 5000(老行为不变)",
              m.resolve_min_athletes(2000), 5000)
        check("① 未配 floor, 选 8000 -> 8000", m.resolve_min_athletes(8000), 8000)

        # ② 配了 floor(界面会这么写) -> 按选的走
        CFG["min_athletes_floor"] = 2000
        check("② floor=2000, 选 2000 -> 2000(★选了真有用)",
              m.resolve_min_athletes(2000), 2000)
        check("② floor=2000, 选 1000 -> 抬到 2000",
              m.resolve_min_athletes(1000), 2000)
        check("② floor=2000, 选 50000 -> 50000",
              m.resolve_min_athletes(50000), 50000)

        # ③ 0 = 不设门槛
        CFG["min_athletes_floor"] = 0
        check("③ floor=0, 选 0 -> 0(不设门槛)", m.resolve_min_athletes(0), 0)

        # ④ 脏值不炸
        CFG.pop("min_athletes_floor", None)
        check("④ 脏值 'abc' -> 退回 5000", m.resolve_min_athletes("abc"), 5000)
        CFG["min_athletes_floor"] = "坏值"
        check("④ floor 是脏值 -> 按 5000 算", m.resolve_min_athletes(3000), 5000)

    print()
    print("=" * 82)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✓ 通过 %d 项: 下拉框能选 · 选完立刻写盘 · 引擎按选的走(不再被地板抬回)" % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
