# -*- coding: utf-8 -*-
"""验证: 上传页的运动类型下拉框里到底有哪些 data-value —— 只解析, 【绝不保存】。

为什么要有这个: 引擎改类型用的是 li[data-value='Ride'], 这个值是从 Strava 的
惯例猜的, 猜错的话 38 条活动会全变成默认类型(改起来很麻烦)。
这里真开一个已登录的环境, 传 1 个骑行 TCX, 把下拉框里的选项全打出来, 然后关掉。

用法: python _验证_骑行类型可选.py [窗口号, 默认 87]
"""
import importlib.util, os, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

WS = Path(__file__).resolve().parents[2]
WIN = sys.argv[1] if len(sys.argv) > 1 else "87"
SAMPLE = WS.parent / "运动轨迹" / "洛杉矶-骑行"

eng = WS / "主脚本" / "strava_ads.py"
os.chdir(str(eng.parent))
sys.path.insert(0, str(eng.parent))
spec = importlib.util.spec_from_file_location("strava_ads", eng)
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = SA
spec.loader.exec_module(SA)

from playwright.sync_api import sync_playwright

files = sorted(p for p in SAMPLE.iterdir() if p.suffix.lower() == ".tcx")
if not files:
    raise SystemExit(f"素材目录是空的: {SAMPLE}")
title, sport = SA.sport_of(files)
print(f"素材     : {SAMPLE.name}  共 {len(files)} 个")
print(f"引擎判定 : 标题「{title}」 类型 {sport}")

prof = SA.ads_find(profile_no=WIN)
if not prof:
    raise SystemExit(f"AdsPower 里没有 {WIN} 号环境")
uid = prof["user_id"]
print(f"环境     : {WIN} -> {uid}  ({prof.get('name')})")

ws = (prof.get("ws") or {}).get("puppeteer") or SA.ads_open(uid)
try:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(ws)
        ctx = b.contexts[0]
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        SA.close_extra_pages(pg, "probe")
        SA.goto_retry(pg, "https://www.strava.com/upload/select")
        print(f"页面     : {pg.url}")
        if "login" in pg.url or "session" in pg.url:
            raise SystemExit("★ 这个环境没登录, 换一个号再试")

        pg.locator("input[name='files[]']").first.set_input_files(str(files[0]))
        print(f"已投喂   : {files[0].name}  (等待解析)")

        forms = pg.locator("form.good:visible")
        for _ in range(40):
            if forms.count() > 0:
                break
            import time as _t
            _t.sleep(0.5)
        n = forms.count()
        print(f"解析出   : {n} 张卡片")
        if n == 0:
            raise SystemExit("★ 没有解析出卡片 —— 看不到下拉框")

        f = forms.first
        print("自动标题 :", f.locator("input[name=name]").first.input_value())
        f.locator(".drop-down-menu.sport-type .selection").first.click(timeout=5000)
        import time as _t
        _t.sleep(1.0)

        opts = pg.locator(".drop-down-menu.sport-type li[data-value]")
        got = []
        for i in range(opts.count()):
            o = opts.nth(i)
            got.append((o.get_attribute("data-value"), (o.inner_text() or "").strip()))

        print(f"\n=== 下拉框里的 {len(got)} 个类型 ===")
        for v, t in got:
            mark = "  ★引擎要用的" if v == sport else ""
            print(f"  data-value={v!r:28s} 显示={t!r}{mark}")

        vals = [v for v, _ in got]
        print(f"\n判定: li[data-value='{sport}'] {'存在 ✔' if sport in vals else '★不存在 —— 要换值!'}")
        print("\n(没有点「保存并查看」, 不会产生任何活动)")
finally:
    try:
        SA.ads_close(uid)
        print(f"已关闭 {WIN}")
    except Exception as e:
        print(f"关窗失败: {str(e)[:60]}")
