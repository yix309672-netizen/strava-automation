# -*- coding: utf-8 -*-
r"""逐函数比对当前引擎与旧版本, 并自动圈出"核心链"

用户最在意的那条链(不改的底线):
    地图 -> 找路段标记 -> 读排行榜 -> 逐个筛资料 -> 存链接

本脚本不靠手写函数名去猜核心链, 而是用 AST 从 collect_regions 出发
按**调用图**把整条链自动展开, 再逐个比对, 明确回答"变了没有"。

用法:  python _核心比对.py            # 两个引擎都跑
       python _核心比对.py ADS        # 只跑一个
"""
import ast
import difflib
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ARCHIVE = pathlib.Path(
    r"C:\Users\1\Desktop\_已删除_可还原\桌面散落的项目文件_20260918")

ENGINES = [
    ("ADS", pathlib.Path("主脚本/strava_ads.py"), ARCHIVE / "strava_ads.py"),
    ("BIT", pathlib.Path("主脚本/strava_bit.py"), ARCHIVE / "strava_bit.py"),
]

# 核心链的起点
SEED = "collect_regions"
# 也想单独看一眼的编排函数(不算核心链, 但它决定"开始任务"怎么进这条链)
ORCH = ("run_one", "run_one_seq", "collect_one")


def norm(seg):
    return "\n".join(x.rstrip() for x in seg.splitlines())


def parse(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    funcs, calls = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = norm("\n".join(lines[node.lineno - 1:node.end_lineno]))
            got = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    if isinstance(f, ast.Name):
                        got.add(f.id)
                    elif isinstance(f, ast.Attribute):
                        got.add(f.attr)
            calls[node.name] = got
    return funcs, calls, len(lines)


def chain(funcs, calls, seed):
    """从 seed 出发按调用图展开(只走本文件内的函数)"""
    order, seen, queue = [], set(), [(seed, 0)]
    while queue:
        name, d = queue.pop(0)
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        order.append((name, d))
        for c in sorted(calls.get(name, ())):
            if c in funcs and c not in seen:
                queue.append((c, d + 1))
    return order


def compare(tag, newp, oldp):
    print()
    print("=" * 74)
    print("  引擎 %s" % tag)
    print("=" * 74)
    if not newp.exists() or not oldp.exists():
        print("  ★ 缺少文件: new=%s old=%s" % (newp.exists(), oldp.exists()))
        return
    fnew, cnew, lnew = parse(newp)
    fold, cold, lold = parse(oldp)
    print("  旧: %s  %d 行 / %d 个顶层函数"
          % (oldp.name, lold, len(fold)))
    print("  新: %s  %d 行 / %d 个顶层函数"
          % (newp.name, lnew, len(fnew)))
    print("  旧文件: %s" % oldp)
    print()

    print("-" * 74)
    print("  ★ 核心链 (从 %s 按调用图自动展开)" % SEED)
    print("-" * 74)
    order = chain(fnew, cnew, SEED)
    if not order:
        print("  ★ 新版里找不到 %s" % SEED)
    n_same = n_diff = n_new = 0
    for name, d in order:
        a, b = fold.get(name), fnew.get(name)
        ind = "  " + "   " * d
        if a is None:
            print("%sNEW  %-22s 旧版没有(新增 %d 行)" % (ind, name, len(b.splitlines())))
            n_new += 1
        elif a == b:
            print("%sSAME %-22s 逐字一致 (%d 行)" % (ind, name, len(b.splitlines())))
            n_same += 1
        else:
            dd = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                           lineterm="", n=0))
            add = sum(1 for x in dd if x.startswith("+") and not x.startswith("+++"))
            rem = sum(1 for x in dd if x.startswith("-") and not x.startswith("---"))
            print("%sDIFF %-22s ★ 有改动 +%d/-%d (旧 %d -> 新 %d 行)"
                  % (ind, name, add, rem, len(a.splitlines()), len(b.splitlines())))
            n_diff += 1
    print()
    print("  核心链小计: 逐字一致 %d 个 / 有改动 %d 个 / 新增 %d 个"
          % (n_same, n_diff, n_new))

    print()
    print("-" * 74)
    print("  编排函数 (决定从哪个口子进核心链)")
    print("-" * 74)
    for name in ORCH:
        a, b = fold.get(name), fnew.get(name)
        if a is None and b is None:
            print("  ??   %-16s 两边都没这个名字" % name)
        elif a is None:
            print("  NEW  %-16s 新增 (%d 行)" % (name, len(b.splitlines())))
        elif b is None:
            print("  DEL  %-16s ★ 被删了!" % name)
        elif a == b:
            print("  SAME %-16s 逐字一致 (%d 行)" % (name, len(b.splitlines())))
        else:
            dd = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                           lineterm="", n=0))
            add = sum(1 for x in dd if x.startswith("+") and not x.startswith("+++"))
            rem = sum(1 for x in dd if x.startswith("-") and not x.startswith("---"))
            print("  DIFF %-16s 有改动 +%d/-%d (旧 %d -> 新 %d 行)"
                  % (name, add, rem, len(a.splitlines()), len(b.splitlines())))

    same = [n for n in fnew if n in fold and fnew[n] == fold[n]]
    diff = sorted(n for n in fnew if n in fold and fnew[n] != fold[n])
    added = sorted(n for n in fnew if n not in fold)
    removed = sorted(n for n in fold if n not in fnew)
    print()
    print("-" * 74)
    print("  全部函数概览")
    print("-" * 74)
    print("  逐字一致 : %d" % len(same))
    print("  有改动   : %d  -> %s" % (len(diff), ", ".join(diff)))
    print("  新增     : %d  -> %s" % (len(added), ", ".join(added)))
    print("  删除     : %d  -> %s" % (len(removed), ", ".join(removed) or "无"))

    out = pathlib.Path("_核心逻辑比对_%s.txt" % tag)
    buf = []
    for n in diff:
        buf += ["=" * 70, "### %s" % n, "=" * 70]
        buf += list(difflib.unified_diff(fold[n].splitlines(), fnew[n].splitlines(),
                                         fromfile="OLD/" + n, tofile="NEW/" + n,
                                         lineterm="", n=2))
        buf.append("")
    out.write_text("\n".join(buf), encoding="utf-8")
    print("\n  改动明细 -> %s" % out.name)


want = [a for a in sys.argv[1:] if a.strip()]
for tag, newp, oldp in ENGINES:
    if want and tag not in want:
        continue
    compare(tag, newp, oldp)
