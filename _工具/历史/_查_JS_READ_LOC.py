# -*- coding: utf-8 -*-
"""查 JS_READ_LOC 两边不一致会不会真出问题。

ADS : return {loc: s, kind: 'city'} / {loc:'', kind:'none'}
BIT : return {loc: s}               / {loc:''}
调用方都是 lr.get("loc"), 所以【看起来】兼容。
但要确认: 有没有地方读 kind? 没有就是无害差异(只该统一, 不必修逻辑)。
"""
import pathlib
import re


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

for f in ("主脚本/strava_ads.py", "主脚本/strava_bit.py"):
    s = pathlib.Path(f).read_text(encoding="utf-8")
    print("=" * 74)
    print(pathlib.Path(f).name)
    for m in re.finditer(r"JS_READ_LOC", s):
        i = m.start()
        line_no = s[:i].count("\n") + 1
        ctx = s[max(0, i - 200):i + 260].replace("\n", " ")
        print("  用到 L%d: ...%s..." % (line_no, ctx[-170:]))

print()
print("=" * 74)
print("查 kind 这个键有没有被读过")
print("=" * 74)
for f in ("主脚本/strava_ads.py", "主脚本/strava_bit.py",
          "界面/ADS自动化.py", "界面/比特派自动化.py"):
    s = pathlib.Path(f).read_text(encoding="utf-8")
    hits = [l.strip()[:90] for l in s.splitlines()
            if re.search(r"""["']kind["']""", l)]
    print("  %-24s %s" % (pathlib.Path(f).name, hits if hits else "(没有)"))
