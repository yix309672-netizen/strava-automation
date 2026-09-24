# -*- coding: utf-8 -*-
"""在一个窗口里故意多开几个标签页, 给后面的采集制造"多余标签"。

为什么: 新开的窗口本来就只有 1 个页面, 跑采集时"关掉 0 个"看不出效果。
先手动塞几个进去, 才能真正验证 close_extra_pages 有没有干活。

用法: python _试跑_塞标签.py <seq>
"""
import json
import sys
import time
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

API = "http://127.0.0.1:54345"
SEQ = sys.argv[1] if len(sys.argv) > 1 else "5"


def post(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# 找到 seq 对应的窗口 id
lst = (post("/browser/list", {"page": 0, "pageSize": 200}).get("data") or {}).get("list") or []
win = None
for w in lst:
    if str(w.get("seq")) == str(SEQ):
        win = w
        break
if win is None:
    print(f"★ 找不到 seq={SEQ} 的窗口")
    sys.exit(1)
print(f"窗口 seq={SEQ} id={win.get('id')} name={win.get('name')!r}")

j = post("/browser/open", {"id": win["id"]})
ws = ((j.get("data") or {}).get("ws"))
print("打开结果 success =", j.get("success"), " ws =", str(ws)[:60])
if not ws:
    print("★ 没拿到 ws:", json.dumps(j, ensure_ascii=False)[:200])
    sys.exit(1)

from playwright.sync_api import sync_playwright

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(ws)
    ctx = b.contexts[0]
    print("现在有", len(ctx.pages), "个页面:")
    for i, pg in enumerate(ctx.pages):
        try:
            print(f"   [{i}] {str(pg.url)[:70]}")
        except Exception as e:
            print(f"   [{i}] (读不到 url: {e})")
    # 故意塞几个
    added = 0
    for u in ("https://www.strava.com/dashboard",
              "https://www.strava.com/athletes/1",
              "about:blank"):
        try:
            pg = ctx.new_page()
            if u != "about:blank":
                try:
                    pg.goto(u, timeout=20000, wait_until="domcontentloaded")
                except Exception:
                    pass
            added += 1
        except Exception as e:
            print("   加标签失败:", str(e)[:60])
    time.sleep(2)
    print(f"加了 {added} 个, 现在共 {len(ctx.pages)} 个页面")
    for i, pg in enumerate(ctx.pages):
        try:
            print(f"   [{i}] {str(pg.url)[:70]}")
        except Exception:
            pass
    # ★ 只断开 CDP, 不关浏览器 —— 让这些多余标签留在那儿给采集去清
print()
print("已断开 CDP; 浏览器保持打开, 多余标签留着。")
