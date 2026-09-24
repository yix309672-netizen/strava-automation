# -*- coding: utf-8 -*-
"""回答用户的问题: 年龄选项选了之后, 是采一个年龄还是全采?

做法: 把界面下拉里的每一项, 原样喂给引擎的 _age_groups_of(), 看引擎最终
      会去查几个年龄组的榜单。这是端到端的(界面选项 -> 引擎实际行为)。
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "主脚本"))
import strava_ads as sa  # noqa: E402


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass


def load_gui(p):
    spec = importlib.util.spec_from_file_location("g", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["g"] = m
    spec.loader.exec_module(m)
    return m


print("=" * 84)
print("年龄选项 -> 引擎实际会查几个年龄组")
print("=" * 84)

for gui_p in (ROOT / "界面" / "ADS自动化.py", ROOT / "界面" / "比特派自动化.py"):
    g = load_gui(gui_p)
    print()
    print("--- %s ---" % gui_p.name)
    print("  %-38s %-6s %s" % ("下拉里显示", "采几个", "引擎实际用的年龄组"))
    print("  " + "-" * 80)
    for label, codes in g.AGE_CHOICES:
        # 界面存进 config 的就是 list(_value_of(...)) = list(codes)
        # 引擎再经 _age_groups_of 校验一遍
        got = sa._age_groups_of(list(codes))
        mark = "★" if len(got) > 1 else " "
        print("  %s %-36s %-6d %s" % (mark, label, len(got), list(got)))

print()
print("=" * 84)
print("结论")
print("=" * 84)
d = sa._age_groups_of(None)
print("  默认 = %d 个年龄组, 全部都会查 -> %s" % (len(d), list(d)))
print("  ★ 用户口径: 45-54 及以下已取消, 传进去也会被引擎剔掉:")
print("     _age_groups_of(('45_54','55_64')) ->",
       list(sa._age_groups_of(("45_54", "55_64"))))
print("  '只要 XX' 那几项 = 1 个, 只查那一个")
print()
print("  ★ 什么情况下会【提前收手】不再查后面的年龄组:")
print("     ① 这个号已经采够「每号目标人数」(默认200) —— 达标即停")
print("     ② 某个年龄组榜单返回空 —— 跳过它, 继续下一个(现在会打日志了)")
print("     ③ 所有路段都跑完")
print()
print("  ★ 年龄组本身【不会】三选一: 选中的几个就是几个, 顺次查。")
