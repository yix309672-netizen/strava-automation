# -*- coding: utf-8 -*-
"""改造后总验收（只读，不修改项目任何文件）
用法: python -X utf8 _verify_after.py
"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASS, FAIL, WARN = [], [], []


def ck(cond, name, detail=""):
    (PASS if cond else FAIL).append(f"{name} {detail}".strip())


def warn(cond, name, detail=""):
    if not cond:
        WARN.append(f"{name} {detail}".strip())


def src(p):
    f = ROOT / p
    return f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""


print("=" * 74)
print("A. 编译检查")
print("=" * 74)
FILES = ["主脚本/strava_ads.py", "主脚本/strava_bit.py", "界面/ADS自动化.py",
         "界面/比特派自动化.py", "claim_client.py", "claim_store.py",
         "update.py", "发布更新.py", "_验收_200.py", "_从中心捞回.py", "_真机实跑.py"]
for f in FILES:
    fp = ROOT / f
    if not fp.exists():
        warn(False, f"文件不存在: {f}")
        continue
    # ★ 进程内 compile(): 不起子进程、不抓管道(受限环境下 subprocess+pipe 会挂),
    #   也不写 __pycache__, 纯只读。
    try:
        compile(fp.read_text(encoding="utf-8", errors="replace"), str(fp), "exec")
        ck(True, f"语法编译 {f}")
    except SyntaxError as e:
        ck(False, f"语法编译 {f}", f"第 {e.lineno} 行: {e.msg}")

print()
print("=" * 74)
print("B. 引擎：任务上下文（用户硬需求 a）")
print("=" * 74)
for eng in ["主脚本/strava_ads.py", "主脚本/strava_bit.py"]:
    s = src(eng)
    for fn in ["new_task_ctx", "new_account_ctx", "append_task_url", "finalize_task",
               "_out_index", "_open_task_file", "TASK_FILE_PREFIX"]:
        ck(fn in s, f"{eng} 含 {fn}")
    ck("collected_users_" in s, f"{eng} 任务文件前缀")
    ck(bool(re.search(r"%Y%m%d_%H%M%S", s)), f"{eng} 时间戳格式 %Y%m%d_%H%M%S")
    ck("任务开始" in s, f"{eng} 任务头含任务开始时间")
    ck("range(50)" in s, f"{eng} 文件名重试有上限(50)")
    ck("def name_for_seq" in s, f"{eng} 含 name_for_seq(预览与执行同口径)")
    # 历史总表必须被索引扫到（否则 2586 行里的 959 重复仍会被重写）
    ck("cands.append(COLLECT_OUT)" in s or "COLLECT_OUT.exists()" in s,
       f"{eng} _out_index 覆盖历史总表")

print()
print("=" * 74)
print("C. 引擎：审计确认的致命修复")
print("=" * 74)
ads, bit = src("主脚本/strava_ads.py"), src("主脚本/strava_bit.py")
ck(bool(re.search(r"int\(str\(per_batch\)", ads)), "ADS per_batch 转 int（上传 100% 失败修复）")
ck(bool(re.search(r"int\(str\(daily_cap\)", ads)), "ADS daily_cap 转 int")
warn(bool(re.search(r"int\(str\(per_batch\)", bit)), "BIT per_batch 转 int（待确认）")
ck(ads.count("except UserStopped:\n            raise") + ads.count("except UserStopped:") >= 4 if False else ads.count("except UserStopped") >= 5,
   "ADS 放行 UserStopped ≥5 处", f"实际 {ads.count('except UserStopped')}")
ck("timeout=5" in ads and "Page.captureScreenshot" in ads, "ADS CDP 截图硬超时")
ck("has been closed" in ads, "ADS goto_retry 死页面快速失败")
ck("_allow_stop" in ads, "ADS ads_req _allow_stop（停止后仍能关干净）")
ck("_SEEN_LOCK" in ads, "ADS save_seen 加锁")
ck("CONCURRENCY_HINT" in ads, "ADS 并发时禁用网速缩放")
ck(ads.count("def save_seen") == 1, "ADS save_seen 单点定义")
ck("disk.update(seen" in ads, "ADS save_seen 是合并写不是覆盖")

print()
print("=" * 74)
print("D. 引擎：第二批（风控闸门 / 死地区 / 提速常量）")
print("=" * 74)
for eng, s in (("ADS", ads), ("BIT", bit)):
    warn("def rate_gate" in s, f"{eng} rate_gate 已落地")
    warn(s.count('rate_gate("') >= 4, f"{eng} rate_gate 调用 ≥4 处", f"实际 {s.count('rate_gate(') - 1}")
    warn("collect_max_minutes" in s, f"{eng} 单号全局时间预算")
    warn("_dry" in s, f"{eng} 死地区跳过")
    warn("ENOUGH_SEGMENTS = 12" in s, f"{eng} ENOUGH_SEGMENTS=12(采样目标)")
    # ★ 2026-09-19 用户要求"精准找每个州人数最多的路段"
    ck("seg_cands" in s and "_ranked = sorted(" in s,
       f"{eng} 选路段按运动达人数排名(不再先到先得)")
    ck("运动达人" in s, f"{eng} 达人数读取支持中文界面")
    warn("PAN_ROUNDS = 8" in s, f"{eng} PAN_ROUNDS=8")
    # ★ 精确断言(代理 D 指出前一版是"误通过": 旧写法只 grep "timeout=8000",
    #   命中的其实是 def exact_btn(..., timeout=8000) 的默认值, 不是截图超时)
    ck("page.screenshot(timeout=8000)" in s, f"{eng} 截图超时精确降到 8000")
    ck("page.screenshot(timeout=20000)" not in s, f"{eng} 已无 20000 截图超时")
    # ★ CDP 截图绝不能用线程池包(Playwright 同步 API 跨线程会 100% 失败)
    #   注意: 必须先把注释行剔掉再判 —— _cdp_grab 里那段注释本身就在讲
    #   "为什么不要用 ThreadPoolExecutor", 直接 grep 会误判成还在用。
    if "def _cdp_grab" in s and "def find_markers" in s:
        _b = s.split("def _cdp_grab", 1)[1].split("def find_markers", 1)[0]
        _code = "\n".join(l for l in _b.splitlines() if not l.lstrip().startswith("#"))
        ck("ThreadPoolExecutor" not in _code,
           f"{eng} _cdp_grab 未使用线程池(同步 API 跨线程不可用)")
    ck('sess.send("Page.captureScreenshot"' in s, f"{eng} CDP 截图是直调")
    # ★ 空地区判定不能把"截图失败(未知)"算进去
    ck("if mk is not None and len(mk) == 0 and best_n <= 0:" in s,
       f"{eng} 空地区判定排除 mk is None(未知≠零标记)")
    # ★ 选路段等待条件: 不能用恒为真的 location.href 正则
    ck('"!!/athletes|segments/.test(location.href)"' not in s,
       f"{eng} 已修掉恒为真的 segpop 等待条件")
    #   .test(h) 只出现在两处: segment_from_popup 的 JS + 新加的 segpop 等待条件。
    #   改造前只有 1 处 -> >=2 就证明等待条件已换成"弹窗里的路段链接"。
    ck(s.count(".test(h)") >= 2, f"{eng} segpop 等待条件改为弹窗路段链接",
       f".test(h) 命中 {s.count('.test(h)')}")
    # ★ 停顿看门狗(对付没有超时的 CDP 调用)
    ck("STALL_EXIT_SEC" in s and "_stall_watchdog" in s and "_arm_watchdog" in s,
       f"{eng} 停顿看门狗已落地")
    ck("_STALL[\"beat\"] = time.time()" in s, f"{eng} check_stop 打心跳")
    # ★ "落盘失败"与"历史已有"必须是可区分的两种 False
    ck('ctx["write_err"]' in s, f"{eng} append_task_url 区分落盘失败")
    ck('_sub.get("write_err")' in s, f"{eng} 落盘失败时不向中心报 pass")
    # ★ 2026-09-19: 登录误判修复 —— 标签页停在 /login 时不能直接判未登录
    ck("_looks_login" in s and "其余情况必须实地验证" in s,
       f"{eng} is_logged_in 修掉『停在登录页就判未登录』")
    ck("访问/login后" in s, f"{eng} 登录判定把判据URL打进日志")
    # ★ 数据完整性
    ck("落盘失败" in s and "write_err" in s, f"{eng} 落盘失败与判重可区分")
    # ★ 号级明细按编号命名(否则成品会被挤到 _2)
    ck('new_account_ctx(task, seq or "")' in s, f"{eng} 号级明细带编号")
    ck("seq=seq" in s and "seq=win" in s, f"{eng} 两条入口都透传编号")
    # ★ 2026-09-19 用户要求: 取消"只查前 40 人"的候选人安全上限
    #   注意断言要精确: "_batch" 会误匹配 per_batch, 所以查真正的截断写法。
    ck("rows[:CAND_SAFETY_CAP]" not in s and "_batch = rows[:"
       not in s, f"{eng} 候选人截断已取消")
    ck("enumerate(rows)" in s or "enumerate(_pend)" in s, f"{eng} 候选人全量遍历")
    ck("CAND_SAFETY_CAP = 40" not in s, f"{eng} 候选人上限 40 已取消")

print()
print("=" * 74)
print("E. 界面")
print("=" * 74)
for gui in ["界面/ADS自动化.py", "界面/比特派自动化.py"]:
    s = src(gui)
    ck("with cf.ThreadPoolExecutor" not in s, f"{gui} 不再用 with ThreadPoolExecutor（防界面永久卡死）")
    ck("cf.wait(" in s, f"{gui} 有界等待")
    ck("shutdown(wait=False)" in s, f"{gui} 非阻塞关闭线程池")
    ck("os.replace(" in s, f"{gui} 结果文件原子写")
    ck("btn_load" in s, f"{gui} 加载按钮可禁用")
    ck("running" in s and "scanning" in s, f"{gui} 运行中守卫")
    ck("finalize_task" in s, f"{gui} 任务汇总接线")
    ck("new_task_ctx" in s, f"{gui} 任务上下文接线")
    # ★ 2026-09-19: 扫描不再用空值覆盖已有数据(审计功能2 的老毛病)
    ck("_empty" in s and "保留原值" in s, f"{gui} 扫描只写非空值, 不覆盖已有数据")

print()
print("=" * 74)
print("F. 去重收口（用户硬需求 b）")
print("=" * 74)
cc = src("claim_client.py")
ck('_TERMINAL = ("pass", "reject", "done")' in cc, "claim_client _TERMINAL 定义")
ck("in _TERMINAL" in cc, "claim_client 读侧按终态过滤")
# ★ 精确断言: 真正的病是"直接拿缓存里的值做真值判断"。改成检查 local_known 的
#   取值+判断两行是否配套 —— 早先那条 `"if v:" not in src` 是误报:
#   claim_batch 里那句 `if v:` 的 v 来自已修好的 local_known(), 语义是对的。
ck('v = self._cache.get(str(aid))' in cc and
   'if v and (v.get("status") in _TERMINAL)' in cc,
   "claim_client local_known 配对判断终态(不是裸 if v:)")

print()
print("=" * 74)
print("G. 功能验证：任务文件真的会被建出来吗（临时目录实跑）")
print("=" * 74)
try:
    import importlib.util
    os.environ.setdefault("STRAVA_WORKER", "VERIFY")
    spec = importlib.util.spec_from_file_location("_eng_ads", str(ROOT / "主脚本" / "strava_ads.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["_eng_ads"] = m
    spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        m.COLLECT_OUT = td / "collected_users.txt"
        m._OUT_HAVE["built"] = False
        m._OUT_HAVE["set"] = set()
        t = m.new_task_ctx(target=200, mode="verify", worker="VERIFY")
        sub = m.new_account_ctx(t, 3)
        u1 = "https://www.strava.com/athletes/111"
        u2 = "https://www.strava.com/athletes/222"
        r1 = m.append_task_url(sub, u1, extra="111\tNew York\t999\t65_69")
        r2 = m.append_task_url(sub, u2)
        r3 = m.append_task_url(sub, u1)          # 重复: 必须被拦
        fin = m.finalize_task(t)
        ck(r1 is True and r2 is True, "新链接写入返回 True")
        ck(r3 is False, "重复链接被拦（返回 False，不计数）")
        files = sorted(p.name for p in td.glob("collected_users_*.txt"))
        ck(any(re.fullmatch(r"collected_users_\d{8}_\d{6}\.txt", f) for f in files),
           "生成任务成品 collected_users_<YYYYMMDD>_<HHMMSS>.txt", str(files))
        ck(any(re.fullmatch(r"collected_users_\d{8}_\d{6}_3\.txt", f) for f in files),
           "生成号级明细 collected_users_<tid>_3.txt", str(files))
        taskfile = [p for p in td.glob("collected_users_*.txt") if not p.name.endswith("_3.txt")][0]
        head = taskfile.read_text(encoding="utf-8").splitlines()
        ck(head[0].startswith("# 任务开始"), "成品首行是任务开始时间", head[0][:60])
        # ★ 2026-09-19 用户要求"只保留链接即可, 其他信息不需要":
        #   数据行必须是纯 URL(不带制表符附加列), 且不再有"任务结束/号数"那些注释行。
        ck(all("\t" not in x for x in head), "任务文件里没有制表符附加列(纯链接)")
        ck(not any(x.startswith("# 任务结束") for x in head), "任务文件里没有'任务结束'等额外信息")
        body = [x for x in head if x.startswith("https://")]
        ck(len(body) == 2, "成品里只有 2 条（重复被拦）", f"实际 {len(body)}")
        subhead = (td / [f for f in files if f.endswith("_3.txt")][0]).read_text(encoding="utf-8").splitlines()
        ck(subhead[0].startswith("# 任务开始"), "号级明细首行是任务开始时间", subhead[0][:60])
        ck(all("\t" not in x for x in subhead), "号级明细也是纯链接(无附加列)")
        total = (td / "collected_users.txt").read_text(encoding="utf-8").splitlines()
        ck(len([x for x in total if x.strip()]) == 2, "历史总表被合并为 2 条", f"实际 {len(total)}")
        # 第二次任务: 历史里去过的绝不再写
        m._OUT_HAVE["built"] = False
        t2 = m.new_task_ctx(mode="verify2")
        sub2 = m.new_account_ctx(t2, 3)
        ck(m.append_task_url(sub2, u1) is False, "第二次任务里历史已有的链接仍被拦（跨任务去重）")
        ck(m.append_task_url(sub2, "https://www.strava.com/athletes/333") is True,
           "第二次任务里全新的链接可以写")
except Exception as e:
    import traceback
    FAIL.append(f"任务文件实跑失败: {e}")
    traceback.print_exc()

print()
print("=" * 74)
print("H. 打包口径（防成果泄露）")
print("=" * 74)
for f, pat in (("update.py", "collected_users_"), ("发布更新.py", "collected_users_"),
               ("_分发给同事/update.py", "collected_users_")):
    warn(pat in src(f), f"{f} 保护/排除清单含 {pat}")

print()
print("=" * 74)
print(f"结果: PASS={len(PASS)}  FAIL={len(FAIL)}  WARN(未做/待确认)={len(WARN)}")
print("=" * 74)
if FAIL:
    print("\n--- FAIL 明细 ---")
    for x in FAIL:
        print("  [FAIL]", x)
if WARN:
    print("\n--- WARN 明细（第二批或待确认项）---")
    for x in WARN:
        print("  [WARN]", x)
print("\n--- PASS 明细 ---")
for x in PASS:
    print("  [ok]", x)
sys.exit(1 if FAIL else 0)
