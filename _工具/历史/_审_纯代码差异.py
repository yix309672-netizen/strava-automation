# -*- coding: utf-8 -*-
"""只比【代码】, 把注释和文档串全部去掉, 看两个引擎的纯逻辑到底差在哪。

这一步是为了回答: 那 36 个"同名不同实现"里, 有没有【真的逻辑差异】。
"""
import ast
import difflib
import io
import pathlib
import tokenize

ROOT = pathlib.Path(".")
A = ROOT / "主脚本" / "strava_ads.py"
B = ROOT / "主脚本" / "strava_bit.py"


def code_only_map(p):
    """函数名 -> 去掉注释/文档串后的代码行"""
    src = p.read_text(encoding="utf-8")
    lines = src.splitlines()
    # 用 tokenize 找出所有注释和字符串的位置, 打上占位
    drop = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                drop.add(tok.start[0])
    except Exception:
        pass
    t = ast.parse(src)
    out = {}
    for n in ast.walk(t):
        if not isinstance(n, ast.FunctionDef):
            continue
        # 剥掉 docstring 行号
        ds = n.body[0] if n.body else None
        ds_lines = set()
        if isinstance(ds, ast.Expr) and isinstance(ds.value, ast.Constant) \
                and isinstance(ds.value.value, str):
            ds_lines = set(range(ds.lineno, (ds.end_lineno or ds.lineno) + 1))
        body = []
        for ln in range(n.lineno, (n.end_lineno or n.lineno) + 1):
            if ln in drop or ln in ds_lines:
                continue
            body.append(lines[ln - 1].strip())
        out[n.name] = [x for x in body if x]
    return out


fa, fb = code_only_map(A), code_only_map(B)
common = sorted(set(fa) & set(fb))
same, diff = [], []
for n in common:
    (same if fa[n] == fb[n] else diff).append(n)

print("=" * 84)
print("去掉全部注释/文档串后, 两个引擎的【纯代码】对比")
print("=" * 84)
print("  共同函数: %d" % len(common))
print("  代码逐行相同: %d" % len(same))
print("  代码确有差异: %d" % len(diff))

print()
print("=" * 84)
print("确有代码差异的(逐个看, 判断是否合理)")
print("=" * 84)
for n in diff:
    d = [l for l in difflib.unified_diff(fa[n], fb[n], lineterm="", n=0)
         if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    print()
    print("  ── %s (%d 行差异) ──" % (n, len(d)))
    for l in d[:8]:
        print("     " + l[:112])
    if len(d) > 8:
        print("     ...还有 %d 行" % (len(d) - 8))
