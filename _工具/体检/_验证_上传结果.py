# -*- coding: utf-8 -*-
"""验证: 上传上去的活动, 标题和类型到底对不对(只读, 不改任何东西)。

用法: python _验证_上传结果.py [窗口号, 默认 87]
"""
import importlib.util, json, os, re, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

WS = Path(__file__).resolve().parents[2]
WIN = sys.argv[1] if len(sys.argv) > 1 else "87"

eng = WS / "主脚本" / "strava_ads.py"
os.chdir(str(eng.parent))
sys.path.insert(0, str(eng.parent))
spec = importlib.util.spec_from_file_location("strava_ads", eng)
SA = importlib.util.module_from_spec(spec)
sys.modules["strava_ads"] = SA
spec.loader.exec_module(SA)

from playwright.sync_api import sync_playwright

# 训练日志每一行都带 data-activity-type / 运动图标, 用它读类型最稳
JS = r"""() => {
  const t = document.body.innerText || '';
  const cnt = {};
  for (const w of ['Morning Ride','Morning Run','Afternoon','Evening','Lunch',
                   'Workout','Ride','Run','骑行','跑步']) {
    const m = t.match(new RegExp(w, 'g'));
    if (m) cnt[w] = m.length;
  }
  const types = {};
  document.querySelectorAll('[data-activity-type]').forEach(e => {
    const k = e.getAttribute('data-activity-type');
    types[k] = (types[k] || 0) + 1;
  });
  const titles = [...document.querySelectorAll('a')].map(a => (a.innerText||'').trim())
    .filter(x => /Morning|Afternoon|Evening|Lunch|Workout|Ride|Run/.test(x)).slice(0, 30);
  return {url: location.href, cnt: cnt, types: types, titles: titles,
          acts: (t.match(/Activities\s*\|?\s*([\d,]+)/)||[])[1] || '',
          head: t.replace(/\s+/g,' ').slice(0, 500)};
}"""

prof = SA.ads_find(profile_no=WIN)
if not prof:
    raise SystemExit(f"没有 {WIN} 号环境")
uid = prof["user_id"]
print(f"环境 {WIN} -> {uid} ({prof.get('name')})")
ws = (prof.get("ws") or {}).get("puppeteer") or SA.ads_open(uid)

try:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(ws)
        ctx = b.contexts[0]
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        SA.close_extra_pages(pg, "probe")
        SA.goto_retry(pg, "https://www.strava.com/athlete/training")
        time.sleep(6)
        d = pg.evaluate(JS)
        if not d["titles"]:
            SA.goto_retry(pg, "https://www.strava.com/dashboard")
            time.sleep(5)
            d2 = pg.evaluate(JS)
            for k in ("titles", "cnt", "types", "acts", "url"):
                d[k] = d2[k]
        print(json.dumps(d, ensure_ascii=False, indent=1)[:3000])
finally:
    try:
        SA.ads_close(uid)
        print(f"已关闭 {WIN}")
    except Exception:
        pass
