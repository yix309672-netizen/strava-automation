# -*- coding: utf-8 -*-
"""查: 设置页的元素为什么"不可见" —— 是弹窗遮罩, 还是根本没渲染出来?

用法: python _查_设置页为什么不可见.py [窗口号, 默认 87]
"""
import importlib.util, json, os, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

WS = Path(__file__).resolve().parents[2]
WIN = sys.argv[1] if len(sys.argv) > 1 else "87"
URL = sys.argv[2] if len(sys.argv) > 2 else "https://www.strava.com/settings/profile"

eng = WS / "主脚本" / "strava_ads.py"
os.chdir(str(eng.parent))
sys.path.insert(0, str(eng.parent))
spec = importlib.util.spec_from_file_location("strava_ads", eng)
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = SA
spec.loader.exec_module(SA)

from playwright.sync_api import sync_playwright

prof = SA.ads_find(profile_no=WIN)
if not prof:
    raise SystemExit(f"没有 {WIN} 号环境")
uid = prof["user_id"]
print(f"环境 {WIN} -> {uid} ({prof.get('name')})")
ws = (prof.get("ws") or {}).get("puppeteer") or SA.ads_open(uid)

JS = r"""() => {
  const vis = e => { if(!e) return false; const r=e.getBoundingClientRect();
    const s=getComputedStyle(e); return r.width>0 && r.height>0 && s.visibility!=='hidden'
           && s.display!=='none' && s.opacity!=='0'; };
  const rows = [...document.querySelectorAll('div.editable-setting')];
  const dlg  = [...document.querySelectorAll('[role=dialog],[class*=modal],[class*=Modal],[class*=overlay]')]
                 .filter(vis).map(e=>({tag:e.tagName,
                    cls:(e.className||'').toString().slice(0,90),
                    txt:(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,110)}));
  const btns = [...document.querySelectorAll('button,a[role=button]')].filter(vis)
                 .map(e=>(e.innerText||'').replace(/\s+/g,' ').trim()).filter(t=>t&&t.length<28);
  return {url:location.href,
    title:document.title,
    bodyLen:(document.body.innerText||'').length,
    bodyHead:(document.body.innerText||'').replace(/\s+/g,' ').trim().slice(0,220),
    athleteImg: !!document.querySelector('#athlete_image'),
    athleteImgVisible: vis(document.querySelector('#athlete_image')),
    editRows: rows.length,
    editRowsVisible: rows.filter(vis).length,
    editTexts: rows.map(r=>(r.textContent||'').replace(/\s+/g,' ').trim().slice(0,40)),
    dialogs: dlg,
    buttons: btns.slice(0,22)};
}"""

try:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(ws)
        ctx = b.contexts[0]
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        SA.close_extra_pages(pg, "probe")
        SA.goto_retry(pg, URL)
        time.sleep(4)
        d = pg.evaluate(JS)
        print(json.dumps(d, ensure_ascii=False, indent=1)[:3500])
        shot = WS / "_过程记录" / f"设置页_{WIN}.png"
        try:
            pg.screenshot(path=str(shot), full_page=False)
            print(f"\n截图: {shot}")
        except Exception as e:
            print(f"截图失败: {str(e)[:60]}")
finally:
    try:
        SA.ads_close(uid)
        print(f"已关闭 {WIN}")
    except Exception as e:
        print(f"关窗失败: {str(e)[:60]}")
