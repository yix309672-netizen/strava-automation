# -*- coding: utf-8 -*-
"""根治: 引擎/界面里写死的 _ADMIN_POLICY 会覆盖你正在用的配置。

★ 实测链条(已复现):
    包里 config.json: min_athletes = 2000
    跑一次引擎  ->  ★ 已按管理员口径纠正 config.json: min_athletes
    之后:            min_athletes = 5000     ← 你的设置被吃掉了

★ 为什么会这样:
    _ADMIN_POLICY 是为【老包遗留的 12州/每段200】准备的"一次性纠正",
    但值写死了(5000 / New York), 而且判断条件是 _policy_rev 落后 ——
    于是只要你把口径改成别的值, 且版本号没同步, 下一次启动就被覆盖回来。

★ 修法(两层都要改):
    ① 判断改成【只纠正确实是老遗留的值】, 而不是无条件覆盖:
         collect_regions: 只有恰好是那串老 12 州 才纠正
         min_athletes:    只有低于硬地板(200)才纠正
    ② _ADMIN_POLICY 里的值不再是"要写进去的目标值", 而是"用来识别的老值"
"""
import pathlib
import py_compile
import re

# ---- 引擎里的那份 ----
OLD_ENG = '''    fixed = {k: v for k, v in _ADMIN_POLICY.items() if CFG.get(k) != v}
    CFG = dict(CFG)
    CFG.update(fixed)
    CFG["_policy_rev"] = _ADMIN_POLICY_REV'''

NEW_ENG = '''    # ★★ 2026-09-20 修: 以前这里【无条件】把 CFG 改成 _ADMIN_POLICY 里
    #   写死的那份(5000 / New York)。实测后果:
    #       包里 config.json 是 min_athletes=2000
    #       跑一次引擎 -> "已按管理员口径纠正 config.json: min_athletes"
    #                  -> 变成 5000     ← 管理员自己改的值被吃掉了
    #   现在只纠正【确实属于老包遗留】的值, 不碰正在用的口径:
    #     · collect_regions: 恰好是那串老 12 州 才纠正
    #     · min_athletes:    低于硬地板(200)才纠正
    _LEGACY_12 = ["New York", "Indiana", "Michigan", "Wisconsin", "Iowa",
                  "Missouri", "Ohio", "Kentucky", "Minnesota",
                  "Tennessee", "West Virginia", "Pennsylvania"]
    fixed = {}
    _cur = [str(x) for x in (CFG.get("collect_regions") or [])]
    if sorted(_cur) == sorted(_LEGACY_12):
        fixed["collect_regions"] = ["New York"]
    for _k in ("min_athletes",):
        try:
            _v = int(CFG.get(_k) or 0)
        except Exception:
            _v = 0
        if 0 < _v < 200:
            fixed[_k] = 200
    CFG = dict(CFG)
    CFG.update(fixed)
    CFG["_policy_rev"] = _ADMIN_POLICY_REV'''

for eng in ("主脚本/strava_ads.py", "主脚本/strava_bit.py"):
    P = pathlib.Path(eng)
    s = P.read_text(encoding="utf-8")
    print("=" * 74)
    print(P.name)
    if OLD_ENG in s:
        s = s.replace(OLD_ENG, NEW_ENG)
        print("  ✓ enforce_admin_policy 改成只纠正老遗留值")
    elif "_LEGACY_12" in s:
        print("  · 已改过")
    else:
        print("  ★ 没匹配到 enforce_admin_policy 的覆盖段")
    P.write_text(s, encoding="utf-8")
    try:
        py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
        print("  语法 OK")
    except Exception as e:
        print("  ★ 语法失败: %s" % str(e)[:160])

# ---- 界面里那份(上一轮改过, 但要确认改的是不是同一个模式) ----
print()
print("=" * 74)
for gui in ("界面/ADS自动化.py", "界面/比特派自动化.py"):
    P = pathlib.Path(gui)
    s = P.read_text(encoding="utf-8")
    has_legacy = "_LEGACY_12" in s
    has_hard = bool(re.search(r'self\._min_ath = int\(_ADMIN_POLICY\["min_athletes"\]\)', s))
    print("  %-24s 用 _LEGACY_12: %s   还有硬覆盖: %s"
          % (pathlib.Path(gui).name, "是" if has_legacy else "否",
             "★ 是" if has_hard else "否"))

print()
print("=" * 74)
print("同步到分发包")
print("=" * 74)
