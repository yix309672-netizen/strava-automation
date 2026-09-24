# -*- coding: utf-8 -*-
"""更新链路支持子目录 —— 第 1 步: 发布端(发布更新.py)。

背景: 包里现在有 sv_ttk/ 子目录(10 个文件), 但发布端只收顶层文件,
      于是主题发不到同事那边; 更糟的是【服务端 manifest 会拍平】,
      和 zip 里保留的子目录路径对不上 -> 子目录永远建不起来,
      反而在根目录撒出 __init__.py。

★ 子代理报告给出的关键点(我逐一核对过):
  · 第 129 行 z.writestr(f.name, data) —— 【只改收集逻辑不改这行等于白改】,
    zip 仍是扁平的, 而且 sv_ttk/sv.tcl 会和未来任何 */sv.tcl 撞成同名条目互相覆盖
  · EXCLUDE 现在是按【基名】匹配的, 改成 rglob 后必须改按【相对路径】匹配,
    否则 sv_ttk/__pycache__/xxx.pyc 的基名不含 "__pycache__" 子串 -> 混进包

改法: 用 rglob 收文件, 用【相对 PKG 的路径】做排除与 zip 条目名。
"""
import pathlib
import py_compile

P = pathlib.Path("发布更新.py")
s = P.read_text(encoding="utf-8")
print("=" * 76)
print("发布更新.py")

# ---- ① 收集: iterdir -> rglob, 按相对路径排除 ----
OLD = '''    files = []
    for f in sorted(PKG.iterdir()):
        if not f.is_file():
            continue
        if any(x in f.name for x in EXCLUDE):
            continue
        files.append(f)'''
NEW = '''    # ★★ 2026-09-20 支持子目录(sv_ttk/ 这类) ★★
    #   · 用 rglob 收【所有层级】的文件, 而不是 iterdir 只看顶层
    #   · 排除改成按【相对路径】匹配 —— 按基名匹配会漏掉
    #     sv_ttk/__pycache__/x.pyc 这种(它的基名里没有 "__pycache__")
    #   · files 存 (绝对路径, zip 条目名) —— 条目名就是相对路径, 带 /
    files = []
    for f in sorted(PKG.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(PKG).as_posix()          # 统一用 / (zip 规范)
        if any(x in rel for x in EXCLUDE):
            continue
        files.append((f, rel))'''
if OLD in s:
    s = s.replace(OLD, NEW)
    print("  ✓ 收集改成 rglob + 相对路径排除")
else:
    print("  ★ 收集逻辑没匹配到")

# ---- ② 打包: writestr 用相对路径(核心一行) ----
OLD2 = '''        for f in files:
            data = f.read_bytes()'''
NEW2 = '''        for f, rel in files:
            data = f.read_bytes()'''
if OLD2 in s:
    s = s.replace(OLD2, NEW2)
    print("  ✓ 体检循环改成解包 (f, rel)")
else:
    print("  ★ 体检循环没匹配到")

OLD3 = '''            z.writestr(f.name, data)'''
NEW3 = '''            # ★ 关键: 必须写【相对路径】, 不能写 f.name ——
            #   写 f.name 会让 zip 里全是扁平名, 子目录结构和 __init__.py 全丢,
            #   而且 sv_ttk/sv.tcl 会和别的 */sv.tcl 撞成同名条目互相覆盖。
            z.writestr(rel, data)'''
if OLD3 in s:
    s = s.replace(OLD3, NEW3)
    print("  ✓ writestr 改用相对路径(核心修复)")
else:
    print("  ★ writestr 没匹配到")

# ---- ③ 报告文件名时用相对路径 ----
s = s.replace('log("  文件  : %d 个" % len(files))',
              'log("  文件  : %d 个(含子目录)" % len(files))')

P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
    print("  语法 OK")
except Exception as e:
    print("  ★ 语法失败: %s" % str(e)[:180])

# ---- ④ 确认没有其它地方还在用 f.name ----
import re
left = [l.strip()[:90] for l in s.splitlines()
        if re.search(r"\bf\.name\b", l) and "#" not in l.split("f.name")[0]]
print()
print("  残留的 f.name 用法: %s" % (left if left else "无 ✓"))
