# -*- coding: utf-8 -*-
"""让分发包的 config.json 带上【管理员统一口径】。

背景(真实症状):
   用户把 collect_age_groups 改成 ['55_64','65_69']、min_athletes 改成 2000、
   gender 改成 male —— 但【分发包的 config.json 没跟着改】:
        collect_age_groups = None
        collect_gender     = None
        min_athletes       = 5000
   于是同事装完 = 旧口径。这正是"同事还是老版本"的一个根因。

★ 但要分清两类键(这是关键):
   【统一口径】—— 所有机器必须一致, 由管理员下发:
       collect_age_groups / collect_gender / collect_date_range /
       min_athletes / min_athletes_floor / max_followers /
       us_only / us_only_strict / geo_center / jobs /
       collect_target_per_account / scan_close / 速率与闸门
   【同事自己选】—— 界面上有下拉框, 尊重他们的选择, 不下发:
       collect_regions(采集地区)  ← 上一轮专门从强制名单里摘掉的

   所以: 前者【从管理员配置同步过去】, 后者【保持分发包原样】。
"""
import json
import pathlib

ROOT = pathlib.Path(".")
ADMIN = ROOT / "配置" / "config.json"
DIST = ROOT / "_分发给同事" / "config.json"

# 管理员统一下发的口径(不含 collect_regions —— 那是同事在下拉框里选的)
POLICY = [
    "collect_age_groups", "collect_gender", "collect_date_range",
    "min_athletes", "min_athletes_floor", "max_followers",
    "us_only", "us_only_strict", "geo_center", "jobs",
    "collect_target_per_account", "target_floor", "scan_close",
    "collect_auto_regions", "segs_per_region",
    "geo_filter", "geo_band_min_km", "geo_band_max_km",
    "ny_exempt_max_km", "lb_max_pages",
    "rate_nav_sec", "rate_api_sec", "rate_act_sec",
    "collect_max_minutes", "stall_exit_sec",
    "pan_rounds", "enough_segments",
    "claim_server", "claim_key",
    # ★ 不含 collect_regions: 同事在界面「采集地区」下拉里自己选
    # ★ 不含 ui_theme: 同事自己决定要不要开主题
    # ★ 不含 adspower_key / adspower_api / 目录 / windows: 同事本地环境
]

a = json.loads(ADMIN.read_text(encoding="utf-8"))
d = json.loads(DIST.read_text(encoding="utf-8"))

print("=" * 76)
print("把管理员口径同步到分发包 config.json")
print("=" * 76)
print()
print("  %-28s %-30s -> %s" % ("键", "分发包(改前)", "改成"))
print("  " + "-" * 72)
changed = []
for k in POLICY:
    if k not in a:
        continue
    old = d.get(k)
    new = a[k]
    if old != new:
        # None 表示"分发包里没这个键", 也该补上
        d[k] = new
        changed.append(k)
        print("  %-28s %-30r %r" % (k, old, new))
if not changed:
    print("  (全都一致, 无需改)")

# 空值补默认: 这几项如果是 None, 同事会用引擎默认, 可能不是你要的
FILL = {"collect_age_groups": ["55_64", "65_69"],
        "collect_gender": "male",
        "min_athletes_floor": 2000}
for k, v in FILL.items():
    if d.get(k) is None:
        d[k] = v
        changed.append(k)
        print("  %-28s %-30r %r  (补默认)" % (k, None, v))

DIST.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
print()
print("  改动 %d 项, 已写回 %s" % (len(changed), DIST))
print()
print("=" * 76)
print("改完后的分发包口径")
print("=" * 76)
for k in ("collect_regions", "collect_age_groups", "collect_gender",
          "collect_date_range", "min_athletes", "min_athletes_floor",
          "us_only", "us_only_strict", "geo_center", "jobs",
          "collect_target_per_account", "location", "scan_close",
          "adspower_key"):
    v = d.get(k)
    if k == "adspower_key":
        v = "(空)" if not v else "★ 有值!"
    print("  %-28s = %r" % (k, v))
print()
print("  ★ collect_regions 故意保持分发包原样 —— 同事在界面下拉框自己选")
print("  ★ adspower_key 必须为空 —— 每台机器填自己的")
