# -*- coding: utf-8 -*-
"""真机探针 v3: 停在指定缩放级数, 点标记读弹窗人数 + 排行榜人数
用法:  python -X utf8 _真机探针.py 3 New York 6
"""
import importlib.util
import io
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

WS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sa", WS / "主脚本" / "strava_ads.py")
sa = importlib.util.module_from_spec(spec)
sys.modules["sa"] = sa
spec.loader.exec_module(sa)

SEQ = sys.argv[1] if len(sys.argv) > 1 else "3"
REGION = sys.argv[2] if len(sys.argv) > 2 else "New York"
LEVEL = int(sys.argv[3]) if len(sys.argv) > 3 else 6
LOGP = WS / "_真机探针.log"


def out(msg=""):
    line = str(msg)
    print(line, flush=True)
    try:
        with open(LOGP, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def shot(page, timeout=45000, tries=3):
    for i in range(tries):
        try:
            return page.screenshot(timeout=timeout)
        except Exception as e:
            out(f"      [截图失败 {i+1}/{tries}] {str(e)[:60]}")
            time.sleep(3)
    return None


def engine_markers(raw):
    """完全照抄 find_markers 的判定, 返回中心点列表"""
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    arr = np.array(im)
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (r > 200) & (g > 40) & (g < 140) & (b < 70)
    mask[:160, :] = False
    mask[:, :200] = False
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    out_ = []
    ys, xs = np.where(mask)
    for (x0, y0) in zip(xs.tolist(), ys.tolist()):
        if visited[y0, x0]:
            continue
        stack = [(x0, y0)]
        visited[y0, x0] = True
        comp = []
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((nx, ny))
        area = len(comp)
        if not (60 <= area <= 900):
            continue
        cxs = [q[0] for q in comp]
        cys = [q[1] for q in comp]
        bw = max(cxs) - min(cxs) + 1
        bh = max(cys) - min(cys) + 1
        if not bw or not bh:
            continue
        if 0.5 <= bw / bh <= 2.0 and area / (bw * bh) >= 0.35:
            out_.append((int(sum(cxs) / area), int(sum(cys) / area)))
    return out_


def main():
    out("=" * 78)
    out(f"真机探针v3 {time.strftime('%H:%M:%S')} 环境={SEQ} 地区={REGION} 停在放大 {LEVEL} 级")
    prof = sa.ads_find(profile_no=str(SEQ))
    if not prof:
        out("!! 找不到环境")
        return 2
    uid = prof["user_id"]
    ws = sa.ads_open(uid)
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            out(f"[1] 登录={sa.is_logged_in(page)} 会员={sa.is_premium(page)}")
            sa.goto_retry(page, "https://www.strava.com/maps/global-heatmap/segments?sport=All&style=standard&terrain=false")
            sa.accept_cookies(page, timeout=3)
            sa.sleep_or_stop(6)
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
            hit = False
            for t in (REGION, REGION.split(",")[0]):
                try:
                    loc = page.get_by_text(t, exact=True).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        hit = True
                        break
                except Exception:
                    continue
            out(f"[2] 搜 {REGION}: {'命中' if hit else '未命中'}")
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
            dpr = page.evaluate("() => window.devicePixelRatio") or 1
            page.mouse.move(700, 400)
            for i in range(LEVEL):
                page.mouse.wheel(0, -500)
                time.sleep(2.5)
            out(f"[3] 已放大 {LEVEL} 级, dpr={dpr}")
            raw = shot(page)
            if raw is None:
                out("!! 截图失败")
                return 1
            mk = engine_markers(raw)
            out(f"[4] 引擎口径标记 {len(mk)} 个: {mk[:10]}")

            out("")
            out("[5] 点标记 -> 弹窗人数 -> 排行榜:")
            got_seg = False
            for idx, (sx, sy) in enumerate(mk[:8], 1):
                try:
                    page.mouse.click(sx / dpr, sy / dpr)
                    sa.sleep_or_stop(2.0)
                    sid = sa.segment_from_popup(page)
                    n = sa.popup_athletes(page)
                    info = page.evaluate(r"""() => {
                        const t = document.body.innerText || '';
                        const m = t.match(/[^\n]*athletes[^\n]*/i);
                        const seg = [...document.querySelectorAll('a[href*="/segments/"]')]
                                    .map(x=>({h:x.getAttribute('href'), t:(x.innerText||'').replace(/\n/g,' ').slice(0,60)})).slice(0,2);
                        return {line: m ? m[0].slice(0,120) : '(整页没有 athletes 字样)', seg: seg};
                    }""")
                    out(f"  #{idx} ({sx},{sy}) 路段={sid!r} popup_athletes()={n}")
                    out(f"      athletes行: {info.get('line')!r}")
                    out(f"      链接: {info.get('seg')}")
                    if sid and n and n >= 5000 and not got_seg:
                        got_seg = True
                        for age in ("45_54", "55_64", "65_69"):
                            try:
                                total, rows = sa.fetch_lb_filtered(page, sid, age, max_pages=8)
                                out(f"      榜单 {age}: totalCount={total} 抓到={len(rows)}")
                                if rows[:2]:
                                    out(f"         样例 {rows[:2]}")
                            except Exception as e:
                                out(f"      榜单 {age} 异常: {str(e)[:70]}")
                    page.keyboard.press("Escape")
                    time.sleep(1.2)
                except Exception as e:
                    out(f"  #{idx} 异常: {str(e)[:90]}")
            out("")
            out("真机探针v3 结束")
    except Exception as e:
        out(f"!! 探针异常: {type(e).__name__}: {str(e)[:200]}")
        return 1
    finally:
        try:
            sa.ads_close(uid)
            out("已关闭该环境")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
