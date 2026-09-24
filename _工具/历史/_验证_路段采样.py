# -*- coding: utf-8 -*-
"""验证: 平移网格是不是真的"每一轮都是新地面", 以及上限是否已放开。

用户原话:「采集效率太慢, 芝加哥几百上千万用户, 是你选点只选择几个重复的」
所以要证两件事:
  ① 新的 grid_pan_targets 不再走回头路(旧版 8 轮只有 3 个不同位置)
  ② 平移轮数 / 采样目标 已经从 8/12 放开到 24/48, 而且可以在 config 里调
"""
import importlib.util
import pathlib
import sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "主脚本"))

PASS, FAIL = [], []


def check(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-44s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


def load(name):
    spec = importlib.util.spec_from_file_location(
        "eng_" + name, ROOT / "主脚本" / ("strava_%s.py" % name))
    m = importlib.util.module_from_spec(spec)
    sys.modules["eng_" + name] = m
    spec.loader.exec_module(m)
    return m


def walk(targets, cx=700, cy=400):
    """把"每次从中心拖到终点"还原成地图的累计位移序列"""
    x = y = 0
    pos = []
    for (tx, ty) in targets:
        x += tx - cx
        y += ty - cy
        pos.append((x, y))
    return pos


OLD_PATTERN = ((1, 0), (1, 0), (0, 1), (-1, 0), (-1, 0), (0, 1))
OLD_SX, OLD_SY = 420, 260


def old_targets(rounds, cx=700, cy=400):
    out = []
    for i in range(rounds):
        px, py = OLD_PATTERN[i % len(OLD_PATTERN)]
        out.append((cx + px * OLD_SX, cy + py * OLD_SY))
    return out


def main():
    print("=" * 80)
    print("验证: 路段采样 —— 网格不再重复 + 上限已放开")
    print("=" * 80)

    print()
    print("--- 旧版(6 步固定 pattern, 8 轮) ---")
    op = walk(old_targets(8))
    print("    实际位移:", op)
    # ★ 更正: 旧版 8 轮【本来就是】3 列 x 3 行的正经蛇形, 8 个新位置、不回头。
    #   我一度误判成"只有 3 个位置、走回头路" —— 错因是把"拖拽终点"(相对中心)
    #   当成了"地图绝对位置"。这条断言就是防止再犯同一个错。
    check("旧版 8 轮 = 8 个不同位置(它并没走回头路)", len(set(op)), 8)

    for name in ("ads", "bit"):
        print()
        print("--- 新版 strava_%s.py ---" % name)
        m = load(name)

        check("ENOUGH_SEGMENTS 已放开", m.ENOUGH_SEGMENTS, 48)
        check("PAN_ROUNDS 已放开", m.PAN_ROUNDS, 24)

        tg = m.grid_pan_targets(m.PAN_ROUNDS)
        np_ = walk(tg)
        check("轮数", len(tg), 24)
        check("★ 24 轮里【不同】的位置数(应为 24)",
              len(set(np_)), m.PAN_ROUNDS)
        # 单调: 走过的格子不回头
        cols = m.GRID_PAN_COLS
        cells = [(round(x / m.GRID_PAN_STEP_X), round(y / m.GRID_PAN_STEP_Y))
                 for (x, y) in np_]
        dup = [c for c in set(cells) if cells.count(c) > 1]
        check("★ 没有重复格子", dup, [])
        # 每轮位移不超过一格(不会拖出屏幕)
        over = []
        px = py = 0
        for (x, y) in np_:
            if abs(x - px) > m.GRID_PAN_STEP_X or abs(y - py) > m.GRID_PAN_STEP_Y:
                over.append((x, y))
            px, py = x, y
        check("★ 每轮位移不超过一格(终点在视口内)", over, [])
        print("        24 轮走位: %s" % (cells[:12],))

        # 上限可配
        src = (ROOT / "主脚本" / ("strava_%s.py" % name)).read_text(encoding="utf-8")
        for key in ('CFG.get("pan_rounds")', 'CFG.get("enough_segments")'):
            check("可从 config 读 %s" % key, key in src, True)
        check("循环用的是可配变量 _pan_rounds",
              "range(_pan_rounds)" in src, True)
        check("停止条件用的是 _enough",
              "len(seg_cands) >= _enough" in src, True)

    print()
    print("=" * 80)
    if FAIL:
        print("★ 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print("✓ 通过 %d 项。" % len(PASS))
    print("  · 网格: 24 轮全是新地面, 每轮位移不超过一格(旧版 8 轮也没问题,")
    print("          这点我先前判断错了, 已在代码注释里留档更正)")
    print("  · 真正的改动: 平移 8 -> 24 轮, 采样目标 12 -> 48 个路段")
    print("    (SEGS_PER_REGION_CAP=40 这下才真正生效)")
    print("  · pan_rounds / enough_segments 可在 config.json 里调, 不用改代码")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
