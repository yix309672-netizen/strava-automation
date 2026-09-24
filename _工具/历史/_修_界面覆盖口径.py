# -*- coding: utf-8 -*-
"""修: 界面硬编码的 _ADMIN_POLICY 把你改的口径覆盖掉。

★ 症状(实测):
    配置里 min_athletes = 2000, 引擎也用的 2000
    但界面「每段≥」显示 5000, 而且【保存时会把 5000 写回 config.json】
    -> 你改的 2000 被自己的界面悄悄改回去

★ 根因:
    界面里有个"管理员口径一次性纠正"机制:
        if _policy_rev < _ADMIN_POLICY_REV:
            self._min_ath = int(_ADMIN_POLICY["min_athletes"])     # 写死 5000
            self._regions = list(_ADMIN_POLICY["collect_regions"]) # 写死 New York
    它本意是"把老包遗留的 12州/每段200 纠正过来", 但值是【硬编码】的。
    后来你把手改成了 2000 / 别的地区, 这套硬编码没跟着走 ——
    于是每次 _policy_rev 低于版本号, 它就把你的值覆盖回去。

★ 修法: _ADMIN_POLICY 只保留【真正需要一次性纠正的历史值】(12州/200),
  不再强行覆盖你现在正在用的口径。具体说:
    · collect_regions: 只有当配置里是那串【老的 12 州】时才纠正
    · min_athletes:    只有低于地板(如 200)时才纠正
  这样既治了老机器, 又不会覆盖你的新设置。
"""
import pathlib
import py_compile

OLD = '''        if _rev < _ADMIN_POLICY_REV:
            for _k, _v in _ADMIN_POLICY.items():
                if _rc.get(_k) != _v:
                    _fixed[_k] = _v
            self._regions = list(_ADMIN_POLICY["collect_regions"])
            self._min_ath = int(_ADMIN_POLICY["min_athletes"])
            _fixed["_policy_rev"] = _ADMIN_POLICY_REV'''

NEW = '''        if _rev < _ADMIN_POLICY_REV:
            # ★★ 2026-09-20 修: 这里以前是【无条件】把值改成 _ADMIN_POLICY 里
            #   写死的那份(5000 / New York)。于是你在界面上改成 2000 之后,
            #   只要 _policy_rev 落后, 界面就把它覆盖回 5000, 还会【写回磁盘】。
            #   现在改成【只纠正"确定是老的遗留值"】, 不动你现在正在用的口径:
            #     · collect_regions: 只有恰好是那串老 12 州 才纠正
            #     · min_athletes:    只有低于硬地板(200)才纠正
            #   这样老机器照样能被治好, 你的新设置不会被自己的界面吃掉。
            _LEGACY_12 = ["New York", "Indiana", "Michigan", "Wisconsin", "Iowa",
                          "Missouri", "Ohio", "Kentucky", "Minnesota",
                          "Tennessee", "West Virginia", "Pennsylvania"]
            _cur_regions = [str(x) for x in (_rc.get("collect_regions") or [])]
            if sorted(_cur_regions) == sorted(_LEGACY_12):
                self._regions = ["New York"]
                _fixed["collect_regions"] = ["New York"]
            try:
                _ma_now = int(_rc.get("min_athletes") or 0)
            except Exception:
                _ma_now = 0
            if 0 < _ma_now < 200:
                self._min_ath = 200
                _fixed["min_athletes"] = 200
            _fixed["_policy_rev"] = _ADMIN_POLICY_REV'''

for gui in ("界面/ADS自动化.py", "界面/比特派自动化.py"):
    P = pathlib.Path(gui)
    s = P.read_text(encoding="utf-8")
    print("=" * 74)
    print(P.name)
    if OLD in s:
        s = s.replace(OLD, NEW)
        print("  ✓ 不再无条件覆盖; 只纠正确实的老遗留值")
    elif "_LEGACY_12" in s:
        print("  · 已改过")
    else:
        print("  ★ 没匹配到")
    P.write_text(s, encoding="utf-8")
    try:
        py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
        print("  语法 OK")
    except Exception as e:
        print("  ★ 语法失败: %s" % str(e)[:180])

# ---- 修 ②: 一键检查.bat 里的文件名提示写错了 ----
bat = pathlib.Path("_生成_双击检查bat.py")
print()
print("=" * 74)
print("② 修 .bat 里的文件名提示(check_result -> 检查结果)")
s = bat.read_text(encoding="utf-8")
n = s.count("check_result_*.txt")
s = s.replace("check_result_*.txt", "检查结果_<机器名>_<时间>.txt")
bat.write_text(s, encoding="utf-8")
print("  改了 %d 处" % n)

# 打包脚本里的那份也要改
pk = pathlib.Path("_打包给同事.py")
s2 = pk.read_text(encoding="utf-8")
n2 = s2.count("check_result_*.txt")
s2 = s2.replace("check_result_*.txt", "CheckResult_<machine>_<time>.txt")
pk.write_text(s2, encoding="utf-8")
print("  打包脚本里改了 %d 处(那里必须是 ASCII, 用英文名)" % n2)
print()
print("  ★ 但两个名字必须统一! 让 检查.py 也输出一个 ASCII 名, 两边都对得上")
