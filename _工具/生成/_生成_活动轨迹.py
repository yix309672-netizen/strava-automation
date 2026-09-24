# -*- coding: utf-8 -*-
r"""生成一批活动轨迹(TCX) —— 这次是【踩真实路网】的, 不会跑到海里去。

★★ 为什么重写 ★★
   上一版用极坐标傅里叶级数画闭环: r(θ)=R(1+Σa·cos(kθ+φ))。
   结果两件事都错了:
     · 圆心是"在经纬度方框里随便撒的", 芝加哥那个方框 lon 到 -87.50 ——
       湖岸线在 -87.60 左右, 所以轨迹直接画到密歇根湖里去了(用户截图: 海上跑步)。
     · 形状是个对称的星形, 一眼就是公式画的, 不像人跑的。
   现在改成【问 OSRM 要真实路网上的环线】: 它只在道路上走, 所以
     · 几何必定落在陆地(水里没有路) —— 从根上解决"海上跑步"
     · 形状就是街道本身: 芝加哥是格子+直角, 洛杉矶是自由的曲线
   代价: 要联网。会缓存在本地, 重跑不再请求。

★★ 为什么是 TCX 不是 GPX ★★
   Strava 标题 = 时间段 + 活动类型。GPX 没有类型 -> 上传页默认 Workout。
   TCX 的 <Activity Sport="Running"/"Biking"> 会被 Strava 认成 Run/Ride,
   配合"早上开始"就自动是 Morning Run / Morning Ride。

用法:
    python _生成_活动轨迹.py --city chicago --sport run  --count 60
    python _生成_活动轨迹.py --city la      --sport ride --count 60
    python _生成_活动轨迹.py --all          # 四套一起出(默认)
"""
import argparse
import json
import math
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
CACHE = ROOT / "_过程记录" / "_路线缓存.json"
OSRM = "http://router.project-osrm.org"
UA = {"User-Agent": "strava-route-tool/1.0", "Accept": "*/*"}

# ★ 锚点全都选在【远离水面】的市区。OSRM 只在路上走, 所以即使圈稍微碰到水面,
#   路线也会绕回陆地 —— 但锚点本身不能在水里, 否则最近的路要过桥/绕很远。
CITIES = {
    "chicago": {
        "name": "芝加哥", "tz": -5,
        # ★★ 锚点必须【离湖足够远】★★
        #   第一版留了几个离岸只有 2km 的锚点(River North/Lincoln Park 西侧),
        #   跑/骑的距离一长就摸到湖边, 于是路线拐上【海军码头】【贝尔蒙特港】
        #   那种伸进水里的栈桥路 —— 60 条骑行里 25 条被判"在水里"。
        #   现在全部压到 lon <= -87.66 (离湖岸 5km 以上)。
        "anchors": [(41.8835, -87.6580),   # 西 Loop
                    (41.9100, -87.6790),   # Wicker Park / Logan Square
                    (41.8550, -87.6600),   # Pilsen / 小村
                    (41.9400, -87.7100),   # 西北侧(离湖 7km)
                    (41.9250, -87.6950),   # Bucktown 北
                    (41.8950, -87.6750),   # 近西区
                    (41.8800, -87.6900),   # 小意大利西
                    (41.8000, -87.6250),   # 中途机场一带
                    (41.8700, -87.7200),   # 西郊 Cicero 方向
                    (41.9600, -87.6800)],  # 北郊
    },
    "la": {
        "name": "洛杉矶", "tz": -7,
        "anchors": [(34.0500, -118.2500),  # Downtown LA
                    (34.0620, -118.3000),  # Koreatown
                    (34.1000, -118.3300),  # Hollywood
                    (34.0900, -118.2700),  # Silver Lake
                    (34.0200, -118.4000),  # Culver City
                    (34.1450, -118.1450),  # Pasadena
                    (34.0700, -118.4000),  # Beverly Hills 西侧
                    (34.0100, -118.2900)], # 南 LA
    },
}
SPORTS = {
    "run":  {"sport": "Running", "km": (1.5, 8.0), "kmh": (8.5, 14.0),
             "gap": (3.0, 20.0), "pts": (35, 400)},
    "ride": {"sport": "Biking",  "km": (10.0, 45.0), "kmh": (18.0, 32.0),
             "gap": (3.0, 20.0), "pts": (60, 600)},
}


def hav(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


# ★ 芝加哥湖岸线(从南到北, 湖在东侧=经度更大)。只用来【拦掉跑到水里的路线】,
#   粗判即可 —— 目的是不让轨迹拐上伸进湖里的栈桥, 不追求米级精度。
CHI_SHORE = [
    (41.64, -87.525), (41.73, -87.530), (41.76, -87.550), (41.79, -87.575),
    (41.82, -87.585), (41.85, -87.600), (41.87, -87.607), (41.885, -87.612),
    (41.890, -87.607), (41.915, -87.625), (41.930, -87.635), (41.950, -87.645),
    (41.980, -87.655), (42.020, -87.670), (42.100, -87.700),
]


def _shore_lon(lat):
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
    if 41.5 <= lat <= 42.2 and -88.0 <= lon <= -87.3:      # 芝加哥: 湖在东边
        return lon > _shore_lon(lat)
    if 33.5 <= lat <= 34.5 and -119.0 <= lon <= -117.8:    # 洛杉矶: 太平洋在西南
        return lon < -118.48 or lat < 33.95
    return False


_cache = {}
_calls = [0]


def load_cache():
    global _cache
    if CACHE.is_file():
        try:
            _cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}


def save_cache():
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache), encoding="utf-8")
    except Exception:
        pass


def osrm_trip(pts):
    """问 OSRM 要一条经过这些点的环线, 返回 (米, [(lat,lon)...]) 或 None。"""
    key = ";".join(f"{round(lo, 6)},{round(la, 6)}" for la, lo in pts)
    if key in _cache:
        v = _cache[key]
        return (v[0], [tuple(x) for x in v[1]]) if v else None
    c = ";".join(f"{lo},{la}" for la, lo in pts)
    url = (f"{OSRM}/trip/v1/driving/{urllib.parse.quote(c)}"
           f"?roundtrip=true&source=first&destination=last"
           f"&geometries=geojson&overview=full")
    out = None
    for _try in range(2):
        try:
            _calls[0] += 1
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40)
            j = json.loads(r.read())
            if j.get("code") == "Ok" and j.get("trips"):
                t = j["trips"][0]
                geo = [(p[1], p[0]) for p in t["geometry"]["coordinates"]]
                out = (float(t["distance"]), geo)
                break
        except Exception as e:
            if _try == 0:
                time.sleep(1.0)
            else:
                print(f"      OSRM 失败: {str(e)[:60]}")
    _cache[key] = [out[0], [[a, b] for a, b in out[1]]] if out else None
    time.sleep(0.35)                     # 示例服务器: 别打太快
    return out


def ring(rng, lat, lon, radius_m, k):
    """在锚点周围撒 k 个点(半径 radius_m 内)。"""
    out = []
    for i in range(k):
        th = 2 * math.pi * i / k + rng.uniform(-0.4, 0.4)
        r = radius_m * rng.uniform(0.55, 1.15)
        out.append((lat + (r * math.sin(th)) / 111320.0,
                    lon + (r * math.cos(th)) / (111320.0 * math.cos(math.radians(lat)))))
    return out


def build_route(rng, anchor, want_km, tries=4):
    """要一条长度接近 want_km 的环线; 拿不到就返回 None(换锚点重来)。"""
    r = max(120.0, want_km * 1000.0 / (2 * math.pi) * 0.45)
    best = None
    for _ in range(tries):
        k = rng.choice((3, 4, 5, 6))
        pts = [anchor] + ring(rng, anchor[0], anchor[1], r, k)
        got = osrm_trip(pts)
        if not got:
            r *= 1.3
            continue
        dist, geo = got
        km = dist / 1000.0
        if best is None or abs(km - want_km) < abs(best[0] / 1000.0 - want_km):
            best = (dist, geo)
        if want_km * 0.55 <= km <= want_km * 1.8:
            return dist, geo
        r *= max(0.5, min(2.5, want_km / max(km, 0.2)))   # 按比例修正再来一次
    return best


def resample(geo, n):
    """按累计弧长把几何点均匀抽成 n 个。"""
    if len(geo) <= n:
        return list(geo)
    seg = [hav(geo[i], geo[i + 1]) for i in range(len(geo) - 1)]
    total = sum(seg) or 1.0
    out, want, acc, j = [geo[0]], total / (n - 1), 0.0, 0
    for i, s in enumerate(seg):
        target = want * len(out)
        while acc + s >= target and len(out) < n - 1:
            t = (target - acc) / max(s, 1e-9)
            out.append((geo[i][0] + (geo[i + 1][0] - geo[i][0]) * t,
                        geo[i][1] + (geo[i + 1][1] - geo[i][1]) * t))
            target = want * len(out)
        acc += s
        j = i
    out.append(geo[-1])
    return out


def make_track(rng, city, sport, when):
    """造一条: 返回 (点, 时间, 累计距离, 总米数) 或 None。"""
    cfg, sp = CITIES[city], SPORTS[sport]
    want = rng.uniform(*sp["km"])
    if rng.random() < 0.3:                       # 偶尔来条长的
        want = min(sp["km"][1], want * rng.uniform(1.3, 1.7))
    for _ in range(6):
        anchor = rng.choice(cfg["anchors"])
        a = (anchor[0] + rng.uniform(-0.006, 0.006),
             anchor[1] + rng.uniform(-0.006, 0.006))
        got = build_route(rng, a, want)
        if got:
            # ★★ 拿到路线后再查一次水: OSRM 只在路上走, 但有些"路"是伸进湖里的
            #   栈桥(海军码头/贝尔蒙特港)。踩到就换锚点重来, 别把这种东西发给用户。
            wet = sum(1 for la, lo in got[1] if in_water(la, lo))
            if wet == 0:
                break
            print(f"      (这条有 {wet} 个点在水里, 换锚点重来)")
            got = None
    if not got:
        return None
    dist_m, geo = got
    kmh = rng.uniform(*sp["kmh"])
    dur = dist_m / (kmh * 1000.0 / 3600.0)
    gap = rng.uniform(*sp["gap"])
    n = max(sp["pts"][0], min(sp["pts"][1], int(dur / gap)))
    pts = resample(geo, n)
    # 时间戳: 距离/速度, 速度带点自然起伏
    seg = [hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    v0 = dist_m / dur
    times, dists, t, acc = [], [], 0.0, 0.0
    for i in range(len(pts)):
        times.append(when + timedelta(seconds=t))
        dists.append(acc)
        if i < len(seg):
            v = v0 * rng.uniform(0.88, 1.12)
            dt = seg[i] / max(v, 0.3)
            t += dt
            acc += seg[i]
    return pts, times, dists, acc


def tcx(sport, pts, times, dists, meters):
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    dur = (times[-1] - times[0]).total_seconds()
    tp = []
    for i, (la, lo) in enumerate(pts):
        tp.append("        <Trackpoint>\n"
                  f"          <Time>{iso(times[i])}</Time>\n"
                  "          <Position>\n"
                  f"            <LatitudeDegrees>{la:.6f}</LatitudeDegrees>\n"
                  f"            <LongitudeDegrees>{lo:.6f}</LongitudeDegrees>\n"
                  "          </Position>\n"
                  f"          <AltitudeMeters>{180.0 + 2.0 * math.sin(i / 9.0):.1f}</AltitudeMeters>\n"
                  f"          <DistanceMeters>{dists[i]:.1f}</DistanceMeters>\n"
                  "        </Trackpoint>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/'
            'TrainingCenterDatabase/v2" xmlns:xsi="http://www.w3.org/2001/'
            'XMLSchema-instance" xsi:schemaLocation="http://www.garmin.com/'
            'xmlschemas/TrainingCenterDatabase/v2 http://www.garmin.com/'
            'xmlschemas/TrainingCenterDatabasev2.xsd">\n'
            "  <Activities>\n"
            f'    <Activity Sport="{SPORTS[sport]["sport"]}">\n'
            f"      <Id>{iso(times[0])}</Id>\n"
            f'      <Lap StartTime="{iso(times[0])}">\n'
            f"        <TotalTimeSeconds>{dur:.1f}</TotalTimeSeconds>\n"
            f"        <DistanceMeters>{meters:.1f}</DistanceMeters>\n"
            f"        <Calories>{int(meters / 1000.0 * (65 if sport == 'run' else 30))}</Calories>\n"
            "        <Intensity>Active</Intensity>\n"
            "        <TriggerMethod>Manual</TriggerMethod>\n"
            "        <Track>\n" + "\n".join(tp) + "\n        </Track>\n"
            "      </Lap>\n"
            f"      <Notes>Morning {'Run' if sport == 'run' else 'Ride'}</Notes>\n"
            "    </Activity>\n"
            "  </Activities>\n"
            "</TrainingCenterDatabase>\n")


def gen(city, sport, count, outdir, start, end, seed):
    rng = random.Random(seed)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = CITIES[city]
    d0, d1 = datetime.fromisoformat(start), datetime.fromisoformat(end)
    span = (d1 - d0).days
    made, fails = [], 0
    for i in range(count):
        day = d0 + timedelta(days=int(span * i / max(count - 1, 1)) + rng.randint(-1, 1))
        when = datetime(day.year, day.month, day.day,
                        rng.randint(6, 8), rng.randint(0, 59), rng.randint(0, 59),
                        tzinfo=timezone(timedelta(hours=cfg["tz"])))
        tr = make_track(rng, city, sport, when)
        if not tr:
            fails += 1
            continue
        pts, times, dists, meters = tr
        p = out / f"{cfg['name']} {day.month}.{day.day}.tcx"
        p.write_text(tcx(sport, pts, times, dists, meters), encoding="utf-8")
        made.append((p.name, meters / 1000.0,
                     (times[-1] - times[0]).total_seconds() / 60.0, len(pts)))
    km = sorted(m[1] for m in made) or [0]
    print(f"  {cfg['name']}-{'跑步' if sport == 'run' else '骑行'}: {len(made)} 条"
          f"{' (失败 %d)' % fails if fails else ''} -> {out}")
    if made:
        print(f"     距离 {km[0]:.2f}~{km[-1]:.2f} km (中位 {km[len(km)//2]:.2f})  "
              f"点数 {min(m[3] for m in made)}~{max(m[3] for m in made)}")
    return len(made)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", choices=list(CITIES))
    ap.add_argument("--sport", choices=list(SPORTS))
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--out", default=str(Path.home() / "Desktop" / "运动轨迹"))
    ap.add_argument("--start", default="2026-04-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--all", action="store_true", help="四套一起出(默认)")
    a = ap.parse_args()
    load_cache()
    jobs = []
    if a.city and a.sport:
        jobs = [(a.city, a.sport)]
    else:
        for c in ("chicago", "la"):
            for s in ("run", "ride"):
                jobs.append((c, s))
    print(f"要生成 {len(jobs)} 套, 每套 {a.count} 条")
    tot = 0
    for c, s in jobs:
        sub = Path(a.out) / f"{CITIES[c]['name']}-{'跑步' if s == 'run' else '骑行'}"
        tot += gen(c, s, a.count, sub, a.start, a.end, a.seed + hash((c, s)) % 9999)
    save_cache()
    print()
    print(f"合计 {tot} 条 -> {a.out}")
    print(f"OSRM 请求 {_calls[0]} 次(其余走了缓存)")
    print("★ 这些都在【真实路网】上, 不会跑到水里; 也都是 TCX + 早上开始。")


if __name__ == "__main__":
    main()
