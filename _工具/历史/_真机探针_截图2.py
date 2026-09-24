# -*- coding: utf-8 -*-
"""探针 v5: 复现"热力图卡住"并对比三种抓图方式(每级都测)
用法: python -X utf8 _真机探针_截图2.py 3 New York
"""
import base64
import importlib.util
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

WS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sa", WS / "主脚本" / "strava_ads.py")
sa = importlib.util.module_from_spec(spec)
sys.modules["sa"] = sa
spec.loader.exec_module(sa)

SEQ = sys.argv[1] if len(sys.argv) > 1 else "3"
REGION = sys.argv[2] if len(sys.argv) > 2 else "New York"
LOGP = WS / "_真机探针_截图2.log"


def out(m=""):
    print(m, flush=True)
    try:
        with open(LOGP, "a", encoding="utf-8") as f:
            f.write(str(m) + "\n")
    except Exception:
        pass


def t_playwright(page, ms):
    t0 = time.time()
    try:
        r = page.screenshot(timeout=ms)
        return f"{r and len(r)/1024:6.0f}KB", (time.time() - t0) * 1000, True
    except Exception as e:
        return str(e)[:22], (time.time() - t0) * 1000, False


def t_cdp(ctx, page):
    t0 = time.time()
    try:
        s = ctx.new_cdp_session(page)
        r = s.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70, "fromSurface": True})
        d = base64.b64decode(r["data"])
        return f"{len(d)/1024:6.0f}KB", (time.time() - t0) * 1000, True
    except Exception as e:
        return str(e)[:22], (time.time() - t0) * 1000, False


def main():
    prof = sa.ads_find(profile_no=str(SEQ))
    uid = prof["user_id"]
    ws = sa.ads_open(uid)
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            sa.goto_retry(page, "https://www.strava.com/maps/global-heatmap/segments?sport=All&style=standard&terrain=false")
            sa.accept_cookies(page, timeout=3)
            time.sleep(6)
            for _t in range(3):
                try:
                    btn = page.get_by_role("button", name=sa.re.compile(r"See the heat", sa.re.I))
                    if btn.count() and btn.first.is_visible():
                        btn.first.click()
                        time.sleep(6)
                        break
                except Exception:
                    pass
                time.sleep(1)
            box = page.locator("input[placeholder*='Search for a location']").first
            box.click()
            time.sleep(1)
            for ch in REGION:
                page.keyboard.type(ch, delay=80)
            time.sleep(3)
            for t in (REGION, REGION.split(",")[0]):
                try:
                    loc = page.get_by_text(t, exact=True).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        break
                except Exception:
                    continue
            sa.sleep_or_stop(8)
            for _try in range(3):
                btn = page.get_by_role("button", name=sa.re.compile(r"^Segments$", sa.re.I))
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    sa.sleep_or_stop(3)
                    d = page.get_by_role("button", name=sa.re.compile(r"^Done$", sa.re.I))
                    if d.count() and d.first.is_visible():
                        d.first.click()
                    break
                time.sleep(2)
            try:
                hb = page.get_by_role("button", name=sa.re.compile(r"^Heatmaps?", sa.re.I))
                if hb.count() and hb.first.is_visible():
                    hb.first.click()
            except Exception:
                pass
            sa.sleep_or_stop(3)
            out("级 | 引擎真实find_markers(12s/3次) | PW 45s | CDP jpeg | 引擎口径标记数")
            page.mouse.move(700, 400)
            for lv in range(1, 9):
                page.mouse.wheel(0, -500)
                time.sleep(2.5)                      # 引擎现在的节奏
                t0 = time.time()
                mk = sa.find_markers(page)
                dt0 = (time.time() - t0) * 1000
                info1 = "None(全失败)" if mk is None else f"{len(mk)}个"
                sz2, dt2, ok2 = t_playwright(page, 45000)
                sz3, dt3, ok3 = t_cdp(ctx, page)
                out(f"{lv:>2} | {info1:<24} {dt0:7.0f}ms | {'OK' if ok2 else '超时'} {dt2:6.0f}ms {sz2} "
                    f"| {'OK' if ok3 else '失败'} {dt3:6.0f}ms {sz3}")
            out("")
            out("说明: 若某一级 12s 全失败而 45s/CDP 成功 -> 证明是'页面间歇性卡住', 修法=加长超时+CDP兜底")
    finally:
        try:
            sa.ads_close(uid)
            out("已关闭该环境")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
