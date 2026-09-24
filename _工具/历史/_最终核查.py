# -*- coding: utf-8 -*-
r"""最终整体核查 —— 一次跑完所有环节，作为验收证据

1. 全部 Python 文件语法
2. 两个引擎导入 + 中心去重客户端可用
3. 两套界面能起来 + 按钮/下拉框/配置键齐全
4. 分发包：无邮箱、无私钥、账号文件空白、必须文件齐全
5. 服务器：健康、鉴权、清单、版本
6. 自动更新：对真实 VPS 走一遍
7. 你的数据完好
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
T = Path(r"C:\Users\1\Desktop\_最终核查")
os.environ["PYTHONIOENCODING"] = "utf-8"
SERVER = "http://137.175.71.171:8000"
KEY = "g1jVQg7y_K5UOtfHUgUEg6seJ4WeKJjAUGJt7shPYvk"

ok = True
FAILS = []


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


def chk(c, label, extra=""):
    global ok
    ok &= bool(c)
    if not c:
        FAILS.append(label)
    log("  %s %-52s %s" % ("OK  " if c else "FAIL", label, extra))


log("=" * 72)
log("  1. 全部 Python 文件语法")
log("=" * 72)
FILES = ["主脚本/strava_ads.py", "主脚本/strava_bit.py",
         "界面/ADS自动化.py", "界面/比特派自动化.py",
         "claim_server.py", "claim_store.py", "claim_client.py",
         "update.py", "发布更新.py", "geo_cities.py",
         "_重做启动器.py", "部署更新端点.py", "deploy_vps.py"]
for p in FILES:
    try:
        ast.parse((WS / p).read_text(encoding="utf-8"))
        chk(True, p)
    except SyntaxError as e:
        chk(False, p, str(e)[:60])

log("")
log("=" * 72)
log("  2. 引擎导入 + 中心去重客户端（你本机布局：界面/ + 主脚本/）")
log("=" * 72)
if T.exists():
    shutil.rmtree(T, ignore_errors=True)
(T / "主脚本").mkdir(parents=True)
(T / "界面").mkdir()
shutil.copy2(WS / "claim_client.py", T / "claim_client.py")
shutil.copy2(WS / "geo_cities.py", T / "geo_cities.py")
shutil.copy2(WS / "配置" / "config.json", T / "config.json")
for n in ("strava_ads.py", "strava_bit.py"):
    shutil.copy2(WS / "主脚本" / n, T / "主脚本" / n)
for n in ("ADS自动化.py", "比特派自动化.py"):
    shutil.copy2(WS / "界面" / n, T / "界面" / n)

for eng in ("strava_ads.py", "strava_bit.py"):
    saved = list(sys.path)
    sys.path[:] = [p for p in sys.path if Path(p).resolve()
                   not in (T.resolve(), (T / "主脚本").resolve())]
    sys.path.insert(0, str(T / "主脚本"))
    os.chdir(T)
    spec = importlib.util.spec_from_file_location("f_" + eng[6:9], T / "主脚本" / eng)
    m = importlib.util.module_from_spec(spec)
    sys.modules["f_" + eng[6:9]] = m
    spec.loader.exec_module(m)
    chk(m.ClaimClient is not None, "%s：中心去重客户端可用" % eng)
    cli = m.make_claim_client(hint="PCFINAL")
    chk(cli is not None, "%s：真的连上了中心服务" % eng,
        getattr(cli, "worker", ""))
    sys.path[:] = saved

log("")
log("=" * 72)
log("  3. 两套界面能起来 + 控件齐全")
log("=" * 72)
import tkinter  # noqa
for gui, pre in (("ADS自动化.py", "ads"), ("比特派自动化.py", "bit")):
    d = T / pre
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    shutil.copy2(T / "界面" / gui, d / gui)
    shutil.copy2(WS / "配置" / "config.json", d / "config.json")
    (d / f"{pre}_accounts.json").write_text("{}", encoding="utf-8")
    (d / f"{pre}_results.json").write_text("{}", encoding="utf-8")
    sys.path.insert(0, str(d))
    os.chdir(d)
    s2 = importlib.util.spec_from_file_location("g_" + pre, d / gui)
    g = importlib.util.module_from_spec(s2)
    sys.modules["g_" + pre] = g
    s2.loader.exec_module(g)
    app = g.App()
    app.withdraw()
    end = time.time() + 1.0
    while time.time() < end:
        try:
            app.update()
        except Exception:
            break
        time.sleep(0.01)
    btns, combos = [], []

    def walk(w):
        for c in w.winfo_children():
            k = c.winfo_class()
            if k == "TButton":
                btns.append(str(c.cget("text")))
            if k == "TCombobox":
                try:
                    combos.append(list(c.cget("values")))
                except Exception:
                    pass
            walk(c)
    walk(app)
    need = ("1.连接并加载", "2.扫描状态", "刷新结果", "3.预览分配",
            "开始任务", "只采集", "停止", "关闭全部浏览器")
    miss = [b for b in need if not any(b in x for x in btns)]
    chk(not miss, "%s：8 个按钮齐全" % gui, str(miss) if miss else "")
    chk(any(len(c) == 4 for c in combos), "%s：执行内容下拉框 4 选项" % gui)
    cfg = app._cfg()
    needk = {"location", "avatar_dir", "gpx_dir", "per_batch", "daily_cap",
             "jobs", "background", "auto_close", "collect_regions",
             "min_athletes", "max_followers", "segs_per_region",
             "check_per_segment", "task_mode"}
    chk(needk <= set(cfg), "%s：_cfg() 14 键齐全" % gui,
        str(needk - set(cfg)) if needk - set(cfg) else "")
    try:
        app.destroy()
    except Exception:
        pass
    sys.path.pop(0)

log("")
log("=" * 72)
log("  4. 分发包体检")
log("=" * 72)
PKGZIP = WS / "_分发给同事.zip"
with zipfile.ZipFile(PKGZIP) as z:
    names = z.namelist()
    chk(len(names) >= 16, "文件数 %d" % len(names))
    must = ("启动.bat", "Start_BitBrowser.bat", "Start_AdsPower.bat",
            "Test_Server.bat", "更新.bat", "open_app.py", "update.py",
            "_gui_ads.py", "_gui_bit.py", "strava_ads.py", "strava_bit.py",
            "claim_client.py", "geo_cities.py", "config.json")
    miss = [n for n in must if n not in names]
    chk(not miss, "必需文件齐全", str(miss) if miss else "")
    MAIL = re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+")
    leak = []
    for n in names:
        t = z.read(n).decode("utf-8", "ignore")
        for mm in MAIL.finditer(t):
            if not any(a in mm.group(0).lower()
                       for a in ("example.com", "test.com", "localhost")):
                leak.append("%s:%s" % (n, mm.group(0)))
        if n.endswith(("accounts.json", "results.json")) and t.strip() not in ("{}", ""):
            leak.append(n + " 非空白")
    chk(not leak, "无邮箱 / 账号文件空白", str(leak[:3]) if leak else "")
    MYKEY = "50171bf3e16dc3d763f08a2adb6d41a7009b3abca0f09491"
    haskey = [n for n in names
              if MYKEY in z.read(n).decode("utf-8", "ignore")]
    chk(not haskey, "无私钥泄漏", str(haskey) if haskey else "")
    c = json.loads(z.read("config.json").decode("utf-8"))
    chk(c.get("adspower_key") == "" and c.get("claim_server"),
        "包内 config：key 为空、服务器已配",
        "server=%s" % c.get("claim_server"))

log("")
log("=" * 72)
log("  5. 服务器")
log("=" * 72)
import requests
try:
    h = requests.get(SERVER + "/health", timeout=10).json()
    chk(h.get("ok") is True, "/health 正常",
        "运动员 %s / 成果 %s" % (h.get("athletes"), h.get("collected")))
    r401 = requests.get(SERVER + "/stats", timeout=10)
    chk(r401.status_code == 401, "/stats 无 key 被拒", str(r401.status_code))
    r200 = requests.get(SERVER + "/stats", headers={"X-API-Key": KEY}, timeout=10)
    chk(r200.status_code == 200, "/stats 带 key 正常", str(r200.status_code))
    man = requests.get(SERVER + "/pkg/manifest",
                       headers={"X-API-Key": KEY}, timeout=10).json()
    chk(bool(man.get("version")) and man.get("count", 0) >= 15,
        "已发布版本可查", "%s / %s 个文件" % (man["version"], man["count"]))
except Exception as e:
    chk(False, "服务器检查", str(e)[:80])

log("")
log("=" * 72)
log("  6. 自动更新（对真实 VPS 走一遍）")
log("=" * 72)
C = T / "client"
shutil.rmtree(C, ignore_errors=True)
C.mkdir()
for f in (WS / "_分发给同事").iterdir():
    if f.is_file():
        shutil.copy2(f, C / f.name)
(C / "strava_ads.py").write_text("# 旧版\n", encoding="utf-8")
(C / "collected_users.txt").write_text("https://x/1\n", encoding="utf-8")
(C / "bit_accounts.json").write_text('{"1":{"email":"keep@x.com"}}',
                                     encoding="utf-8")
cf = json.loads((C / "config.json").read_text(encoding="utf-8"))
cf["my_note"] = "别覆盖我"
(C / "config.json").write_text(json.dumps(cf, ensure_ascii=False, indent=2),
                               encoding="utf-8")
r = subprocess.run([sys.executable, str(C / "update.py"), "--auto"],
                   cwd=str(C), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=300)
out = (r.stdout or "") + (r.stderr or "")
chk(r.returncode == 0, "update.py 退出码 0", out.strip().splitlines()[-1][:60]
    if out.strip() else "")
# ★ 原来这里断言的是"更新后的文件 == 本地 _分发给同事/ 里的文件"。
#   这个断言只在"刚刚发完版那一刻"成立: 只要本地包比线上新一版
#   (改完还没发版), 就必然不相等 -> 报 FAIL, 但其实是正常的版本落差,
#   反而把真正该验的东西盖住了。
#   真正该验的是: **客户端拿到的字节 == 服务器清单里公布的那一份**。
#   这个断言在任何状态下都成立, 而且比原来更强(逐字节比 sha256)。
pub = requests.get(SERVER + "/pkg/manifest",
                   headers={"X-API-Key": KEY}, timeout=10).json()
got = hashlib.sha256((C / "strava_ads.py").read_bytes()).hexdigest()
want = ((pub.get("files") or {}).get("strava_ads.py") or {}).get("sha256")
chk(bool(want) and got == want, "更新下来的文件 == 服务器清单 sha256",
    "…%s" % got[:12])
chk((C / "strava_ads.py").read_text(encoding="utf-8",
                                    errors="ignore").strip() != "# 旧版",
    "旧文件确实被替换掉了")
# 版本落差只提示、不计成败: 本地包比线上新是"改完还没发版"的正常状态
loc = hashlib.sha256((WS / "_分发给同事" / "strava_ads.py").read_bytes()).hexdigest()
log("  ---- 线上版本 %s；%s" % (
    pub.get("version"),
    "本地包与线上一致" if loc == want
    else "本地包比线上新一版（改动尚未发版，同事拿到的仍是旧版）"))
chk((C / "collected_users.txt").read_text(encoding="utf-8").count("x/1") == 1,
    "★ 采集成果没被动")
chk(json.loads((C / "bit_accounts.json").read_text(encoding="utf-8"))
    ["1"]["email"] == "keep@x.com", "★ 账号没被动")
c2 = json.loads((C / "config.json").read_text(encoding="utf-8"))
chk(c2.get("my_note") == "别覆盖我", "★ 同事自定义键没被动")

log("")
log("=" * 72)
log("  7. 你的数据完好")
log("=" * 72)
for p, mn in (("数据/collected_users.txt", 90000),
              ("数据/collected_seen.json", 15000),
              ("配置/ads_accounts.json", 4000),
              ("配置/bit_accounts.json", 1600)):
    f = WS / p
    chk(f.is_file() and f.stat().st_size >= mn, p,
        "%d B" % f.stat().st_size if f.is_file() else "★ 丢了")

shutil.rmtree(T, ignore_errors=True)
log("")
log("=" * 72)
if FAILS:
    log("  ★ 失败 %d 项：" % len(FAILS))
    for f in FAILS:
        log("     - " + f)
else:
    log("  ★ 最终整体核查：全部通过")
log("=" * 72)
sys.exit(0 if ok else 1)
