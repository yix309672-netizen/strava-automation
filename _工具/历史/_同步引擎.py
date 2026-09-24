# -*- coding: utf-8 -*-
"""引擎同步: 把【两边逐行相同的函数】从 ADS 自动对齐到 Bit。

为什么这样做(而不是抽公共模块):
    这两个引擎是"一个程序的两份拷贝", 各自带一整套全局状态(CFG / log / ROOT /
    TASK_FILE_PREFIX ...)。那 58 个相同的函数依赖 126 个这样的全局名字, 硬抽
    common.py 会造成: ① 循环导入  ② 全局状态分裂(CFG 变成两个对象, 改一个
    另一个不知道 —— 正是之前花一整天才修好的那类 bug)  ③ 改动面失控。
    所以改成【单一真源 + 自动同步】: 两边都保留自己的函数, 但把"本来就该
    逐行相同"的那些自动对齐。收益是一样的(不会再出现"只改一边"), 风险接近零。

规则(严格):
    · 只处理【当前两边逐行相同】的函数 —— 本来就一样, 覆盖过去不改变任何行为
    · 有差异的函数【一律不碰】—— 它们要么是浏览器适配层(本该不同),
      要么是真差异, 需要人工判断
    · 默认【干跑】, 加 --go 才真写

用法:
    python _同步引擎.py          # 干跑: 打印哪些函数两边不一致(应该为空)
    python _同步引擎.py --go     # 真跑: 把 ADS 的同名函数覆盖到 Bit
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
A = ROOT / "主脚本" / "strava_ads.py"      # 真源
B = ROOT / "主脚本" / "strava_bit.py"      # 跟随方
GO = "--go" in sys.argv

# 这些函数【永远不参与同步】
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
}


def split_funcs(src):
    """切成 {函数名: (起止偏移, 文本)}, 只认顶层 def(行首无缩进)。"""
    out = {}
    for m in re.finditer(r"^def (\w+)\(", src, re.M):
        name = m.group(1)
        start = m.start()
        nxt = src.find("\ndef ", start + 1)
        end = nxt + 1 if nxt > 0 else len(src)
        out[name] = (start, end, src[start:end])
    return out


def main():
    sa = A.read_text(encoding="utf-8")
    sb = B.read_text(encoding="utf-8")
    fa, fb = split_funcs(sa), split_funcs(sb)

    def callees(txt):
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
        (stable if ok else skipped).append((n, why))
    # 有差异的(需要人工判断, 本脚本不碰)
    differs = sorted(n for n in fa
                     if n in fb and fa[n][2].strip() != fb[n][2].strip())

    print("=" * 74)
    print("引擎同步 %s" % ("【正式执行】" if GO else "【干跑】"))
    print("=" * 74)
    print("  %-26s %d 个函数" % ("ADS 顶层函数", len(fa)))
    print("  %-26s %d 个函数" % ("Bit 顶层函数", len(fb)))
    print("  %-26s %d 个" % ("可同步(逐行相同 + 依赖闭包安全)", len(stable)))
    if skipped:
        print("  %-26s %d 个" % ("已跳过(避免制造事故)", len(skipped)))
        for n, why in skipped[:12]:
            print("       %-22s %s" % (n, why))
        if len(skipped) > 12:
            print("       ...还有 %d 个" % (len(skipped) - 12))
    print("  %-26s %d 个" % ("有差异(本脚本不碰)", len(differs)))

    # ---- 检查: stable 里有没有两边其实不一致的(理论上不会有) ----
    bad = []
    for n, _w in stable:
        if fa[n][2].strip() != fb[n][2].strip():
            bad.append(n)
    if bad:
        print()
        print("  ★ 异常: 下面这些本该相同却不同, 请人工看: %s" % bad)

    # ---- 真正的动作: 把 ADS 的 stable 函数覆盖到 Bit ----
    changed = []
    if GO:
        new = sb
        for n, _w in stable:
            _s, _e, txt_a = fa[n]
            s2, e2, txt_b = fb[n]
            if txt_a == txt_b:
                continue                       # 逐字一致, 连注释都一样, 不用动
            # 只换函数体, 保留 Bit 那边的注释头(如果有差异只在注释)
            new = new[:s2] + txt_a + new[e2:]
            changed.append(n)
        if changed:
            B.write_text(new, encoding="utf-8")
        print()
        print("  已同步 %d 个函数(注释有差异的也一并对齐)" % len(changed))
        for n in changed[:40]:
            print("     " + n)
        if len(changed) > 40:
            print("     ...还有 %d 个" % (len(changed) - 40))
    else:
        # 干跑: 报告"注释层面还不一致"的有多少
        cos = [n for n, _w in stable if fa[n][2] != fb[n][2]]
        print()
        print("  其中【注释/空行】还不一致的有: %d 个" % len(cos))
        if cos:
            for n in cos[:30]:
                print("     " + n)
            if len(cos) > 30:
                print("     ...还有 %d 个" % (len(cos) - 30))
        print()
        print("  干跑结束。加 --go 真跑。")

    # ---- 语法检查 ----
    import py_compile
    print()
    for f in (A, B):
        try:
            py_compile.compile(str(f), doraise=True, cfile="__pycache__/x.pyc")
            print("  语法 OK  " + f.name)
        except Exception as e:
            print("  ★ 语法 FAIL %s: %s" % (f.name, str(e)[:160]))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
