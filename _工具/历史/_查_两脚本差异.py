# -*- coding: utf-8 -*-
"""找出为什么两个脚本对同一个包给出不同结果。

现象:
  _验_包内界面显示.py   -> min_ath=2000, shown='2000'   ✓
  _验证_同事拿到能用.py -> min_ath=5000, shown='5000...' ✗
差别只在脚本本身。逐个比它们做了什么不同的事。
"""
import pathlib
import re

A = pathlib.Path("_验_包内界面显示.py").read_text(encoding="utf-8")
B = pathlib.Path("_验证_同事拿到能用.py").read_text(encoding="utf-8")

print("=" * 78)
print("两个脚本的关键区别")
print("=" * 78)

print()
print("【A】(结果是 2000 的那个) 解压后怎么定位 base:")
for l in A.splitlines():
    if "extractall" in l or "base =" in l or "next(d" in l:
        print("   " + l.strip()[:96])

print()
print("【B】(结果是 5000 的那个) 解压后怎么定位 base:")
for l in B.splitlines():
    if "extractall" in l or "base =" in l or "sub = " in l or "len(sub)" in l:
        print("   " + l.strip()[:96])

print()
print("=" * 78)
print("★ 关键怀疑: B 解压到的目录里, 可能【有多个子目录】, 它挑错了")
print("=" * 78)
import zipfile
zips = sorted((pathlib.Path.home() / "Desktop").glob("发给同事_脚本包_*.zip"))
ZIP = zips[-1]
with zipfile.ZipFile(ZIP) as z:
    names = z.namelist()
tops = sorted({n.split("/")[0] for n in names if "/" in n})
print("  包里顶层条目: %s" % tops)
print("  只有 1 个顶层目录吗: %s" % ("是 ✓" if len(tops) == 1 else "★ 不止一个!"))

# 复刻 B 的定位逻辑
import tempfile, shutil


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
tmp = pathlib.Path(tempfile.mkdtemp(prefix="cmp_"))
with zipfile.ZipFile(ZIP) as z:
    z.extractall(tmp)
sub = [d for d in tmp.iterdir() if d.is_dir()]
print()
print("  解压后 tmp 下的目录: %s" % [d.name for d in sub])
print("  B 的逻辑: len(sub)==1 就用 sub[0], 否则用 tmp")
print("  -> B 会选: %s" % (sub[0].name if len(sub) == 1 else tmp.name))
print("  实际 base: %s" % (sub[0] if len(sub) == 1 else tmp))
# 那个 base 里有没有 config.json / _gui_ads.py
b = sub[0] if len(sub) == 1 else tmp
print()
print("  那个 base 里有 config.json 吗: %s" % (b / "config.json").is_file())
print("  那个 base 里有 _gui_ads.py 吗 : %s" % (b / "_gui_ads.py").is_file())
if (b / "config.json").is_file():
    import json
    c = json.loads((b / "config.json").read_text(encoding="utf-8"))
    print("  它的 min_athletes = %r" % c.get("min_athletes"))
shutil.rmtree(tmp, ignore_errors=True)
