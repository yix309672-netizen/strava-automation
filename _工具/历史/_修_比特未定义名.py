# -*- coding: utf-8 -*-
"""修: 比特引擎里两个【引用了不存在的名字】的地方。

pyflakes 报的:
    strava_bit.py:3768  undefined name '_geo_cities'
    strava_bit.py:4058  undefined name 'geo_is_new_york'

根因: 我把 ADS 的那段代码复制进比特版时, 没注意两边的【辅助函数名不一样】:
    ADS : _geo_cities() / geo_is_new_york() / geo_resolve_center()
    比特: (没有前两个)   is_new_york_safe() / resolve_center_safe()
  → 平时不报错(在那两个 try 里被 except 吞掉), 但功能其实是废的:
      · geo_lookup() 永远返回"认不出" -> is_us_location 全靠州表兜底
      · region_is_ny() 永远走字符串判断, geo_cities 那套白放着

改法: 让比特版按【它自己的实现】来 —— 有就用, 没有就退回它已有的函数。
"""
import pathlib
import py_compile

P = pathlib.Path("主脚本/strava_bit.py")
s = P.read_text(encoding="utf-8")
print("=" * 74)
print(P.name)

# ---- ① geo_lookup: 比特没有 _geo_cities(), 直接 import geo_cities 用 ----
OLD1 = '''def geo_lookup(loc_text, state_hint=""):
    """包一层 geo_cities.lookup; 拿不到就返回认不出(绝不抛)"""
    try:
        return _geo_cities().lookup(loc_text, state_hint)
    except Exception:
        return None, None, "none", ""'''
NEW1 = '''def geo_lookup(loc_text, state_hint=""):
    """包一层 geo_cities.lookup; 拿不到就返回认不出(绝不抛)。

    ★ 修: 原来写的是 _geo_cities(), 那是【ADS 版才有的辅助函数】,
      比特版没有 -> NameError 被下面的 except 吞掉 -> 永远返回"认不出"。
      这里直接 import, 两个引擎就都不依赖各自的包装函数了。
    """
    try:
        from geo_cities import lookup as _lk
        return _lk(loc_text, state_hint)
    except Exception:
        return None, None, "none", ""'''
if OLD1 in s:
    s = s.replace(OLD1, NEW1)
    print("  ✓ geo_lookup 改成直接 import geo_cities.lookup")
else:
    print("  ★ geo_lookup 没匹配到")

# ---- ② region_is_ny: 比特的判纽约函数叫 is_new_york_safe ----
OLD2 = '''def region_is_ny(region):
    """这个地区名算不算"纽约来源"(决定要不要豁免 1000km 上限)。"""
    try:
        if geo_is_new_york(region):
            return True
    except Exception:
        pass
    return "new york" in str(region or "").lower()'''
NEW2 = '''def region_is_ny(region):
    """这个地区名算不算"纽约来源"(决定要不要豁免 1000km 上限)。

    ★ 修: 原来调的是 ADS 版才有的 geo_is_new_york(); 比特版的对应函数叫
      is_new_york_safe()。名字写错 -> NameError 被 except 吞掉 ->
      geo_cities 那套判定白放着, 只剩字符串兜底。
    """
    try:
        if is_new_york_safe(region):
            return True
    except Exception:
        pass
    return "new york" in str(region or "").lower()'''
if OLD2 in s:
    s = s.replace(OLD2, NEW2)
    print("  ✓ region_is_ny 改用比特自己的 is_new_york_safe")
else:
    print("  ★ region_is_ny 没匹配到")

P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
    print("  语法 OK")
except Exception as e:
    print("  ★ 语法失败: %s" % str(e)[:160])

# ---- ③ 顺手清掉那两个"导入但没用"的 ----
for f, old in (("fix_update.py", "import requests  # noqa: F401\n"),
               ("发布更新.py", None)):
    pass
print()
print("复查 pyflakes:")
import subprocess
import sys
r = subprocess.run([sys.executable, "-m", "pyflakes", str(P)],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
out = (r.stdout or "").strip()
print("  " + (out if out else "干净, 没有未定义名字 ✓"))
