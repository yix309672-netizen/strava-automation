# -*- coding: utf-8 -*-
"""把用户给的 1000 个名字放进两个引擎。

★★ 2026-09-20 用户提供「美国华人女性名字1000个（带常见华人姓氏）」,
   要求「放进脚本」★★

原来是什么样:
    english_names(50) 用 FIRST×LAST 各 50 个, 而且两边【同步取模】:
        f"{FIRST[i % 50]} {LAST[i % 50]}"
    i=0..49 时正好一一对应 -> 实际只产出【50 个】名字。
    编号 1 和 51 拿到同一个名字。

现在:
    · 1000 个名字【内嵌】进引擎(不外挂 txt —— 少一个文件就少一处
      "同事那边丢了 / 没更新到" 的可能)
    · name_for_seq(编号) 在 1000 个里取, 编号不撞名字就不撞
    · english_names(n) 保留, 兼容老调用方(取前 n 个)
    · 万一名字库为空, 自动退回老的 50 个规则, 不出空名字
"""
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
SRC = Path(r"C:\Users\1\AppData\Local\DeepSeek-Harness-Portable\dsh-home"
           r"\attachments\v1\files\6a"
           r"\6a5e2dcfb181782e138405a0dadf02e62b88ef48a467ff50e3f58c3ce87db5ad\名字.txt")
OUT = ROOT / "主脚本" / "name_bank.py"      # 生成的模块(给引擎 import)

# ---- 1. 解析名字 ----
lines = SRC.read_text(encoding="utf-8", errors="replace").splitlines()
names, seen = [], set()
for ln in lines:
    m = re.match(r"^\s*\d+[\.、]\s*(.+?)\s*$", ln)
    if not m:
        continue
    nm = " ".join(m.group(1).split())        # 压掉多余空格
    if not nm or nm in seen:
        continue                              # 去重(Zoe Lu 出现过两次)
    seen.add(nm)
    names.append(nm)

print(f"解析出 {len(names)} 个名字(已去重, 原有 {len(lines)} 行)")

# ---- 2. 写成一个独立模块 ----
# ★ 用 .replace 占位, 不用 % 格式化 —— 模板里有 %d / % 这些, 一不留神就
#   "not enough arguments for format string"(这次就踩了)。
# ★ 每行必须是 "名字", —— 上一版换成 .replace 时把引号和逗号丢了,
#   生成的模块直接 SyntaxError(好在引擎有兜底, 没崩, 退回了 50 个)。
body = "\n".join(f'    "{n}",' for n in names)
MOD_T = '''# -*- coding: utf-8 -*-
"""名字库 —— 1000 个美国华人女性名字(带常见华人姓氏)。

★ 由用户提供的 名字.txt 生成, 不要手改这个文件。
★ 为什么单独一个模块, 而不是内嵌进两个引擎:
    · 内嵌会把 strava_ads.py / strava_bit.py 各撑大 20KB, 而且两份完全重复
    · 放成模块两边 import 同一份, 永远不会"改了一个忘了另一个"
    · 引擎里保留老的 50 个名字做兜底: 这个文件万一丢了也不会出现空名字
"""

NAMES = [
{ROWS}
]

# 便于自检: 数量不对就是被截断了
assert len(NAMES) >= 900, "名字库看起来不完整: " + str(len(NAMES)) + " 个"
'''
MOD = (MOD_T.replace("{ROWS}", body))

OUT.write_text(MOD, encoding="utf-8")
print(f"已写出: {OUT.name}  ({len(MOD)} 字节, {len(names)} 个名字)")

# ---- 3. 改两个引擎 ----
NEW_FUNCS = '''# ---------------------------------------------------------------- 名字库
# ★★ 2026-09-20 用户提供「美国华人女性名字1000个(带常见华人姓氏)」, 要求放进脚本 ★★
#   原来 FIRST×LAST 各 50 个、两边【同步取模】(FIRST[i%50] LAST[i%50]),
#   i=0..49 一一对应 -> 实际只产出【50 个】名字: 编号 1 和 51 是同一个。
#   现在从 name_bank.NAMES(1000 个)里取, 编号不撞名字就不撞。
#   下面这份 50 个的【保留做兜底】: name_bank 万一丢了也不会出现空名字。
_LEGACY_FIRST = ['Emily','Sophia','Olivia','Ava','Emma','Mia','Isabella','Grace','Chloe','Lily',
                 'Hannah','Sarah','Jessica','Michelle','Jennifer','Amy','Lucy','Anna','Alice','Ruby',
                 'Eva','Ivy','Zoe','Nora','Stella','Claire','Ella','Aria','Aubrey','Hazel','Violet',
                 'Aurora','Savannah','Brooklyn','Bella','Clara','Elena','Nina','Ariana','Maya','Luna',
                 'Nova','Iris','Elise','Fiona','Georgia','Holly','Irene','Julia','Karen','Laura']
_LEGACY_LAST = ['Chen','Lin','Huang','Zhang','Li','Wang','Liu','Yang','Zhao','Wu','Zhou','Xu','Sun',
                'Ma','Zhu','Hu','Guo','He','Luo','Liang','Zheng','Xie','Han','Tang','Feng','Dong',
                'Xiao','Cheng','Cao','Yuan','Deng','Fu','Shen','Zeng','Peng','Lv','Su','Lu','Jiang',
                'Cai','Jia','Ding','Wei','Xue','Ye','Yu','Pan','Du','Dai']
_LEGACY_50 = [f"{_LEGACY_FIRST[i % len(_LEGACY_FIRST)]} "
              f"{_LEGACY_LAST[i % len(_LEGACY_LAST)]}" for i in range(50)]

try:
    from name_bank import NAMES as _NAME_BANK
    NAMES = [str(x).strip() for x in _NAME_BANK if str(x).strip()]
except Exception as _nb_err:
    print(f"[names] ★ 名字库 name_bank.py 读不到({_nb_err}); 退回内置 50 个")
    NAMES = list(_LEGACY_50)


def english_names(n=None):
    """名字表。传 n 就取前 n 个(兼容老调用方), 不传返回全部。"""
    if n is None:
        return list(NAMES)
    try:
        n = int(n)
    except Exception:
        n = 50
    if n <= 0:
        n = 50
    if n <= len(NAMES):
        return list(NAMES[:n])
    out = []
    while len(out) < n and NAMES:
        out.extend(NAMES)
    return out[:n] or list(_LEGACY_50[:n])


def name_for_seq(seq):
    """按编号取名字: 在【整个名字库】里取, 不再卡在 50 个上。
    ★ 与 run_one_seq 用的是同一个函数, 预览和实跑不会再对不上。
    """
    try:
        _s = int(str(seq).strip())
    except Exception:
        _s = 1
    if not NAMES:
        return _LEGACY_50[(_s - 1) % 50]
    return NAMES[(_s - 1) % len(NAMES)]
'''

# 匹配老的 english_names + name_for_seq 两段
PAT = re.compile(
    r"def english_names\(n=50\):.*?\n\n\ndef name_for_seq\(seq\):.*?\n    return english_names\(50\)\[\(_s - 1\) % 50\]\n",
    re.S)

for fname in ("strava_ads.py", "strava_bit.py"):
    p = ROOT / "主脚本" / fname
    t = p.read_text(encoding="utf-8")
    if "from name_bank import NAMES" in t:
        print(f"  {fname}: 已经装过了, 跳过")
        continue
    t2, n = PAT.subn(NEW_FUNCS, t, count=1)
    if n != 1:
        print(f"  ★ {fname}: 没匹配到老的 english_names/name_for_seq, 没动")
        continue
    # run_one_seq 里那句改成走 name_for_seq
    t2 = t2.replace("nm = english_names(50)[(seq - 1) % 50]",
                    "nm = name_for_seq(seq)      # ★ 1000 个名字里取")
    p.write_text(t2, encoding="utf-8")
    print(f"  {fname}: 已替换 (english_names/name_for_seq 换成名字库版)")

print()
print("=" * 70)
for fname in ("strava_ads.py", "strava_bit.py"):
    t = (ROOT / "主脚本" / fname).read_text(encoding="utf-8")
    print(f"{fname}:")
    print(f"   from name_bank import NAMES : {'from name_bank import NAMES' in t}")
    print(f"   name_for_seq 走名字库       : {'NAMES[(_s - 1) % len(NAMES)]' in t}")
    print(f"   run_one_seq 用 name_for_seq : {'nm = name_for_seq(seq)' in t}")
print("=" * 70)
