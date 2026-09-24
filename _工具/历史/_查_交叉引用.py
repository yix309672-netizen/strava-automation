# -*- coding: utf-8 -*-
"""交叉引用体检: 界面 -> 引擎 的每一次调用、引擎 -> 配置 的每一个键, 全都对一遍。

为什么需要它: 界面和引擎是两个文件, 谁缺一个函数/键, 报错都发生在【点击那一刻】,
同事只会说"用不了"。这里一次性把四对关系全查出来, 不让问题一个个冒。
"""
import ast
import json
import re
import sys
from pathlib import Path


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

PKG = Path(sys.argv[1] if len(sys.argv) > 1 else
           r"C:\Users\1\Desktop\_模拟同事机\发给同事_脚本包_20260920_085635")
ENG = {"ads": "strava_ads.py", "bit": "strava_bit.py"}
GUI = {"ads": "_gui_ads.py", "bit": "_gui_bit.py"}
BAD = []


def src(n):
    return (PKG / n).read_text(encoding="utf-8", errors="replace")


def api(text):
    """一个文件里【定义】的名字 + 类属性"""
    t = ast.parse(text)
    out = set()
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    out.add(tg.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.Try):
            for sub in n.body + [x for h in n.handlers for x in h.body]:
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    out.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for tg in sub.targets:
                        if isinstance(tg, ast.Name):
                            out.add(tg.id)
    # 函数内部的定义也收(嵌套函数/内部类不常见, 但 import 常在函数里)
    for n in ast.walk(t):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
    return out


# ---------------------------------------------------------------- 1 界面调引擎
for k in ("ads", "bit"):
    g, e = src(GUI[k]), src(ENG[k])
    have = api(e)
    alias = re.findall(r"^(\w+)\s*=\s*importlib|module_from_spec\(\"(strava_\w+)\"", g, re.M)
    used = sorted({m for m in re.findall(r"\bS[AB]\.([A-Za-z_]\w*)", g)})
    for name in used:
        if name not in have:
            BAD.append(f"[{GUI[k]}] 调用引擎属性 S?.[{name}] —— {ENG[k]} 里没有")

# ---------------------------------------------------------------- 2 引擎读配置
# ★★ 2026-09-20 修(假报事故): 上一版把 `CFG["x"]` 一律当成"硬取必崩", 结果报了
#   18 条, 实测【全是假的】—— 其中
#     · CFG["_policy_rev"] = ...  是【赋值】(写), 不是读
#     · CFG["accounts_file"] 前面有 `if CFG.get("accounts_file"):` 保护
#   按那种报法去"修", 就是用户说的"AI 瞎改": 改的是没坏的东西。
#   现在: 赋值的键先剔除; 剩下的硬取只看【有没有配套的 CFG.get() 保护】,
#   有保护就只提示"疑似受保护", 不再当成必崩。
cfg = json.loads(src("config.json"))
for k in ("ads", "bit"):
    e = src(ENG[k])
    read_soft = set(re.findall(r"CFG\.get\(\s*[\"']([\w\u4e00-\u9fff]+)[\"']", e))
    sub_all = set(re.findall(r"CFG\[\s*[\"']([\w\u4e00-\u9fff]+)[\"']\s*\]", e))
    # 赋值目标(写) —— 从"读"里剔除
    written = set(re.findall(r"CFG\[\s*[\"']([\w\u4e00-\u9fff]+)[\"']\s*\]\s*(?:=[^=]|\+=|-=)", e))
    read_hard = sub_all - written
    for name in sorted(read_soft | read_hard):
        if name in cfg:
            continue
        if name in read_soft and name not in read_hard:
            tag = "可选(有默认值)"                       # 完全没问题
        elif name in read_soft:
            tag = "★需确认: 有硬取也有 get, 大概率被 if 保护"   # 人工看一眼
        elif name in written:
            tag = "只写不读(会自动补进 config)"            # 完全没问题
        else:
            tag = "★★真硬取, 没有 get 兜底 —— 值得人工确认"
        BAD.append(f"[{ENG[k]}] 配置键 {name} 不在 config.json ({tag})")

# ---------------------------------------------------------------- 3 两引擎漂移
a, b = api(src(ENG["ads"])), api(src(ENG["bit"]))
only_a = sorted(a - b - {"__doc__"})
only_b = sorted(b - a)
print(f"[两引擎] 只有 ADS 有: {len(only_a)} 个 -> {only_a}")
print(f"[两引擎] 只有 BIT 有: {len(only_b)} 个 -> {only_b}")

# ---------------------------------------------------------------- 4 界面字段闭环
for k in ("ads", "bit"):
    g = src(GUI[k])
    m = re.search(r"FIELDS\s*=\s*\(([^)]*)\)", g)
    fields = [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()] if m else []
    acct = PKG / f"{k}_accounts.json"
    data = json.loads(acct.read_text(encoding="utf-8"))
    print(f"[{GUI[k]}] FIELDS={fields}  账号文件类型={type(data).__name__} 条数={len(data)}")

print()
if BAD:
    print(f"★★★ 发现 {len(BAD)} 处问题 ★★★")
    for x in BAD:
        print("  -", x)
else:
    print("★★★ 交叉引用: 全部通过 ★★★")
