# -*- coding: utf-8 -*-
"""验证: 同事拿到这个包, 解压后能不能真的跑起来。

★ 这是最重要的一步 —— 前面所有验证都是"我们的代码对不对",
  这一步验的是"同事那块能不能用"。

做法: 找一个干净临时目录, 把包解开, 然后:
  ① 关键文件在不在
  ② 引擎能不能 import(会读 config)
  ③ 界面能不能起(真起一次 Tk)
  ④ 成果文件会写到哪、文件名叫什么
  ⑤ 一键检查.bat 能不能跑
  ⑥ 口径对不对(55+ / 2000 / 今年 / 美国境内)
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

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

# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = _find_project_root(__file__)
# ★ 2026-09-20 用户要求「不要更新那么多同事包, 分类整理」之后, 包统一放在
#   桌面\Strava发布包\ 里, 名字固定叫 发给同事_脚本包_最新.zip。
#   这里两个位置都找一下, 老位置(直接扔桌面)也兼容。
_DESK = pathlib.Path.home() / "Desktop"
zips = sorted((_DESK / "Strava发布包").glob("发给同事_脚本包*.zip"))
if not zips:
    zips = sorted(_DESK.glob("发给同事_脚本包_*.zip"))
if not zips:
    print("★ 没找到同事包 —— 先跑 _打包给同事.py")
    print(f"  找过: {_DESK / 'Strava发布包'}  和  {_DESK}")
    raise SystemExit(1)
ZIP = zips[-1]
print("=" * 84)
print("验包: %s" % ZIP.name)
print("=" * 84)

PASS, FAIL = [], []


def ck(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-50s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


tmp = pathlib.Path(tempfile.mkdtemp(prefix="colleague_pkg_"))
with zipfile.ZipFile(ZIP) as z:
    z.extractall(tmp)
# 里面是一层目录，进去
sub = [d for d in tmp.iterdir() if d.is_dir()]
if len(sub) == 1:
    base = sub[0]
else:
    base = tmp
print("  解压到: %s" % base)

print()
print("--- 1. 文件齐不齐 ---")
for n in ("启动.bat", "Start_AdsPower.bat", "Start_BitBrowser.bat",
          "strava_ads.py", "strava_bit.py", "_gui_ads.py", "_gui_bit.py",
          "claim_client.py", "geo_cities.py", "update.py", "fix_update.py",
          "config.json", "check.py", "一键检查.bat", "使用说明_先看这个.txt"):
    ck("有 %s" % n, (base / n).is_file(), True)

print()
print("--- 2. config 口径(同事拿到的默认值) ---")
cfg = json.loads((base / "config.json").read_text(encoding="utf-8"))
ck("年龄只留 55+", cfg.get("collect_age_groups"), ["55_64", "65_69"])
ck("性别 男", cfg.get("collect_gender"), "male")
ck("时间 今年", cfg.get("collect_date_range"), "this_year")
ck("每段门槛 2000", cfg.get("min_athletes"), 2000)
ck("门槛地板 2000", cfg.get("min_athletes_floor"), 2000)
ck("只要美国境内", cfg.get("us_only"), True)
ck("圆心按脚本位置", cfg.get("geo_center"), "config")
ck("扫描关浏览器", cfg.get("scan_close"), True)
ck("浏览器 key 为空(同事自己填)", cfg.get("adspower_key"), "")

print()
print("--- 3. 引擎能不能 import(会真读 config) ---")
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
code = (
    "import importlib.util, json, pathlib, sys\n"
    "spec = importlib.util.spec_from_file_location('e', r'%s')\n"
    "m = importlib.util.module_from_spec(spec); sys.modules['e']=m\n"
    "spec.loader.exec_module(m)\n"
    "print(json.dumps({'DATA_DIR': str(m.DATA_DIR), 'COLLECT_OUT': str(m.COLLECT_OUT),\n"
    "  'DAILY': str(m._daily_path()),\n"
    "  'age': list(m._age_groups_of(None)),\n"
    "  'gender': m._lb_filters()[0], 'dr': m._lb_filters()[1],\n"
    "  'minath': m.resolve_min_athletes(2000)}))\n" % (base / "strava_ads.py")
)
r = subprocess.run([sys.executable, "-c", code], cwd=str(base),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=240, env=env)
info = None
for line in (r.stdout or "").splitlines():
    line = line.strip()
    if line.startswith("{"):
        try:
            info = json.loads(line)
        except Exception:
            pass
if info is None:
    ck("引擎 import 成功", False, True)
    print("    ★ 输出:", ((r.stdout or "") + (r.stderr or ""))[-500:])
else:
    ck("引擎 import 成功", True, True)
    ck("引擎实际用的年龄组", info["age"], ["55_64", "65_69"])
    ck("引擎实际用的性别", info["gender"], "male")
    ck("引擎实际用的时间范围", info["dr"], "this_year")
    ck("引擎实际的门槛(不被地板抬)", info["minath"], 2000)
    print("    数据目录: %s" % info["DATA_DIR"].replace(str(base), "<包目录>"))
    print("    成果文件: %s" % info["DAILY"].replace(str(base), "<包目录>"))

print()
print("--- 4. 界面能不能起(真起一次 Tk) ---")
PROBE = r'''
import importlib.util, pathlib, sys, json
gui = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec); sys.modules["gm"] = m
spec.loader.exec_module(m)
app = m.App(); app.withdraw(); app.update()
out = {"region": app.var_region.get(), "age": app.var_age.get(),
       "gender": app.var_gender.get(), "dr": app.var_daterange.get(),
       "minath": app.var_minath.get(), "cols": list(m.FIELDS)[:4],
       # ★ 2026-09-22: 把下拉框的【全部选项】也带出来 ——
       #   用户要求"每段 100~900 的也要能采", 光验当前值不够,
       #   得确认那几个选项真的在框里。
       "minath_all": [x[0] for x in m.MIN_ATH_CHOICES],
       "cols_all": list(m.FIELDS),
       # ★ 把内部变量也带出来: 光看显示文字有时会骗人(以前踩过),
       #   两个一起对才知道真值。
       "_min_ath": app._min_ath}
print("PROBE=" + json.dumps(out, ensure_ascii=False))
app.destroy()
'''
pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
r2 = subprocess.run([sys.executable, str(pf), str(base / "_gui_ads.py")],
                    cwd=str(base), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=240, env=env)
res = None
for line in (r2.stdout or "").splitlines():
    if line.startswith("PROBE="):
        res = json.loads(line[6:])
if res is None:
    ck("界面能起来", False, True)
    print("    ★", ((r2.stdout or "") + (r2.stderr or ""))[-400:])
else:
    ck("界面能起来", True, True)
    ck("界面显示年纪 = 55+ 那项", res["age"], "55-64 + 65-69 两个都采(默认)")
    ck("界面显示性别 = 男性", res["gender"], "男性")
    ck("界面显示时间 = 今年", res["dr"], "今年")
    # ★ 2026-09-22: 每段门槛的标签现在带说明("2000 (发行包默认)"),
    #   所以只比"以这个值开头", 不再死比整串 ——
    #   否则以后每改一次下拉文案, 这条就假报警一次。
    ck("界面显示每段 = 2000", str(res["minath"]).startswith("2000"), True)
    ck("界面每段下拉里有 100~900", all(
        any(str(v).startswith(str(x)) for v in res.get("minath_all", []))
        for x in (100, 200, 900)), True)
    ck("界面内部 _min_ath 也是 2000", res["_min_ath"], 2000)
    # ★ 2026-09-20 用户要求「备注还是恢复成原样吧。移到后面去」之后,
    #   前四列变回 编号/窗口/账号/密码, 备注挪到最后一列。
    ck("列顺序 备注已移到最后一列", res["cols"], ["seq", "win", "email", "password"])
    ck("备注确实是最后一列", res["cols_all"][-1], "note")

print()
print("--- 5. 一键检查.bat 能不能跑 ---")
bat = base / "一键检查.bat"
b = bat.read_bytes()
crlf = b.count(b"\r\n"); lf = b.count(b"\n") - crlf
na = sum(1 for x in b if x > 127)
ck("bat 是 CRLF", lf, 0)
ck("bat 是纯 ASCII", na, 0)
r3 = subprocess.run([sys.executable, str(base / "check.py")], cwd=str(base),
                    input="\n", capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=300, env=env)
ck("check.py 能跑完", r3.returncode, 0)
outfiles = sorted(list((pathlib.Path.home() / "Desktop").glob("CheckResult_*.txt")) +
                  list((pathlib.Path.home() / "Desktop").glob("检查结果_*.txt")),
                  key=lambda p: p.stat().st_mtime)
ck("生成了结果文件(CheckResult_* 或 检查结果_*)", len(outfiles) > 0, True)
ck("中英文两个名字都生成了", len(outfiles) >= 2, True)
if outfiles:
    t = outfiles[-1].read_text(encoding="utf-8", errors="replace")
    ck("结果里有第一节(更新到位)", "更新到位" in t, True)
    ck("结果里有第二节(成果文档)", "成果文档在哪" in t, True)
    ck("结果里有第三节(为什么没采到)", "为什么没采到" in t, True)
    ck("密钥已打码", "50171bf3e16dc3d763f08a2adb6d41a7009b3abca0f09491" not in t, True)
    # 清理测试产生的文件
    for f in outfiles:
        try:
            f.unlink()
        except Exception:
            pass

shutil.rmtree(tmp, ignore_errors=True)
print()
print("=" * 84)
if FAIL:
    print("★ 失败 %d 项:" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("✓ 通过 %d 项: 同事解压即可用 —— 文件齐、口径对、引擎能跑、界面能起、检查能用"
      % len(PASS))
