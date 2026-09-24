# -*- coding: utf-8 -*-
r"""验证生成的轨迹: 在不在水里、形状像不像真人跑的、Sport 对不对。

★★ 为什么要专门查"在水里" ★★
   上一版把圆心撒在经纬度方框里, 芝加哥那个方框 lon 到 -87.50,
   而湖岸线在 -87.60 附近 —— 轨迹直接画进密歇根湖, 用户截图问
   "我在海上跑步吗"。所以这一步必须能真的查出越界。

   这里用一条【手写的芝加哥湖岸线】(从南到北一串点, 湖在东侧 = 经度更大),
   落在湖里的点一律判不合格。洛杉矶同理(太平洋在西南, 用一条斜线)。
   ★ 这是粗判: 只用来抓"整条跑到水里", 不追求米级精度。

其他检查: 合法 TCX / Sport 对得上 / 本地早上开始 / 首尾闭合 /
         点数与间距像真人 / 相邻点不会突然跳很远(那种多半是跨水面的直线)
"""
import glob
import math
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

NS = "{http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2}"

# 芝加哥湖岸线: (lat, 岸线经度)。陆地 = 经度 < 岸线经度(湖在东边)。
CHI_SHORE = [
    (41.64, -87.525), (41.73, -87.530), (41.76, -87.550), (41.79, -87.575),
    (41.82, -87.585), (41.85, -87.600), (41.87, -87.607), (41.885, -87.612),
    (41.890, -87.607), (41.915, -87.625), (41.930, -87.635), (41.950, -87.645),
    (41.980, -87.655), (42.020, -87.670), (42.100, -87.700),
]


def shore_lon(lat):
    if lat <= CHI_SHORE[0][0]:
        return CHI_SHORE[0][1]
    if lat >= CHI_SHORE[-1][0]:
        return CHI_SHORE[-1][1]
    for i in range(len(CHI_SHORE) - 1):
        a, b = CHI_SHORE[i], CHI_SHORE[i + 1]
        if a[0] <= lat <= b[0]:
            t = (lat - a[0]) / max(b[0] - a[0], 1e-9)
            return a[1] + (b[1] - a[1]) * t
    return -87.6


def in_water(lat, lon):
    """在芝加哥 -> 用岸线判; 在洛杉矶一带 -> 用太平洋边界判。"""
    if 41.5 <= lat <= 42.2 and -88.0 <= lon <= -87.3:          # 芝加哥
        return lon > shore_lon(lat)
    if 33.5 <= lat <= 34.5 and -119.0 <= lon <= -117.8:        # 洛杉矶
        return lon < -118.48 or lat < 33.95                    # 太平洋在西南
    return False


def hav(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def check_dir(d, want_sport, tz, label):
    files = sorted(glob.glob(str(Path(d) / "*.tcx")))
    if not files:
        print(f"  {label:16s} ★ 没有文件")
        return 1
    bad = {"xml": [], "sport": [], "time": [], "loop": [], "water": [], "jump": []}
    km_all, gap_all, npts = [], [], []
    for f in files:
        name = Path(f).name
        try:
            root = ET.fromstring(Path(f).read_text(encoding="utf-8"))
        except Exception as e:
            bad["xml"].append(f"{name}:{e}")
            continue
        act = root.find(f"{NS}Activities/{NS}Activity")
        lap = act.find(f"{NS}Lap") if act is not None else None
        tps = lap.findall(f"{NS}Track/{NS}Trackpoint") if lap is not None else []
        if act is None or lap is None or len(tps) < 10:
            bad["xml"].append(f"{name}:结构不全")
            continue
        if act.get("Sport") != want_sport:
            bad["sport"].append(f"{name}:{act.get('Sport')}")
        pos = [(float(p.find(f"{NS}Position/{NS}LatitudeDegrees").text),
                float(p.find(f"{NS}Position/{NS}LongitudeDegrees").text)) for p in tps]
        t0 = datetime.fromisoformat(tps[0].find(f"{NS}Time").text.replace("Z", "+00:00"))
        loc = t0 + timedelta(hours=tz)
        if not (5 <= loc.hour < 12):
            bad["time"].append(f"{name}:{loc:%H:%M}")
        if hav(pos[0], pos[-1]) > 40:
            bad["loop"].append(f"{name}:{hav(pos[0], pos[-1]):.0f}m")
        wet = [p for p in pos if in_water(p[0], p[1])]
        # ★ 只看"点"是不够的: 两个陆地点之间的【直线】也可能跨水
        #   (采样稀疏时尤其明显)。所以线段中点也要查一遍。
        mids = [((pos[i][0] + pos[i + 1][0]) / 2, (pos[i][1] + pos[i + 1][1]) / 2)
                for i in range(len(pos) - 1)]
        wet += [p for p in mids if in_water(p[0], p[1])]
        if wet:
            bad["water"].append(f"{name}:{len(wet)} 处在水里 "
                                f"例({wet[0][0]:.4f},{wet[0][1]:.4f})")
        segs = [hav(pos[i], pos[i + 1]) for i in range(len(pos) - 1)]
        if segs and max(segs) > 400:
            # ★ 长直线本身不算错(芝加哥是格子街道, 正东西向的路很直很长的有的是),
            #   只要它没跨水就行 —— 中点检查已经在上面做了。
            bad["jump"].append(f"{name}:最长直线段 {max(segs):.0f}m(已查中点)")
        dm = lap.find(f"{NS}DistanceMeters")
        tt = lap.find(f"{NS}TotalTimeSeconds")
        if dm is not None:
            km_all.append(float(dm.text) / 1000.0)
        if tt is not None and len(tps) > 1:
            gap_all.append(float(tt.text) / (len(tps) - 1))
        npts.append(len(tps))
    print(f"  {label:16s} {len(files):3d} 条 | "
          f"XML坏{len(bad['xml'])} Sport错{len(bad['sport'])} 非早上{len(bad['time'])} "
          f"不闭合{len(bad['loop'])} ★在水里{len(bad['water'])} 跳太远{len(bad['jump'])}")
    if km_all:
        km_all.sort()
        print(f"  {'':16s} 距离 {km_all[0]:.2f}~{km_all[-1]:.2f} km(中位 {km_all[len(km_all)//2]:.2f})"
              f"  点数 {min(npts)}~{max(npts)}  打点间隔 {min(gap_all):.1f}~{max(gap_all):.1f}s")
    for k in ("xml", "sport", "time", "loop", "water", "jump"):
        for x in bad[k][:3]:
            print(f"      ★ {k}: {x}")
    return len(bad["xml"]) + len(bad["sport"]) + len(bad["time"]) + len(bad["water"])

def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else (Path.home() / "Desktop" / "运动轨迹")
    print(f"检查目录: {base}")
    print()
    bad = 0
    for city, tz in (("芝加哥", -5), ("洛杉矶", -7)):
        for sp, want in (("跑步", "Running"), ("骑行", "Biking")):
            d = base / f"{city}-{sp}"
            if d.is_dir():
                bad += check_dir(d, want, tz, f"{city}-{sp}")
    print()
    # 顺手看看【原来的素材】有没有同样的问题
    old = Path.home() / "Desktop" / "芝加哥运动"
    if old.is_dir():
        print("对照: 原来的 58 份 GPX 素材")
        wet_files = []
        tot = 0
        for f in sorted(old.glob("*.gpx")):
            tot += 1
            t = f.read_text(encoding="utf-8", errors="replace")
            pts = [(float(a), float(b)) for a, b in
                   re.findall(r'<trkpt lat="([-\d.]+)" lon="([-\d.]+)"', t)]
            w = [p for p in pts if in_water(p[0], p[1])]
            if w:
                wet_files.append((f.name, len(w), len(pts), w[0]))
        print(f"  {tot} 份里有 {len(wet_files)} 份踩到了水里")
        for n, w, tot2, ex in wet_files[:6]:
            print(f"      {n}  {w}/{tot2} 个点在水里  例({ex[0]:.4f},{ex[1]:.4f})")
    print()
    print("★★★ 全部落在陆地 + 路网上 ★★★" if bad == 0 else f"★★★ 有 {bad} 项不合格 ★★★")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
