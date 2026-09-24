# -*- coding: utf-8 -*-
"""验证: 进程启动时 claim_client.py 不在 -> 之后文件回来了, 能不能自动补上。

复刻的就是用户 10:56 那次的确切场景:
    界面启动时文件被删了 -> ClaimClient 被钉死成 None
    -> 文件后来还原了 -> 旧代码【永远不会再试】, 一直退回本地去重
                      -> collect 是 fail-closed 的, 于是整批采集被取消

只测本次改动。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
ENGINES = ["strava_ads.py", "strava_bit.py"]

PROBE = r'''
import importlib.util, json, pathlib, sys
tmp = pathlib.Path(sys.argv[1]); eng = pathlib.Path(sys.argv[2])
# ★ 完全照抄界面加载引擎的方式(界面/ADS自动化.py 第 1005-1008 行)
spec = importlib.util.spec_from_file_location("eng_probe", eng)
m = importlib.util.module_from_spec(spec)
sys.modules["eng_probe"] = m
spec.loader.exec_module(m)

r1 = m.ClaimClient
print("STEP1 " + json.dumps({"claim_client_is_none": r1 is None}))

# 文件"回来"了: 拷到引擎所在目录的上一级(就是项目根, sys.path 里有)
src = pathlib.Path(sys.argv[3])
shutil_dst = tmp / "claim_client.py"
import shutil as _sh


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
_sh.copy2(src, shutil_dst)
print("STEP2 " + json.dumps({"wrote": str(shutil_dst), "exists": shutil_dst.is_file()}))

# 关键: 不重启进程, 直接再要一次
got = m._reload_claim_client()
print("STEP3 " + json.dumps({"recovered": got is not None,
                             "name": getattr(got, "__name__", None)}))
'''

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: 期望 %r, 实际 %r" % (label, want, got))
    print("    %s %-40s %r" % ("OK  " if ok else "★FAIL", label, got))


def main():
    print("=" * 76)
    print("验证: 启动时缺 claim_client.py -> 文件回来后能否自动补上(不重启)")
    print("=" * 76)

    for eng in ENGINES:
        print()
        print("--- %s ---" % eng)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="claimheal_"))
        (tmp / "主脚本").mkdir()
        eng_dst = tmp / "主脚本" / eng
        shutil.copy2(ROOT / "主脚本" / eng, eng_dst)
        # ★ 故意【不放】claim_client.py —— 复刻启动时文件不在
        (tmp / "config.json").write_text(
            json.dumps({"claim_server": "http://137.175.71.171:8000",
                        "claim_key": "x"}, ensure_ascii=False), encoding="utf-8")

        probe_file = tmp / "_probe.py"
        probe_file.write_text(PROBE, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(probe_file), str(tmp), str(eng_dst),
             str(ROOT / "claim_client.py")],
            cwd=str(tmp), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=240, env=env)

        steps = {}
        for line in (r.stdout or "").splitlines():
            for tag in ("STEP1", "STEP2", "STEP3"):
                if line.startswith(tag + " "):
                    steps[tag] = json.loads(line[len(tag) + 1:])

        if r.returncode != 0 or "STEP1" not in steps or "STEP3" not in steps:
            print("  ★ 探测失败, 输出尾部:")
            print(((r.stdout or "") + (r.stderr or ""))[-1200:])
            fails.append("%s 探测失败" % eng)
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        check("启动时确实没导到(ClaimClient is None)",
              steps["STEP1"]["claim_client_is_none"], True)
        check("文件回来后 _reload_claim_client() 补上了",
              steps["STEP3"]["recovered"], True)
        check("补上的是真的 ClaimClient 类",
              steps["STEP3"]["name"], "ClaimClient")
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 76)
    if fails:
        print("★ 失败 %d 项:" % len(fails))
        for f in fails:
            print("   - " + f)
        return 1
    print("✓ 通过: 启动时缺 claim_client.py 的进程, 文件回来后不用重启也能自愈;")
    print("  这样就不会再出现「文件明明在, 任务却报缺 claim_client.py」了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
