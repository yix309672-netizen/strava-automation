# -*- coding: utf-8 -*-
"""真机验证: 在真实的 Strava 上传页上跑引擎的 set_act_title, 读回结果。

单元测试用的是假页面, 只能证明"代码按预期调用"。这一步才是真章:
把真页面打开、真塞 3 个文件、调【引擎自己的】 set_act_title,
再把页面上的标题/类型读回来比对。

★ 绝不点"保存并查看": 只是让卡片显示出来, 看完就关标签, 不会产生任何活动。
★ 需要有一个已打开且已登录 Strava 的 AdsPower 环境。
"""
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
GPX_DIR = Path(r"C:\Users\1\Desktop\芝加哥运动")
TITLE, SPORT = "Morning Run", "Run"
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
API = str(CFG.get("adspower_api") or "http://127.0.0.1:50325")
KEY = str(CFG.get("adspower_key") or "")


def api(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + KEY})
    return json.loads(urllib.request.urlopen(req, timeout=12).read().decode("utf-8"))


lst = ((api("/api/v1/browser/local-active").get("data") or {}).get("list")) or []
if not lst:
    print("★ 没有已打开的 AdsPower 环境 —— 先从界面开一个号, 再跑本脚本")
    sys.exit(2)
ws = (lst[0].get("ws") or {}).get("puppeteer") or ""
print("环境:", lst[0]["user_id"])

spec = importlib.util.spec_from_file_location("_live_ads", ROOT / "主脚本" / "strava_ads.py")
m = importlib.util.module_from_spec(spec)
sys.modules["_live_ads"] = m
spec.loader.exec_module(m)

pick = sorted(GPX_DIR.glob("*.gpx"),
              key=lambda p: tuple(int(x) for x in re.search(r"(\d+)\.(\d+)", p.name).groups()))[-5:]
print("素材:", [p.name for p in pick])

from playwright.sync_api import sync_playwright

READ = r"""
() => ({
  titles: Array.from(document.querySelectorAll("form.good input[name=name]")).map(i => i.value),
  sports: Array.from(document.querySelectorAll('.drop-down-menu.sport-type .selection'))
                .map(e => (e.textContent || '').trim()),
})
"""

ok_all = True
cases = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(ws)
    ctx = b.contexts[0] if b.contexts else b.new_context()
    pg = ctx.new_page()
    try:
        pg.goto("https://www.strava.com/upload/select", wait_until="domcontentloaded",
                timeout=60000)
        pg.wait_for_timeout(3500)
        fb = pg.locator("input[name='files[]']").first
        if fb.count() == 0:
            fb = pg.locator("input[type=file]").first
        fb.set_input_files([str(x) for x in pick])
        pg.wait_for_timeout(7000)

        before = pg.evaluate(READ)
        limit = pg.evaluate(
            "() => /exceeded the maximum number of uploads/i.test(document.body.innerText||'')")
        if limit:
            print("\n★ 这个号被 Strava 限流了:")
            print("   'You've exceeded the maximum number of uploads. Please try again later.'")
            print("   页面根本不渲染可编辑卡片, 所以现在验不了。")
            print("   —— 这是【短时限流】, 不是产品问题; 等一会儿或换一个号再跑。")
            print("   (注意: 别为了验证反复塞文件, 那正是触发限流的原因。)")
            try:
                pg.close()
            except Exception:
                pass
            sys.exit(3)

        print("\n塞完文件、还没动之前 (Strava 自动填的):")
        print("  标题:", before["titles"])
        print("  类型:", before["sports"])
        cases.append(("改动前标题确实不是 Morning Run",
                      any(t != TITLE for t in before["titles"]),
                      f"{before['titles']}"))

        print("\n调用引擎的 set_act_title(page, %d) ..." % len(pick))
        n = m.set_act_title(pg, len(pick))
        pg.wait_for_timeout(1500)
        after = pg.evaluate(READ)
        print("  返回:", n)
        print("  改后标题:", after["titles"])
        print("  改后类型:", after["sports"])

        cases.append(("① 页面上的标题全变成 Morning Run",
                      after["titles"] and all(t == TITLE for t in after["titles"]),
                      f"{after['titles']}"))
        cases.append(("② 页面上的类型全变成 Run",
                      after["sports"] and all(s == SPORT for s in after["sports"]),
                      f"{after['sports']}"))
        cases.append(("③ 每一张卡片都改了(不是只改第一张)",
                      n == len(before["titles"]) and n >= 1,
                      f"改了 {n} 张, 页面上有 {len(before['titles'])} 张"))
        cases.append(("④ 没点保存, 页面还停在上传页",
                      "upload" in (pg.url or ""), pg.url[-40:]))
    finally:
        try:
            pg.close()
            print("\n(验证标签已关闭, 没有提交任何活动)")
        except Exception:
            pass

print("=" * 74)
for name_, ok, detail in cases:
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name_:34s} {detail}")
print()
print("★★★ 真页面上确实改成了 Morning Run / Run ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
