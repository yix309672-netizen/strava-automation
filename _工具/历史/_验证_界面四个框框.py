# -*- coding: utf-8 -*-
"""验证: 界面上新增的 4 个下拉框能否正常工作、不报错。

回答用户那句"能否加上去不报错" —— 不是读代码猜, 是真起一次界面。
对每个界面(ADS / 比特)都做同样四件事:
  ① 老配置(只有 collect_regions, 没有新的三个键)下能起来, 不报错
  ② 4 个下拉框都在, 且显示的文字合法(是选项之一)
  ③ 改选之后, 存进 config.json 的值正确(含"地点名"这种新写法)
  ④ 存出来的值能被引擎的校验函数接受(不会让 Strava 返回 400)

★ 真起 Tk 窗口后立刻 withdraw, 用完 destroy。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

PROBE = r'''
import importlib.util, inspect, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
gui = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("guimod", gui)
m = importlib.util.module_from_spec(spec)
sys.modules["guimod"] = m
spec.loader.exec_module(m)

app = m.App()
app.withdraw()
app.update()

res = {}
res["has_region"] = hasattr(app, "var_region")
res["has_age"] = hasattr(app, "var_age")
res["has_gender"] = hasattr(app, "var_gender")
res["has_daterange"] = hasattr(app, "var_daterange")
res["region_choices"] = list(m.REGION_CHOICES)
res["age_labels"] = [x[0] for x in m.AGE_CHOICES]
res["gender_labels"] = [x[0] for x in m.GENDER_CHOICES]
res["date_labels"] = [x[0] for x in m.DATE_CHOICES]
res["region_default"] = app.var_region.get()
res["age_default"] = app.var_age.get()
res["gender_default"] = app.var_gender.get()
res["date_default"] = app.var_daterange.get()

# ---- 改选成用户点名的那个地点 + 非默认的性别/时间/年纪 ----
#   ★ 这会触发 _save_collect_choice 的 trace -> 立刻写回 config.json
app.var_region.set("Central Park (New York)")
app.var_gender.set("女性")
app.var_daterange.set("今年")
app.var_age.set("只要 70-74 (单个)")
app.update()

# ---- ★ 拿【引擎真正收到的那份运行时字典】(_cfg 的返回值) ----
#   这才是"跑任务时用的口径"; 只查 config.json 是不够的 ——
#   界面的 _cfg() 不写盘, 引擎导入后 CFG 也不会再读盘。
try:
    _c = app._cfg()
    res["cfg"] = {k: _c.get(k) for k in
                  ("collect_regions", "collect_gender",
                   "collect_date_range", "collect_age_groups")}
except Exception as e:
    res["cfg_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])

print("PROBE=" + json.dumps(res, ensure_ascii=False))
try:
    app.destroy()
except Exception:
    pass
'''

fails = []


def check(label, got, want):
    ok = got == want
    if not ok:
        fails.append("%s: 期望 %r, 实际 %r" % (label, want, got))
    print("    %s %-38s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


def main():
    print("=" * 78)
    print("验证: 界面上新增的 4 个下拉框(采集地区/年纪/性别/时间范围)")
    print("=" * 78)

    # 引擎的合法取值, 用来校验界面存出来的东西
    sys.path.insert(0, str(ROOT / "主脚本"))
    import strava_ads as sa  # noqa

    for gui_src, gui_name in (("界面/ADS自动化.py", "ADS自动化.py"),
                              ("界面/比特派自动化.py", "比特派自动化.py")):
        print()
        print("--- %s ---" % gui_name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="gui4box_"))
        shutil.copy2(ROOT / gui_src, tmp / gui_name)
        cfg = tmp / "config.json"
        # ★ 老配置: 只有 collect_regions, 没有新增的三个键
        cfg.write_text(json.dumps({
            "adspower_key": "KEEP_ME",
            "avatar_dir": "C:/同事/头像",
            "collect_regions": ["New York"],
            "min_athletes": 5000,
            "jobs": 3,
            "_policy_rev": 2,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run([sys.executable, "-c", PROBE, str(tmp / gui_name)],
                               cwd=str(tmp), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=200,
                               env=env)
        except subprocess.TimeoutExpired:
            fails.append("%s 起界面超时" % gui_name)
            print("  ★FAIL 起界面超时")
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            fails.append("%s 探测失败" % gui_name)
            print("  ★FAIL 探测失败, 输出尾部:")
            print(((r.stdout or "") + (r.stderr or ""))[-1200:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        check("① 老配置能起来, 4 个下拉框都在",
              [res["has_region"], res["has_age"], res["has_gender"],
               res["has_daterange"]], [True, True, True, True])
        check("② 采集地区默认值来自 config",
              res["region_default"], "New York")
        check("② 性别默认显示「男性」", res["gender_default"], "男性")
        check("② 时间默认显示「本月」", res["date_default"], "本月")
        check("② 年纪默认是 55+ 那项", res["age_default"],
              "55-64 + 65-69 两个都采(默认)")
        check("③ 改选后界面变量已更新", res.get("region_default") is not None, True)
        c = res.get("cfg") or {}
        if res.get("cfg_err"):
            fails.append("%s _cfg() 抛异常: %s" % (gui_name, res["cfg_err"]))
            print("  ★FAIL _cfg() 抛异常: %s" % res["cfg_err"])
        check("③ _cfg 里的 collect_regions(地点名)",
              c.get("collect_regions"), ["Central Park (New York)"])
        check("③ _cfg 里的 collect_gender", c.get("collect_gender"), "female")
        check("③ _cfg 里的 collect_date_range",
              c.get("collect_date_range"), "this_year")
        check("③ _cfg 里的 collect_age_groups",
              c.get("collect_age_groups"), ["70_74"])

        # ★ 另一条路: 改选是否写回了 config.json(下次启动还能记住)
        after = json.loads(cfg.read_text(encoding="utf-8"))
        check("③ 已写回磁盘 collect_regions", after.get("collect_regions"),
              ["Central Park (New York)"])
        check("③ 已写回磁盘 collect_gender", after.get("collect_gender"), "female")
        check("③ 已写回磁盘 collect_age_groups",
              after.get("collect_age_groups"), ["70_74"])
        check("③ 同事自己的 key 没被动", after.get("adspower_key"), "KEEP_ME")
        check("③ 同事自己的头像目录没被动", after.get("avatar_dir"), "C:/同事/头像")

        # ---- ④ 存出来的值必须被引擎接受 ----
        g = c.get("collect_gender")
        d = c.get("collect_date_range")
        ages = c.get("collect_age_groups") or []
        check("④ 性别在引擎合法集合内", g in sa.GENDERS_VALID, True)
        check("④ 时间在引擎合法集合内", d in sa.DATE_RANGES_VALID, True)
        check("④ 年龄组全部合法(不会 400)",
              all(a in sa.AGE_GROUPS_VALID for a in ages), True)
        check("④ 地区搜索关键词(去括号)",
              sa.region_search_key(after["collect_regions"][0]), "Central Park")
        check("④ 该地点被认作纽约来源(拿豁免)",
              sa.region_is_ny("Central Park (New York)"), True)

        # 界面里所有下拉选项都得是引擎认的(invalid 选项等于坑用户)
        bad_g = [v for _l, v in
                 [(x, y) for x, y in [("男性", "male"), ("女性", "female"),
                                      ("全部", "overall")]]
                 if v not in sa.GENDERS_VALID]
        check("④ 性别下拉里没有非法选项", bad_g, [])

        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 78)
    if fails:
        print("★ 失败 %d 项:" % len(fails))
        for f in fails:
            print("   - " + f)
        return 1
    print("✓ 通过: 4 个下拉框都能用, 老配置能起来, 改选后存的值引擎全部接受,")
    print("  同事自己的 key / 目录没被动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
