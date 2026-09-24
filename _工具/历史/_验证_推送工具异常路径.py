# -*- coding: utf-8 -*-
"""验证推送工具【四、发布结果】那段的异常路径: 网络抖一下也不会 NameError。

背景: 那段代码原来是
        try:
            ...
            ver = m.get("version")      # ← 只在 try 里赋值
        except Exception as e:
            log("复核失败")
        ...
        log(str(ver))                   # ← 第五节要用它
    只要 try 抛异常, ver 从头到尾没被赋值, 第五节就 NameError ——
    而这时候【包其实已经发布成功了】, 管理员看到满屏报错会以为推送失败。

做法: 把真实源码里那两节原样抽出来跑, 只把 urllib.request.urlopen 换成必然抛异常,
      看第五节能不能照常打印。不是重写一遍逻辑, 是跑真代码。
"""
import pathlib
import subprocess
import sys
import tempfile
import textwrap

# ★ 控制台/管道是 GBK 时, print 到 \ufffd 这类字符会 UnicodeEncodeError。
#   本脚本要打印被测程序的原始输出, 里面正好可能有替换字符 —— 必须兜底,
#   否则"验证脚本自己崩了", 看起来像被测工具有问题。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

TOOL = pathlib.Path(r"C:\Users\1\Desktop\一键推送更新.py")
ROOT = pathlib.Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")

src = TOOL.read_text(encoding="utf-8")

a = src.index('    log("四、发布结果")')
# ★ 必须用 rindex, 而且要连 'try:' 一起退掉:
#   1) 'input("按回车退出...")' 在文件里出现两次(前面"上传失败"分支也有一个),
#      用 index 会抓到前面那个, 抽出来的区间是空的;
#   2) 只切到 input 那一行会留下悬空的 'try:', 拼出来的测试脚本 IndentationError。
b = src.rindex('    try:\n        input("按回车退出...")')
block = textwrap.dedent(src[a:b])

if "ver = \"?\"" not in block:
    print("★FAIL 抽取到的代码里没有 'ver = \"?\"' —— 修复可能被回退了")
    raise SystemExit(1)
if block.index('ver = "?"') > block.index("try:"):
    print("★FAIL 'ver = \"?\"' 在 try 之后 —— 异常路径仍会 NameError")
    raise SystemExit(1)
print("OK   源码里 ver 的默认赋值在 try 之前")

harness = '''# -*- coding: utf-8 -*-
import json, pathlib, sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")      # 控制台是 GBK 时不让 print 崩
    except Exception:
        pass
ROOT = pathlib.Path(r"%s")
def log(m=""):
    print(m)
cmp = {"version": "AAAAAAAAAAAAAAAA"}

# 把网络调用弄坏, 模拟"网络抖一下"
import urllib.request as _u
def _boom(*a, **k):
    raise RuntimeError("network down (模拟网络抖动)")
_u.urlopen = _boom

%s

print()
print(">>> 第五节执行完, ver = %%r" %% (ver,))
assert ver == "?", "ver 应该是默认值 '?', 实际 %%r" %% (ver,)
print("✓ 异常路径没有 NameError, 第五节照常打印, 且 ver 安全降级为 '?'")
''' % (ROOT, block)

p = pathlib.Path(tempfile.gettempdir()) / "_push_tool_exc_test.py"
p.write_text(harness, encoding="utf-8")
r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
out = (r.stdout or "").strip()
print()
print(out[-1200:] if out else "(无输出)")
if r.returncode != 0:
    print("★FAIL 返回码 %d" % r.returncode)
    print((r.stderr or "")[-800:])
p.unlink()
raise SystemExit(r.returncode)
