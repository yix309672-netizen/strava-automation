# -*- coding: utf-8 -*-
r"""真机验证: 用比特派的一个号, 跑【引擎真正的 check_athlete】, 看"近期活动"判定。

为什么这么测:
    上一版只用假页面验过判定逻辑。这一步是拿真号 + 真资料页 + 真日期跑 ——
    能验到假页面永远验不到的两件事:
        ① 那段 JS 在真页面上到底读不读得到 <time datetime>
        ② 读到的日期是不是真的能对上"这个人最近有没有活动"

样本用【已采集的链接】: 它们是老口径(只看粉丝/位置)采下来的,
现在拿新口径重判一遍, 一眼就能看出这个筛选到底会筛掉多少人。

★ 只读: 开一个比特窗口 -> 看几个公开资料页 -> 关标签 -> 关窗口。
  不采集、不上传、不提交任何东西。
"""
import importlib.util
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
API = str(CFG.get("bitbrowser_api") or "http://127.0.0.1:54345")
N = 6                                   # 只看 6 个, 别去招惹风控
# ★ 命令行可以临时改窗口天数, 用来演示"淘汰"那一半:
#     python _验证_近期活动_真机.py 7     # 只留最近 7 天有活动的
#   默认 60 = 正式口径。
RECENT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
import requests

# 上次用的是 seq=24; 这次换一个(用户要求"换一个号")
WANT = ["2", "15", "17", "18", "19", "22", "23"]

r = requests.post(f"{API}/browser/list", json={"page": 0, "pageSize": 100},
                  timeout=20).json()
items = (r.get("data") or {}).get("list") or []
pick = None
for want in WANT:
    for it in items:
        if str(it.get("seq") or "").lstrip("_") == want:
            pick = it
            break
    if pick:
        break
if not pick:
    print("★ 没找到可用窗口")
    sys.exit(2)
print(f"用窗口: seq={pick.get('seq')} name={pick.get('name')}")

# 样本: 从最新的采集成果里取几条(老口径采下来的)
urls = []
for ln in (ROOT / "数据" / "链接-20260921.txt").read_text(encoding="utf-8").splitlines():
    ln = ln.strip()
    if ln.startswith("https://www.strava.com/athletes/"):
        urls.append(ln)
    if len(urls) >= N:
        break
print(f"样本 {len(urls)} 个(老口径采下来的):")
for u in urls:
    print("   ", u)

spec = importlib.util.spec_from_file_location("_live_bit", ROOT / "主脚本" / "strava_bit.py")
m = importlib.util.module_from_spec(spec)
sys.modules["_live_bit"] = m
spec.loader.exec_module(m)

op = requests.post(f"{API}/browser/open", json={"id": pick["id"], "loadExtensions": True},
                   timeout=60).json()
if not op.get("success"):
    print("★ 打开失败:", op.get("msg"))
    sys.exit(2)
ws = (op.get("data") or {}).get("ws") or ""
print("ws:", ws[:56], "...")

from playwright.sync_api import sync_playwright

# 和 check_athlete 里那段 JS 一模一样, 单独跑一次只为把"读到了什么"打出来
READ = r"""
() => {
  var ds = [];
  var tns = document.querySelectorAll('time[datetime]');
  for (var q = 0; q < tns.length; q++) {
      var dv = tns[q].getAttribute('datetime');
      if (dv) ds.push(dv);
  }
  var t = document.body.innerText || '';
  var m4 = t.match(/Last\s+4\s+Weeks[\s\S]{0,60}?([\d,]+)\s+Total\s+Activit/i)
        || t.match(/\u6700\u8fd1\s*4\s*\u5468[\s\S]{0,30}?([\d,]+)\s*(?:\u6b21)?\u6d3b\u52a8/);
  return {dates: ds.slice(0, 6), n_dates: ds.length,
          four_week: m4 ? parseInt(m4[1].replace(/,/g, '')) : -1,
          noAccess: /don't have access|\u6ca1\u6709\u8bbf\u95ee\u6743\u9650/i.test(t)};
}
"""

ok_all = True
rows = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(ws)
    ctx = b.contexts[0] if b.contexts else b.new_context()
    pg = ctx.new_page()
    try:
        for u in urls:
            aid = u.rstrip("/").split("/")[-1]
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(4500)
                raw = pg.evaluate(READ)
                ok, why = m.check_athlete(pg, aid, 200, geo_filter=False,
                                          us_only=False, recent_days=RECENT)
                rows.append((aid, raw, ok, why))
            except Exception as e:
                rows.append((aid, {"err": str(e)[:60]}, None, "异常"))
    finally:
        try:
            pg.close()
        except Exception:
            pass
        try:
            requests.post(f"{API}/browser/close", json={"id": pick["id"]}, timeout=30)
            print("(标签已关, 窗口已关)")
        except Exception:
            pass

print()
print("=" * 96)
print(f"{'编号':>12}  {'页面读到的时间':<34} {'4周内':>5}  {'判定':<6} 说明")
print("-" * 96)
for aid, raw, ok, why in rows:
    if raw.get("err"):
        print(f"{aid:>12}  读页面异常: {raw['err']}")
        continue
    ds = raw.get("dates") or []
    dtxt = (ds[0][:19].replace("T", " ") + ("…" if len(ds) > 1 else "")) if ds else "(页面没有 time 标签)"
    mark = "保留" if ok else "淘汰"
    print(f"{aid:>12}  {dtxt:<34} {raw.get('four_week', -1):>5}  {mark:<6} {why}")
    if raw.get("noAccess"):
        print(f"{'':>12}  ★ 页面显示无访问权限")
    if ok is None:
        ok_all = False

keep = sum(1 for _, r, o, _ in rows if o is True and not r.get("err"))
toss = sum(1 for _, r, o, _ in rows if o is False and not r.get("err"))
print("-" * 96)
print(f"老口径采下来的 {len(rows)} 个里: 新口径保留 {keep} 个, 淘汰 {toss} 个")
print()
print("★★★ 真页面上读得到 <time datetime>, 判定也对上了 ★★★" if ok_all
      else "★★★ 有读取异常 ★★★")
sys.exit(0 if ok_all else 1)
