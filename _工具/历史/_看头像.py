# -*- coding: utf-8 -*-
r"""看指定账号现在的头像状态（确认 48 补齐了没 / 50、52 是否还没头像）"""
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

SEQS = [a for a in sys.argv[1:] if a.strip()] or ["48", "50", "52"]
print("=" * 76)
print("  %-5s %-7s %-9s %-20s %-20s %s"
      % ("编号", "登录", "有头像", "真实名字", "所在地", "活动数"))
print("  " + "-" * 72)
need = []
for seq in SEQS:
    prof = A.ads_find(profile_no=str(seq))
    if not prof:
        print("  %-5s ★ 找不到环境" % seq)
        continue
    uid = prof.get("user_id")
    try:
        ws = A.ads_open(uid)
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            lg = A.is_logged_in(page)
            A.goto_retry(page, "https://www.strava.com/settings/profile")
            A.accept_cookies(page, timeout=3)
            av = A.has_custom_avatar(page)
            info = A.read_settings_info(page)
            try:
                acts = A.profile_activity_count(page)
            except Exception:
                acts = -1
        print("  %-5s %-7s %-9s %-20s %-20s %s"
              % (seq, "是" if lg else "否", "是" if av else "★ 无",
                 (info.get("name") or "")[:18],
                 (info.get("location") or "")[:18], acts))
        if not av:
            need.append(seq)
    except Exception as e:
        print("  %-5s 异常: %s" % (seq, str(e)[:60]))
    finally:
        try:
            A.ads_close(uid)
        except Exception:
            pass

print()
if need:
    print("  ★ 还需要补齐资料的账号: %s" % ", ".join(need))
else:
    print("  OK 查的这几个都已有头像")
