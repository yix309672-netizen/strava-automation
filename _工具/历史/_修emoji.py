# -*- coding: utf-8 -*-
r"""修：Strava 用户名里的 emoji 把日志打崩

实跑日志里出现:
    --- Logging error ---
    UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f6b4'
    Message: '[region]   [NO] Victor  Boyce 🚴🏾 IB 私密'

原因: 引擎的 StreamHandler 写 sys.stdout, 而 stdout 是 GBK 控制台/管道时,
      编码不了 emoji(🚴🏽‍♀️🚴‍♂️ 之类) -> logging 报错, 那一行日志直接丢掉。
      Strava 用户名里带 emoji 很常见, 所以这不是偶发。

修法: 保留控制台原有编码(不乱码中文), 只把 errors 设成 replace,
      emoji 会变成 ? 但整行照样打出来, 不再报错、不再丢日志。
"""
import ast
import sys
from pathlib import Path

WS = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")

OLD = '''logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=['''

NEW = '''# ★ Strava 用户名里常带 emoji(🚴🏽‍♀️ 之类)。控制台是 GBK 时编码不了,
#   logging 会报 UnicodeEncodeError, 那一行日志直接丢掉。
#   这里保留控制台原编码(不乱码中文), 只把不可编码字符换成 ?,
#   这样整行照样打出来, 不再报错。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=['''


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


ok = True
for rel in ("主脚本/strava_ads.py", "主脚本/strava_bit.py"):
    p = WS / rel
    raw = p.read_bytes()
    lf, crlf = raw.count(b"\n"), raw.count(b"\r\n")
    nl = "\r\n" if (lf and crlf == lf) else "\n"
    t = raw.decode("utf-8").replace("\r\n", "\n")
    if OLD not in t:
        ok = False
        log("  [★] %s 没找到锚点" % rel)
        continue
    t = t.replace(OLD, NEW, 1)
    try:
        ast.parse(t)
    except SyntaxError as e:
        ok = False
        log("  ★ %s 语法错误: %s" % (rel, e))
        continue
    p.write_bytes(t.replace("\n", nl).encode("utf-8"))
    log("  [OK] %s  stdout/stderr 设为 errors=replace" % rel)

log("")
log("结果: %s" % ("完成" if ok else "★ 失败"))
sys.exit(0 if ok else 1)
