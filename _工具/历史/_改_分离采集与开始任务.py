# -*- coding: utf-8 -*-
"""一次性手术: 把「采集」从「开始任务」里摘出去, 只留给「只采集」。

背景(用户 2026-09-22 要求):
    「▶ 开始任务」应该只做 注册账号 / 改资料 / 上传轨迹;
    「◎ 只采集」才做采集。现实是点"开始任务"也会顺带采一轮。

改两处(两个引擎都要):
  A. run_one_seq 里那 90 行的采集块 -> 只留【会员状态 + 真实姓名/所在地】读取。
     采集部分(make_claim_client / collect_regions / mark_step)整段删掉。
     ★ 会员检测不能一起删: 表格里"会员"那一列靠它回填;
       而且 is_premium() 结束时页面正停在 /settings/profile, 顺手读姓名零成本。
  B. pending_todo 里不再往待办塞"采集" —— 否则"只差采集"的号会被判成还有活,
     白开一次浏览器(而那个浏览器开了也不会采了)。

★ 用脚本按【整块】替换, 不手抄 90 行: 手抄漏一个大括号就是把文件写坏。
"""
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# ---- A. run_one_seq 里的采集块 -> 只读状态 ----
A_START = "        # 会员检测:会员 -> 采集链接; 非会员 -> 跳过\n"
A_END = "    # 任务完成自动关闭浏览器(用户停止时也关)\n"
A_NEW = '''        # ★★ 2026-09-22 用户要求: 「▶ 开始任务」只做 注册/改资料/传轨迹, 【不采集】★★
        #   采集只归「◎ 只采集」那个按钮 —— 它走 collect_one(), 跟这里没关系。
        #   这一段原来在 collect_enabled 打开时会顺手采一轮, 于是点"开始任务"
        #   也会采, 和用户预期不符(make_claim_client / collect_regions 整段删了)。
        #   ★ 但【会员状态】和【真实姓名/所在地】必须留着:
        #     表格里"会员 / 姓名 / 城市"三列靠它回填, 而且 is_premium() 结束时
        #     页面正停在 /settings/profile, 顺手 read_settings_info 是零额外跳转。
        check_stop()
        if CFG.get("collect_enabled", True):
            page = repair()
            _prem = is_premium(page)
            # ★ 三态回填: True->是 / False->否 / None(读不到)->"?"
            #   界面把 "?" 当"本次读不到", 保留原来的值, 不会把已知的"是"冲掉。
            result["prem"] = ("是" if _prem is True
                              else ("否" if _prem is False else "?"))
            try:
                _ri = read_settings_info(page)
                _real_name = _ri.get("name") or _real_name
                _real_loc = _ri.get("location") or _real_loc
            except Exception:
                pass
            if _prem is False and page_alive(page):
                log.info(f"[skip] {win} 非会员(不采集, 要采集请用「◎ 只采集」)")

'''

# ---- B. pending_todo 里的"采集"待办 ----
B_OLD = '''    # 采集:每天一次(会员才真正执行)
    try:
        if CFG.get("collect_enabled", True):
            today = time.strftime("%Y-%m-%d")
            if st.get("collected") != today:
                todo.append("采集")
    except Exception:
        pass
    return todo
'''
B_NEW = '''    # ★★ 2026-09-22 用户要求: 「▶ 开始任务」不做采集, 采集只归「◎ 只采集」★★
    #   所以不再往待办里塞"采集" —— 否则一个"别的事都干完了、只差采集"的号,
    #   会被判成"还有活"而白开一次浏览器(开了也不会采了)。
    return todo
'''

ok = True
for f in ("主脚本/strava_ads.py", "主脚本/strava_bit.py"):
    p = ROOT / f
    src = p.read_text(encoding="utf-8")
    bak = p.with_name(p.name + f".bak_before_分离采集_{time.strftime('%Y%m%d_%H%M%S')}")

    i = src.find(A_START)
    j = src.find(A_END)
    if i < 0 or j < 0 or j < i:
        print(f"  ★ {f}: 采集块边界没找到 (start={i} end={j}) —— 跳过, 没动文件")
        ok = False
        continue
    block = src[i:j]
    if "collect_regions(" not in block or "make_claim_client(" not in block:
        print(f"  ★ {f}: 找到的块里没有 collect_regions/make_claim_client —— 不敢动")
        ok = False
        continue
    new = src[:i] + A_NEW + src[j:]

    if B_OLD not in new:
        print(f"  ★ {f}: pending_todo 的采集待办没找到 —— 不敢动")
        ok = False
        continue
    new = new.replace(B_OLD, B_NEW, 1)

    shutil.copy2(p, bak)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    # 语法先过一遍再落盘
    try:
        compile(new, str(p), "exec")
    except SyntaxError as e:
        tmp.unlink(missing_ok=True)
        print(f"  ★ {f}: 改完语法不过({e}) —— 已放弃, 原文件没动")
        ok = False
        continue
    import os
    os.replace(tmp, p)
    print(f"  OK {f}")
    print(f"     采集块 {block.count(chr(10))} 行 -> {A_NEW.count(chr(10))} 行")
    print(f"     剩余 collect_regions( 出现次数: {new.count('collect_regions(')}"
          f"  (collect_one 里应该还有 1 次)")
    print(f"     备份: {bak.name}")

print()
print("手术完成" if ok else "★ 有步骤失败, 见上")
sys.exit(0 if ok else 1)
