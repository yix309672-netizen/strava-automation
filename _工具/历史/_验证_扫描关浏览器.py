# -*- coding: utf-8 -*-
"""验证: 扫描完一个号 -> 自动关闭该号浏览器。

重点是复现用户那台机器的确切条件:
    配置/config.json 里 auto_close = false
    —— 旧代码读的就是它, 于是扫描时【一个号都不关】, 扫 30 个号开 30 个浏览器。

所以本测试的核心断言是:
    ★ auto_close=false 时, 扫描仍然必须关闭浏览器(不受它影响)
"""
import importlib.util
import inspect
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
    print("    %s %-52s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


PROBE = r'''
import importlib.util, inspect, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
tmp = pathlib.Path(sys.argv[1]); eng = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("ee", eng)
m = importlib.util.module_from_spec(spec)
sys.modules["ee"] = m
spec.loader.exec_module(m)

out = {}
out["auto_close"] = m.CFG.get("auto_close")
out["scan_close"] = m.CFG.get("scan_close")
out["default_should_close"] = m.scan_should_close()

src = inspect.getsource(m.scan_one)
# ★ 断言前先【剥掉注释行】: 新代码的注释里写着"注意这里不再看 auto_close",
#   直接搜字符串会把注释当成代码 -> 误报(我第一次就踩了)。
#   真正要防的是【代码里还在读 CFG.get("auto_close")】。
code = "\n".join(l for l in src.splitlines()
                 if not l.strip().startswith("#"))
out["scan_one_mentions_auto_close"] = "auto_close" in code
out["scan_one_calls_scan_should_close"] = "scan_should_close()" in code

# 显式关掉时应该不关
m.CFG["scan_close"] = False
out["when_false"] = m.scan_should_close()
m.CFG["scan_close"] = True
out["when_true"] = m.scan_should_close()
# 脏值
m.CFG["scan_close"] = "坏值"
out["when_garbage"] = m.scan_should_close()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 84)
    print("验证: 扫描完成自动关闭该号浏览器")
    print("=" * 84)

    for name in ("ads", "bit"):
        print()
        print("--- strava_%s.py ---" % name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="scanclose_"))
        shutil.copy2(ROOT / "主脚本" / ("strava_%s.py" % name),
                     tmp / ("strava_%s.py" % name))
        # ★★ 复刻用户那台机器的条件: auto_close = false ★★
        (tmp / "config.json").write_text(json.dumps({
            "collect_regions": ["Chicago"],
            "auto_close": False,          # ← 旧代码就是读它, 于是扫描一个都不关
            "scan_close": True,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        pf = tmp / "_p.py"
        pf.write_text(PROBE, encoding="utf-8")
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), str(tmp),
                            str(tmp / ("strava_%s.py" % name))],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            FAIL.append("%s 探测失败" % name)
            print("  ★FAIL 探测失败:")
            print(((r.stdout or "") + (r.stderr or ""))[-1000:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        check("前提: 配置里 auto_close 确实是 false", res["auto_close"], False)
        check("★ auto_close=false 时扫描仍然关闭浏览器",
              res["default_should_close"], True)
        check("★ scan_one 里不再引用 auto_close",
              res["scan_one_mentions_auto_close"], False)
        check("★ scan_one 走的是 scan_should_close()",
              res["scan_one_calls_scan_should_close"], True)
        check("scan_close=false 时才不关", res["when_false"], False)
        check("scan_close=true 时关", res["when_true"], True)
        check("scan_close 是脏值 -> 退回关(默认)", res["when_garbage"], True)
        shutil.rmtree(tmp, ignore_errors=True)

    # 配置里两处都该有 scan_close
    print()
    print("--- 配置 ---")
    for rel in ("配置/config.json", "_分发给同事/config.json"):
        d = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        check("%s 有 scan_close=true" % rel, d.get("scan_close"), True)

    print()
    print("=" * 84)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✓ 通过 %d 项: 扫描完每个号都关浏览器, 且【不受 auto_close 影响】" % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
