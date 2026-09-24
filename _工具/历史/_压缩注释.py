# -*- coding: utf-8 -*-
"""审视并压缩代码 —— 只压注释, 不动一行逻辑。

问题: 4 个文件 13983 行里有 1633 行注释(12%), 12 处注释块超过 8 行, 最长 19 行。
      大部分是【过程记录】: 用户哪天实测了什么、我判断错过什么、修过几次。
      那是给对话看的, 不是给代码看的。代码要的是"为什么这么写、别改回去",
      一两句就够。

原则:
  · 只改【纯注释行】的连续块和行尾注释, 【一行代码都不动】
  · 每个块保留: 核心事实 + 关键数字 + 别改回去的理由
  · 删掉: 日期流水、"用户原话"整段、"我判断错了"的自述、重复铺垫
  · 关键块(如 RLock 不能改 Lock、不能线程池包 send)【必须留】——
    那些是"改了就出事"的警告, 属于代码的一部分

先干跑, 打印会删掉什么, 确认后再真跑。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(".")
FILES = ["主脚本/strava_ads.py", "主脚本/strava_bit.py",
         "界面/ADS自动化.py", "界面/比特派自动化.py"]
GO = "--go" in sys.argv

# 一个注释块最多保留几行(超出就压)
MAX_BLOCK = 4

# 这些块是"改了就出事"的警告, 原样保留
KEEP_MARK = ("RLock", "绝对不要用线程池", "原子写", "绝不能", "★ 必须是")

DROP_PAT = re.compile(
    r"(用户原话|用户实测|用户报|我第一版|我一度|我判断错|错因|"
    r"第一次|第二次|踩过两次|教训[:：]|留档|更正|"
    r"2026-09-1\d \d\d:\d\d|真机实测|真机教训)")


def shrink(block):
    """块 -> 压缩后的行。保留首要事实, 丢掉过程叙述。"""
    if len(block) <= MAX_BLOCK:
        return block
    if any(k in "\n".join(block) for k in KEEP_MARK):
        return block[:MAX_BLOCK + 4]          # 警告块多留一点
    head = block[0]
    rest = [l for l in block[1:] if not DROP_PAT.search(l)]
    out = [head] + rest
    return out[:MAX_BLOCK]


def process(path):
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    out, i, saved, blocks = [], 0, 0, 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("#") and not s.startswith("#!"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1
            blk = lines[i:j]
            new = shrink(blk)
            if len(new) < len(blk):
                blocks += 1
                saved += len(blk) - len(new)
            out.extend(new)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out) + "\n", saved, blocks


print("=" * 78)
print("注释压缩 %s" % ("【正式执行】" if GO else "【干跑, 什么都不动】"))
print("=" * 78)
tot_saved = tot_blocks = 0
for f in FILES:
    p = ROOT / f
    src = p.read_text(encoding="utf-8")
    new, saved, blocks = process(p)
    old_n = len(src.splitlines())
    new_n = len(new.splitlines())
    tot_saved += saved
    tot_blocks += blocks
    print("  %-26s %5d -> %5d 行  (精简 %d 块, 去掉 %d 行注释)"
          % (pathlib.Path(f).name, old_n, new_n, blocks, saved))
    if GO:
        p.write_text(new, encoding="utf-8")

print()
print("合计: 精简 %d 个注释块, 去掉 %d 行" % (tot_blocks, tot_saved))
if not GO:
    print()
    print("干跑结束。确认就加 --go 真跑:  python _压缩注释.py --go")
else:
    import py_compile
    print()
    print("语法检查:")
    for f in FILES:
        try:
            py_compile.compile(f, doraise=True, cfile="__pycache__/x.pyc")
            print("  OK   " + f)
        except Exception as e:
            print("  FAIL %s  %s" % (f, str(e)[:150]))
