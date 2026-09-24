# -*- coding: utf-8 -*-
r"""把素材里"跑到水里"的 GPX 换成新造的、在真实路网上的 GPX。

★★ 为什么会有这种文件 ★★
   用户截图问"我在海上跑步吗" —— 一查, 除了我上一版生成的那批(已删),
   用户【原来的 58 份素材】里也有 3 份踩水, 其中 2 份整条都在密歇根湖里:
       芝加哥 5.1.gpx    46/46 个点在水里   (41.5776,-87.4882)
       芝加哥 9.12.gpx   46/46 个点在水里   (同一圈, 坐标一模一样)
       芝加哥 6.15.gpx   16/366 个点在水里
   (41.578,-87.488 在密歇根湖里, 离岸十几公里。)

★★ 替换原则 ★★
   · 文件名一个字不改(引擎按 (\d+)\.(\d+) 排序, 改了顺序就乱)
   · 格式保持 GPX(这个文件夹本来就是 GPX, 不掺 TCX)
   · 日期保持一致(5.1 -> 5月1日, 9.12 -> 9月12日)
   · 距离尽量贴近原来那份
   · 起始时间统一放到【早上 06:00-09:00】(原来 9.12 是傍晚 18:24)
   · 新轨迹走真实路网(OSRM), 生成后再自查一遍水

用法:
    python _修_素材跑水里.py                 # 只看哪几份要换
    python _修_素材跑水里.py --apply         # 真换(先备份到 项目\_备份\)
"""
import argparse
import importlib.util
import math
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
GEN = ROOT / "_工具" / "生成" / "_生成_活动轨迹.py"

_spec = importlib.util.spec_from_file_location("_gen_mod", GEN)
G = importlib.util.module_from_spec(_spec)
sys.modules["_gen_mod"] = G
_spec.loader.exec_module(G)

GPX_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx creator="https://gpx.studio" version="1.1" '
            'xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
            'http://www.topografix.com/GPX/1/1/gpx.xsd">\n')


def read_gpx(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    pts = [(float(a), float(b)) for a, b in
           re.findall(r'<trkpt lat="([-\d.]+)" lon="([-\d.]+)"', t)]
    ts = [datetime.fromisoformat(x.replace("Z", "+00:00"))
          for x in re.findall(r"<time>([^<]+)</time>", t)]
    dist = sum(G.hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) if len(pts) > 1 else 0.0
    return pts, ts, dist


def write_gpx(p, name, pts, times):
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = []
    for i, (la, lo) in enumerate(pts):
        body.append(f'      <trkpt lat="{la:.6f}" lon="{lo:.6f}">\n'
                    f"        <ele>{182 + 2 * math.sin(i / 9.0):.0f}</ele>\n"
                    f"        <time>{iso(times[i])}</time>\n"
                    "      </trkpt>")
    p.write_text(
        GPX_HEAD
        + "  <metadata>\n"
        + f"    <name>{name}</name>\n"
        + "  </metadata>\n"
        + "  <trk>\n"
        + f"    <name>{name}</name>\n"
        + "    <trkseg>\n" + "\n".join(body) + "\n    </trkseg>\n"
        + "  </trk>\n</gpx>\n",
        encoding="utf-8")


def rebuild(rng, name, want_km, day):
    """照原距离/日期重造一条, 返回 (点, 时间) 或 None。"""
    # 起始时间: 本地早上 06:00-09:00
    when = datetime(day.year, day.month, day.day,
                    rng.randint(6, 8), rng.randint(0, 59), rng.randint(0, 59),
                    tzinfo=timezone(timedelta(hours=-5)))
    for _ in range(8):
        anchor = rng.choice(G.CITIES["chicago"]["anchors"])
        a = (anchor[0] + rng.uniform(-0.006, 0.006),
             anchor[1] + rng.uniform(-0.006, 0.006))
        got = G.build_route(rng, a, want_km)
        if got and not any(G.in_water(la, lo) for la, lo in got[1]):
            dist_m, geo = got
            break
    else:
        return None
    kmh = rng.uniform(8.5, 12.0)
    dur = dist_m / (kmh * 1000.0 / 3600.0)
    n = max(35, min(400, int(dur / rng.uniform(4.0, 12.0))))
    pts = G.resample(geo, n)
    seg = [G.hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    v0 = dist_m / dur
    times, t = [], 0.0
    for i in range(len(pts)):
        times.append(when + timedelta(seconds=t))
        if i < len(seg):
            t += seg[i] / max(v0 * rng.uniform(0.9, 1.1), 0.3)
    return pts, times


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Desktop" / "芝加哥运动"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--seed", type=int, default=20260922)
    a = ap.parse_args()

    folder = Path(a.dir)
    files = sorted(folder.glob("*.gpx"))
    if not files:
        print(f"★ {folder} 里没有 .gpx")
        return 1
    print(f"扫 {folder}  ({len(files)} 份)")

    bad = []
    for f in files:
        pts, ts, dist = read_gpx(f)
        wet = [p for p in pts if G.in_water(p[0], p[1])]
        if wet:
            bad.append((f, len(pts), dist / 1000.0, ts[0] if ts else None, wet[0]))
    if not bad:
        print("  没有踩水的, 不用动")
        return 0
    print(f"  踩水的 {len(bad)} 份:")
    for f, n, km, t0, ex in bad:
        print(f"    {f.name:20s} {n:4d}点 {km:5.2f}km  "
              f"起 {t0.astimezone(timezone(timedelta(hours=-5))):%Y-%m-%d %H:%M}  "
              f"例({ex[0]:.4f},{ex[1]:.4f})")
    if not a.apply:
        print()
        print("(未改动 —— 加 --apply 才真换; 换之前会把原文件备份到 项目\\_备份\\)")
        return 0

    bakdir = ROOT / "_备份" / f"_替换水里跑的_{time.strftime('%Y%m%d_%H%M%S')}"
    bakdir.mkdir(parents=True, exist_ok=True)
    rng = __import__("random").Random(a.seed)
    G.load_cache()
    n_ok = 0
    for f, n, km, t0, ex in bad:
        local = t0.astimezone(timezone(timedelta(hours=-5))) if t0 else datetime(2026, 4, 1)
        got = rebuild(rng, f.stem, km or 3.0, local)
        if not got:
            print(f"    ★ {f.name}: 造不出来, 跳过")
            continue
        pts, times = got
        wet2 = [p for p in pts if G.in_water(p[0], p[1])]
        if wet2:
            print(f"    ★ {f.name}: 新造的还有 {len(wet2)} 个点在水里, 跳过")
            continue
        shutil.copy2(f, bakdir / f.name)
        write_gpx(f, f.stem, pts, times)
        real = sum(G.hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) / 1000.0
        print(f"    OK {f.name:20s} {km:5.2f}km -> {real:5.2f}km  "
              f"{len(pts):4d}点  起 "
              f"{times[0].astimezone(timezone(timedelta(hours=-5))):%m-%d %H:%M}")
        n_ok += 1
    G.save_cache()
    print()
    print(f"换了 {n_ok} 份; 原件备份在 {bakdir}")
    print(f"OSRM 请求 {G._calls[0]} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
