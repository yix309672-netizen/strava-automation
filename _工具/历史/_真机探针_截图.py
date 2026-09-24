# -*- coding: utf-8 -*-
"""真机探针 v4: 只测"截图到底要多久/哪种截法快"
用法: python -X utf8 _真机探针_截图.py 3 New York 6
"""
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
LEVEL = int(sys.argv[3]) if len(sys.argv) > 3 else 6
LOGP = WS / "_真机探针_截图.log"


def out(m=""):
    print(m, flush=True)
    try:
        with open(LOGP, "a", encoding="utf-8") as f:
            f.write(str(m) + "\n")
    except Exception:
        pass


def timed(label, fn, tries=2):
    for i in range(tries):
        t0 = time.time()
        try:
            r = fn()
            dt = time.time() - t0
            size = len(r) if isinstance(r, (bytes, bytearray)) else -1
            out(f"  {label:<46} 成功 {dt*1000:7.0f} ms   {size/1024:8.1f} KB")
            return dt
        except Exception as e:
            dt = time.time() - t0
            out(f"  {label:<46} 失败 {dt*1000:7.0f} ms   {str(e)[:60]}")
    return None


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
            page.mouse.move(700, 400)
            for i in range(LEVEL):
                page.mouse.wheel(0, -500)
                time.sleep(2.0)
            out(f"=== 已放大 {LEVEL} 级, 开始测各种截图方式 ===")
            out("")
            out("  [A] 默认 PNG, 各种超时")
            timed("png default timeout=12000 (引擎现在的设置)", lambda: page.screenshot(timeout=12000), tries=1)
            timed("png timeout=30000", lambda: page.screenshot(timeout=30000), tries=1)
            timed("png timeout=60000", lambda: page.screenshot(timeout=60000), tries=1)
            out("")
            out("  [B] 关动画 / 类型优化")
            timed("png animations=disabled timeout=60000",
                  lambda: page.screenshot(timeout=60000, animations="disabled"), tries=1)
            timed("jpeg quality=60 timeout=60000",
                  lambda: page.screenshot(type="jpeg", quality=60, timeout=60000), tries=1)
            timed("jpeg q60 animations=disabled timeout=60000",
                  lambda: page.screenshot(type="jpeg", quality=60, animations="disabled", timeout=60000), tries=1)
            out("")
            out("  [C] 绕过 Playwright 等待: CDP Page.captureScreenshot")
            try:
                cdp = ctx.new_cdp_session(page)
                t0 = time.time()
                r = cdp.send("Page.captureScreenshot", {"format": "png"})
                import base64
                data = base64.b64decode(r["data"])
                out(f"  {'CDP captureScreenshot png':<46} 成功 {(time.time()-t0)*1000:7.0f} ms   {len(data)/1024:8.1f} KB")
                t0 = time.time()
                r = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 60})
                data = base64.b64decode(r["data"])
                out(f"  {'CDP captureScreenshot jpeg q60':<46} 成功 {(time.time()-t0)*1000:7.0f} ms   {len(data)/1024:8.1f} KB")
            except Exception as e:
                out(f"  CDP 截图异常: {str(e)[:100]}")
            out("")
            out("  [D] 截图等待的到底是什么: 直接看页面状态")
            try:
                st = page.evaluate("""() => ({
                    ready: document.readyState,
                    fonts: document.fonts ? document.fonts.status : 'n/a',
                    hidden: document.hidden,
                    vis: document.visibilityState,
                    anim: (document.getAnimations ? document.getAnimations().length : -1),
                    size: [window.innerWidth, window.innerHeight]
                })""")
                out(f"      readyState={st['ready']} fonts={st['fonts']} hidden={st['hidden']} "
                    f"visibility={st['vis']} 动画数={st['anim']} 视口={st['size']}")
            except Exception as e:
                out(f"      读页面状态失败: {str(e)[:80]}")
    finally:
        try:
            sa.ads_close(uid)
            out("已关闭该环境")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
