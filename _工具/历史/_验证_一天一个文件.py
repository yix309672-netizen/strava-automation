# -*- coding: utf-8 -*-
"""验证: 成果文件真的变成"一天一个"了。

不读代码猜, 直接驱动引擎的任务函数看它落出什么文件:
  ① 同一天跑两次任务 -> 只应有 1 个文件
  ② 两次任务的链接都在这一个文件里
  ③ 重复链接不会写第二遍(去重仍然有效)
  ④ 不再出现 <时间戳>.txt / <时间戳>_<号>.txt 这种分文档
  ⑤ 历史总表 collected_users.txt 仍然维护(它是累计去重的底账, 不能丢)
"""
import datetime
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
    print("    %s %-50s %r" % ("OK  " if ok else "★FAIL", label, got))
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
tmp = pathlib.Path(sys.argv[1]); eng = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("eng", eng)
m = importlib.util.module_from_spec(spec)
sys.modules["eng"] = m
spec.loader.exec_module(m)

def run_task(urls, seq="7"):
    task = m.new_task_ctx(target=10, mode="gui", worker="W")
    sub = m.new_account_ctx(task, seq)
    for u in urls:
        m.append_task_url(sub, u)
    m.finalize_task(task)
    return task

# 第一次任务
t1 = run_task(["https://www.strava.com/athletes/101",
               "https://www.strava.com/athletes/102"], seq="7")
# 第二次任务(同一天), 其中一个链接是重复的
t2 = run_task(["https://www.strava.com/athletes/102",
               "https://www.strava.com/athletes/103"], seq="9")

txt = sorted(p.name for p in tmp.glob("*.txt")
             if p.name.startswith("链接-") or p.name.startswith("collected_users"))
daily = [n for n in txt if n != "collected_users.txt"]
out = {"files": txt, "daily": daily,
       "final1": t1["final"].name if t1.get("final") else None,
       "final2": t2["final"].name if t2.get("final") else None}
for n in txt:
    out["c:" + n] = (tmp / n).read_text(encoding="utf-8").splitlines()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 84)
    print("验证: 成果文件「一天一个」")
    print("=" * 84)

    for name in ("ads", "bit"):
        print()
        print("--- strava_%s.py ---" % name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="daily_"))
        shutil.copy2(ROOT / "主脚本" / ("strava_%s.py" % name),
                     tmp / ("strava_%s.py" % name))
        # 平铺布局: config.json 就在引擎旁边 -> 数据文件写同级
        (tmp / "config.json").write_text(
            json.dumps({"collect_regions": ["Chicago"]}, ensure_ascii=False),
            encoding="utf-8")
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

        import datetime
        today = datetime.datetime.now().strftime("%Y%m%d")
        daily_name = "链接-%s.txt" % today

        check("① 同一天两次任务只落 1 个日期文件", res["daily"], [daily_name])
        check("① 没有 <时间戳>_<号>.txt 这种号级明细",
              [n for n in res["daily"] if n.count("_") > 2], [])
        check("② 两次任务的 final 都指向同一个文件",
              [res["final1"], res["final2"]], [daily_name, daily_name])
        lines = res.get("c:" + daily_name) or []
        body = [x for x in lines if x.strip() and not x.startswith("#")]
        check("② 三个不同链接都在这个文件里",
              sorted(body), ["https://www.strava.com/athletes/10%d" % i
                             for i in (1, 2, 3)])
        check("③ 重复的 102 只出现一次",
              body.count("https://www.strava.com/athletes/102"), 1)
        check("④ 文件头只有一行日期", [x for x in lines if x.startswith("#")],
              ["# 采集日期 %s" % datetime.datetime.now().strftime("%Y-%m-%d")])
        check("⑤ 历史总表仍在维护", "collected_users.txt" in res["files"], True)
        master = res.get("c:collected_users.txt") or []
        check("⑤ 总表里也是 3 条(无重复)",
              sorted(x for x in master if x.strip()), sorted(body))
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- 安全断言: 改名之后, 成果文件还受保护吗 ----------------
    print()
    print("--- 安全断言: 成果文件名「链接-<日期>」是否被正确识别 ---")
    import ast
    sample = "链接-%s.txt" % datetime.datetime.now().strftime("%Y%m%d")

    # ① 发布更新.py 的 EXCLUDE: 漏了 -> 链接会被打进包传上 VPS
    t = ast.parse((ROOT / "发布更新.py").read_text(encoding="utf-8"))
    exc = []
    for node in ast.walk(t):
        if isinstance(node, ast.Assign) and \
                getattr(node.targets[0], "id", "") == "EXCLUDE":
            exc = [e.value for e in node.value.elts]
    hit = [x for x in exc if x in sample]
    check("① 发布更新.py 会排除成果文件(不泄露到 VPS)", bool(hit), True)
    print("        命中的排除规则: %s" % hit)

    # ② update.py / fix_update.py 的 PROTECTED_PREFIX: 漏了 -> 被更新覆盖
    for fn in ("update.py", "fix_update.py"):
        t = ast.parse((ROOT / fn).read_text(encoding="utf-8"))
        pp = []
        for node in ast.walk(t):
            if isinstance(node, ast.Assign) and \
                    getattr(node.targets[0], "id", "") == "PROTECTED_PREFIX":
                pp = [e.value for e in node.value.elts]
        hit = [x for x in pp if sample.startswith(x)]
        check("② %s 保护成果文件(不被更新覆盖/删除)" % fn, bool(hit), True)
        print("        命中的保护前缀: %s" % hit)

    # ③ 引擎 _out_index 必须扫两种文件名, 否则跨天去重会失效
    eng = ROOT / "主脚本" / "strava_ads.py"
    s = eng.read_text(encoding="utf-8")
    check("③ _out_index 扫新文件名", 'DAILY_FILE_PREFIX + "*.txt"' in s, True)
    check("③ _out_index 也扫老文件名(历史文件不丢)",
          'TASK_FILE_PREFIX + "*.txt"' in s, True)

    print()
    print("=" * 84)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✓ 通过 %d 项: 一天一个文件 · 两次任务合并 · 去重有效 · 总表保留" % len(PASS))
    return 0


if __name__ == "__main__":
    import subprocess
    raise SystemExit(main())
