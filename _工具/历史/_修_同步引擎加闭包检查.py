# -*- coding: utf-8 -*-
"""给 _同步引擎.py 加【依赖闭包检查】—— 同名不等于同义。

起因: 子代理的安全核查抓到一个会让自动同步【反而制造事故】的漏洞:
    geo_lookup 两边同名, 但实现不同:
        ADS : return _geo_cities().lookup(...)      # _geo_cities 是 ADS 独有
        BIT : from geo_cities import lookup         # 已经修好的写法
    如果同步工具"同名就覆盖", 就会把 ADS 那份刷进比特 ->
    _geo_cities 在比特不存在 -> NameError 被 except 吞掉 ->
    国别判定永远"认不出", 不报错, 极难发现(这正是之前踩过的那个坑)。

所以同步工具必须:
  ① 只同步【依赖闭包全部同名同义】的函数
  ② 显式拉黑那些"调用了同名异构辅助函数"的函数
  ③ 拉黑辅助函数本身(geo_lookup / goto_retry), 防止被整批覆盖踩回旧 bug
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
P = ROOT / "_同步引擎.py"
s = P.read_text(encoding="utf-8")
print("=" * 74)
print("给 _同步引擎.py 加依赖闭包检查")

# ---- ① 黑名单: 子代理核查确认的 8 个 ----
OLD_NEVER = '''# 这些函数【永远不参与同步】: 浏览器适配层, 两边本来就该不同
NEVER = {
    "main", "run_one", "collect_one", "scan_one", "list_items", "is_logged_in",
    "ads_req", "ads_list", "ads_find", "ads_open", "ads_close", "ads_active",
    "ads_close_all", "bb", "open_window", "minimize_pid", "find_window_id",
    "ads_headers", "auto_worker_id",
}'''
NEW_NEVER = '''# 这些函数【永远不参与同步】
NEVER = {
    # 浏览器适配层 —— 两边本来就该不同
    "main", "run_one", "collect_one", "scan_one", "list_items", "is_logged_in",
    "ads_req", "ads_list", "ads_find", "ads_open", "ads_close", "ads_active",
    "ads_close_all", "bb", "open_window", "minimize_pid", "find_window_id",
    "ads_headers", "auto_worker_id",
    # ★★ 2026-09-20 子代理安全核查确认的"同名异构"函数 ★★
    #   它们调用了【两边同名但实现不同】的辅助函数。单独复制不会 NameError
    #   (那个名字在对方那边存在), 但【语义会变且不报错】—— 比报错难查得多。
    #     · set_gender/set_privacy/set_profile/set_units/google_login
    #         都调 goto_retry(): ADS 有 goto_same 短路 + note_goto 记账 +
    #         backoff 指数退避; BIT 是固定 sleep。刷过去 -> 每次白等 4 次 goto。
    #     · is_us_location 调 geo_lookup(): 见下面那条注释, 刷过去会踩回旧 bug。
    "set_gender", "set_privacy", "set_profile", "set_units", "google_login",
    "is_us_location",
    # ★ 辅助函数本身也要拉黑 —— 否则"同名即覆盖"会把它们刷过去。
    #   geo_lookup: ADS 用 _geo_cities()(ADS 独有), BIT 已改成
    #               from geo_cities import lookup。刷过去 = 复现静默失效事故。
    #   goto_retry: 两边实现差 5 处, 且 ADS 版依赖 goto_same/note_goto(ADS 独有)。
    "geo_lookup", "goto_retry",
    # 同名异构的其它辅助函数(核查报告点名)
    "accept_cookies", "_net_scale",
}'''
if OLD_NEVER in s:
    s = s.replace(OLD_NEVER, NEW_NEVER)
    print("  ✓ 黑名单已扩充到 %d 个(含 8 个同名异构)")
else:
    print("  ★ 黑名单没匹配到")

# ---- ② 依赖闭包检查: 函数体内调用的每个名字, 两边都必须同名同义 ----
OLD_SEL = '''    # 该同步的 = 两边都有 + 逐行相同 + 不在 NEVER 里
    stable = sorted(n for n in fa
                    if n in fb and fa[n][2].strip() == fb[n][2].strip()
                    and n not in NEVER)'''
NEW_SEL = '''    def callees(txt):
        """这个函数体里调用了哪些名字(AST 级别的 Call.func 是 Name)"""
        import ast
        out = set()
        try:
            for node in ast.walk(ast.parse(txt)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    out.add(node.func.id)
        except Exception:
            pass
        return out

    def is_safe_to_copy(name):
        """★ 依赖闭包检查: 它调用的每个函数, 在两边必须【同名同义】。

        ★★ 为什么必须有这一步 ★★
          子代理核查抓到的漏洞: geo_lookup 两边同名但实现不同, 若"同名就覆盖",
          会把 ADS 那份(_geo_cities)刷进比特 -> NameError 被 except 吞掉 ->
          功能静默失效。所以"逐行相同"还不够, 必须看它调用了谁。
        """
        if name in NEVER:
            return False, "在黑名单里"
        calls = callees(fa[name][2])
        for c in calls:
            if c in NEVER:
                return False, "调用了同名异构的 %s()" % c
            # 调用了"对方有、自己没有"的函数 -> 复制过去会 NameError
            if c in fa and c not in fb:
                return False, "调用了 Bit 没有的 %s()" % c
            # 调用了两边都有的函数, 但那个函数本身两边实现不同 -> 语义会变
            if c in fa and c in fb and fa[c][2].strip() != fb[c][2].strip():
                # 剔除注释后再比一次: 只差注释的不算危险
                ca = [l.strip() for l in fa[c][2].splitlines()
                      if l.strip() and not l.strip().startswith("#")]
                cb2 = [l.strip() for l in fb[c][2].splitlines()
                       if l.strip() and not l.strip().startswith("#")]
                if ca != cb2:
                    return False, "调用了同名异构的 %s()" % c
        return True, ""

    # 该同步的 = 两边都有 + 逐行相同 + 黑名单外 + 依赖闭包安全
    stable, skipped = [], []
    for n in sorted(fa):
        if n not in fb or fa[n][2].strip() != fb[n][2].strip():
            continue
        ok, why = is_safe_to_copy(n)
        (stable if ok else skipped).append((n, why))'''
if OLD_SEL in s:
    s = s.replace(OLD_SEL, NEW_SEL)
    print("  ✓ 加入依赖闭包检查")
else:
    print("  ★ 选择逻辑没匹配到")

# ---- ③ 报告里带上被跳过的 ----
OLD_RPT = '''    print("  %-26s %d 个" % ("可同步(两边已逐行相同)", len(stable)))'''
NEW_RPT = '''    print("  %-26s %d 个" % ("可同步(逐行相同 + 依赖闭包安全)", len(stable)))
    if skipped:
        print("  %-26s %d 个" % ("已跳过(避免制造事故)", len(skipped)))
        for n, why in skipped[:12]:
            print("       %-22s %s" % (n, why))
        if len(skipped) > 12:
            print("       ...还有 %d 个" % (len(skipped) - 12))'''
if OLD_RPT in s:
    s = s.replace(OLD_RPT, NEW_RPT)
    print("  ✓ 报告里列出被跳过的")

# stable 现在是 (name, why) 元组的列表, 后面几处用法要跟着改
s = s.replace('''    bad = []
    for n in stable:
        if fa[n][2].strip() != fb[n][2].strip():
            bad.append(n)''',
              '''    bad = []
    for n, _w in stable:
        if fa[n][2].strip() != fb[n][2].strip():
            bad.append(n)''')
s = s.replace('''        new = sb
        for n in stable:
            _s, _e, txt_a = fa[n]''',
              '''        new = sb
        for n, _w in stable:
            _s, _e, txt_a = fa[n]''')
s = s.replace('''        cos = [n for n in stable if fa[n][2] != fb[n][2]]''',
              '''        cos = [n for n, _w in stable if fa[n][2] != fb[n][2]]''')

P.write_text(s, encoding="utf-8")
import py_compile
try:
    py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
    print("  语法 OK")
except Exception as e:
    print("  ★ 语法失败: %s" % str(e)[:200])
