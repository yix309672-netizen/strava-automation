# -*- coding: utf-8 -*-
r"""把指定账号登出 Strava —— 为了复现"自动登录"场景来验证修复①

为什么要登出: result["login"] 那个 bug 只在
    "打开时是登出状态 -> 自动谷歌登录成功"
这条路上才触发。52 号上次已经登进去了, 不登出就复现不了。
"""
import os
import sys
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.chdir(str(WS / "主脚本"))
sys.path.insert(0, str(WS / "主脚本"))
sys.path.insert(0, str(WS))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import strava_ads as A                            # noqa: E402
from playwright.sync_api import sync_playwright   # noqa: E402

seq = (sys.argv[1] if len(sys.argv) > 1 else "52").strip()
prof = A.ads_find(profile_no=seq)
if not prof:
    print("找不到环境", seq)
    sys.exit(1)
uid = prof.get("user_id")
ws = A.ads_open(uid)
try:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(ws)
        ctx = b.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("登出前 登录状态:", A.is_logged_in(page))
        A.goto_retry(page, "https://www.strava.com/logout")
        page.wait_for_timeout(4000)
        A.goto_retry(page, "https://www.strava.com/dashboard")
        page.wait_for_timeout(3000)
        after = A.is_logged_in(page)
        print("登出后 登录状态:", after, " <- 期望 False")
        print("当前 URL:", (page.url or "")[:70])
finally:
    try:
        A.ads_close(uid)
    except Exception:
        pass
print("完成" if not after else "★ 没登出成功")
