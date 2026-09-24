# -*- coding: utf-8 -*-
"""把源码同步到 _分发给同事/ 并自检关键标记(一次性工具)"""
import hashlib
import json
import pathlib
import shutil
import sys

# ★ 控制台是 GBK: 标记里带 ▶ ★ ☆ 这类字符时 print 会直接崩(踩过好几次)。
#   把编码错误降级成替换字符, 别让"打印不出来"把整次发版拦下。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

root = pathlib.Path(__file__).resolve().parent
dist = root / "_分发给同事"


def h(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


PAIRS = [
    ("界面/ADS自动化.py", "_gui_ads.py"),
    ("界面/比特派自动化.py", "_gui_bit.py"),
    ("主脚本/strava_ads.py", "strava_ads.py"),
    ("主脚本/strava_bit.py", "strava_bit.py"),
    ("update.py", "update.py"),
    ("fix_update.py", "fix_update.py"),
    # ★★ 2026-09-20 补上 geo_cities.py ★★
    #   漏了它 = 改了地理库却发不出去。这次就是: 美国地名表从 17087 条补到
    #   52082 条(文件名 ./geo_cities.py), 结果发布包里还是旧的 813KB 版本,
    #   同事更新完拿到的仍是那张不全的表。
    #   (桌面 一键推送更新.py 的 SYNC_MAP 里本来就有它, 这里是对齐。)
    ("geo_cities.py", "geo_cities.py"),
    # ★★ 2026-09-20 补上 name_bank.py ★★
    #   用户把 1000 个名字交给脚本之后, 引擎是 `from name_bank import NAMES`
    #   去读它的。漏了它 = 同事那边 import 不到 -> 静默退回内置的 50 个名字,
    #   而且【不报错】—— 属于"改了却发不出去"的那一类, 必须一起同步。
    ("主脚本/name_bank.py", "name_bank.py"),
    # ★★ 2026-09-24 补上 app_version.py ★★
    #   界面标题栏和引擎日志都要显示版本号, 真源就这一个文件。漏了它 =
    #   同事那边 import 不到 -> 兜底成 "v?" -> 标题栏空白, 又回到
    #   "说不上来自己跑的是哪一版" 的老问题。和 geo_cities/name_bank 同类。
    ("主脚本/app_version.py", "app_version.py"),
]

print("=== 同步源代码 -> 分发目录 ===")
for src, dst in PAIRS:
    s, d = root / src, dist / dst
    before = h(d) if d.exists() else "(新文件)"
    shutil.copy2(s, d)
    print("  %-20s -> %-18s %9d B   %s -> %s"
          % (src, dst, d.stat().st_size, before, h(d)))

cp = dist / "config.json"
c = json.loads(cp.read_text(encoding="utf-8"))
# ★★ 绝不能让 _policy_rev 出现在分发包里 ★★
#   老机器的旧 update.py 是"缺失的键就补上" —— 它会把这个键补进同事的配置;
#   新界面/新引擎再一看"版本号已经 >= 2", 就以为口径纠正过了直接跳过,
#   采集州会永远停在 12 个州。这个键必须由新代码自己写。
if "_policy_rev" in c:
    del c["_policy_rev"]
    print("  config.json ★ 已移除 _policy_rev(它只能由新代码自己写, 不能下发)")
cp.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("  config.json  -> regions=%s min=%s jobs=%s _policy_rev=%r key=%r"
      % (c.get("collect_regions"), c.get("min_athletes"), c.get("jobs"),
         c.get("_policy_rev"), c.get("adspower_key")))

print()
print("=== 新代码关键标记自检 ===")
MARKS = {
    "_gui_ads.py": ["_ADMIN_POLICY_REV = 2", "按管理员口径纠正配置", "os.replace(_tmp, _c)",
                    # ★ 会员三态: "?" 必须和 -1 一样被当成"本次读不到"
                    '"None", "-1", "?"',
                    # ★ 4 个下拉框(2026-09-19 用户要求)
                    "REGION_CHOICES", "AGE_CHOICES", "GENDER_CHOICES",
                    "DATE_CHOICES", "var_region", "_save_collect_choice",
                    # ★ 每段人数门槛下拉框(2026-09-19 用户要求)
                    "MIN_ATH_CHOICES", "var_minath",
                    # ★ 账号自动识别(2026-09-20 用户要求)
                    # ★★ 2026-09-20 晚: 用户又要求「备注恢复成原样, 移到后面去」,
                    #   列序变回 ...priv, note。原来这里查的 '"note", "email"'
                    #   就永远 MISS 了 —— 又一条过期标记(和 collect_regions 那次同款)。
                    #   改成查【备注确实在最后一列】, 跟当前口径一致。
                    '"priv", "note"', "note", "email",
                    # ★★ 2026-09-21: 密码列自愈(用户问"你确定修好了吗? 密码呢") ★★
                    #   错位时 password 被 login 覆盖成 是/否; 原来的自愈压根没管
                    #   这一列, 于是坏值一直赖着、还被存回账号文件, 把真密码冲掉。
                    #   这三条标记 = 三道闸, 少一道就又会丢密码。
                    "def _pwd_index(acc):",
                    'nv["password"] = idx.get(e, "")',
                    "if str(pwd).strip() in _YESNO:",
                    # ★★ 2026-09-22: 标签写明"不含采集"(用户就是被这个搞混的)
                    "执行内容(不含采集)"],
    "_gui_bit.py": ["_ADMIN_POLICY_REV = 2", "按管理员口径纠正配置", "os.replace(_tmp, _c)",
                    '"None", "-1", "?"',
                    "REGION_CHOICES", "AGE_CHOICES", "GENDER_CHOICES",
                    "DATE_CHOICES", "var_region", "_save_collect_choice",
                    "MIN_ATH_CHOICES", "var_minath",
                    # ★★ 2026-09-20 晚: 同 _gui_ads.py —— 备注挪回最后一列,
                    #   原来的 '"note", "email"' 标记已过期。
                    '"priv", "note"', "note", "email",
                    # ★★ 2026-09-21: 同 _gui_ads.py —— 密码列自愈三道闸
                    "def _pwd_index(acc):",
                    'nv["password"] = idx.get(e, "")',
                    "if str(pwd).strip() in _YESNO:",
                    # ★★ 2026-09-22: 标签写明"不含采集"(用户就是被这个搞混的)
                    "执行内容(不含采集)"],
    "strava_ads.py": ["_ADMIN_POLICY_REV = 2", "enforce_admin_policy()",
                      # ★★ 2026-09-20: 原来这里查的是 '"collect_regions": ["New York"]',
                      #   那行字【长在 _ADMIN_POLICY 字典里】。字典作为死数据被删掉
                      #   之后, 这个标记就永远 MISS —— 变成一条假警报,
                      #   照着它去"修"就是改没坏的东西。改成查真正的纠正语句。
                      'fixed["collect_regions"] = ["New York"]',
                      # ★ 会员三态判定(2026-09-19 用户报"会员号显示否"后修)
                      "_PREMIUM_JS", '("是" if _prem is True', "read_settings_info(page)",
                      # ★ claim_client 自愈(2026-09-19 用户报"文件在却报缺"后修)
                      "_reload_claim_client", "已自动补上",
                      # ★ 榜单口径 + 地点搜索(2026-09-19 用户要求做下拉框)
                      "AGE_GROUPS_VALID", "def _lb_filters", "region_search_key",
                      "def region_is_ny", "lb_gender",
                      # ★ 路段采样放开(2026-09-19 用户报"只选几个重复的")
                      "GRID_PAN_COLS", "pan_rounds", "enough_segments",
                      # ★ 每段门槛可配地板(2026-09-19 用户要求做下拉框)
                      "def resolve_min_athletes", "min_athletes_floor",
                      # ★ 年龄只留 55+(2026-09-19 用户要求取消 45-54 及以下)
                      "AGE_GROUPS_MIN_ALLOWED", "def age_bucket_low",
                      'AGE_GROUPS_DEFAULT = ("55_64", "65_69")',
                      # ★ 成果文件改成"一天一个"(2026-09-19 用户要求集中)
                      #   文件名 = 固定前缀「链接-」+ 日期
                      "def _daily_path", "采集日期", 'task["final"] = _daily_path()',
                      'DAILY_FILE_PREFIX = "链接-"',
                      # ★ 去重必须同时扫新旧两种文件名, 漏一种会重复写
                      'd.glob(DAILY_FILE_PREFIX + "*.txt")',
                      'd.glob(TASK_FILE_PREFIX + "*.txt")',
                      # ★ 扫描完关浏览器(2026-09-19 用户要求, 不然内存扛不住)
                      "def scan_should_close", "scan_should_close()",
                      # ★ 只采美国境内 + 圆心按脚本位置(2026-09-19 用户要求)
                      "def is_us_location", "_US_WORDS", "州表不可用",
                      "geo_center=config", "us_only",
                      # ★ AdsPower key 自愈(2026-09-20 同事报"一直显示API不正确")
                      #   ★ 只查 ADS 版: 比特版走 bb() 不用 AdsPower, 没有 ads_headers
                      "def ads_headers", "ads_headers()", "是【空的】",
                      # ★★ 2026-09-21: 上传的活动标题一律 Morning Run ★★
                      #   ★ 关键(真页面探出来的): 标题是上传页每张卡片上的
                      #     <input name=name>, Strava 已按【账号时区】自动填好;
                      #     类型默认 Workout。改素材文件根本管不住它 ——
                      #     必须在这两个框里写死。缺一条标题就还是 Afternoon Workout。
                      #   ★★ 2026-09-24 升级: 不再是写死的"早晨跑步", 而是
                      #     【跟着素材走】—— 骑行 TCX(Sport="Biking") -> Morning Ride/Ride,
                      #     跑步 -> Morning Run/Run, 认不出的退回跑步。
                      #     标志从 set_act_title(page, want=0) 变成了带 title/sport
                      #     两个形参 + 新增 sport_of()。老标志留着只会误报 MISS。
                      'ACT_TITLE = "Morning Run"', 'ACT_SPORT = "Run"',
                      "def sport_of(files):",
                      "_SPORT_MAP = {",
                      "def set_act_title(page, want=0, title=None, sport=None):",
                      "set_act_title(page, len(batch), *sport_of(batch))",
                      "form.good:visible",
                      # ★★ 2026-09-22: 老号也要能上传轨迹 ★★
                      #   `not skip_setup and files and upload_needed` 把整段上传
                      #   挡住了 —— 老号(有头像)skip_setup=True, 选"仅上传轨迹"
                      #   也什么都不传。和 09-19 修的"老号不补隐私"是同一个坑。
                      "这一步【不再受 skip_setup 管】",
                      # ★★ 2026-09-22: 采集从「开始任务」里摘出去了 ★★
                      #   开始任务只做 注册/改资料/传轨迹, 采集只归「◎ 只采集」
                      #   (它走 collect_one)。改回去就又变成"点开始任务也会采"。
                      #   ★ 会员状态/真实姓名仍要读 —— 表格那三列靠它回填。
                      "「▶ 开始任务」只做 注册/改资料/传轨迹",
                      "要采集请用「◎ 只采集」",
                      # ★★ 2026-09-22: 只采"近期还有活动"的人(默认 60 天) ★★
                      #   数据来自资料页的 <time datetime="ISO"> —— 结构化属性,
                      #   不用解析 "7 hours ago" 那种文字, 也不受界面语言影响。
                      #   check_athlete 本来就要打开资料页, 所以是零额外请求。
                      "recent_days=0", "out.recent_dates",
                      'CFG.get("recent_days", 60)',
                      "近{recent_days}天没活动",
                      # ★★ 2026-09-22: 点完地图标记要等"运动达人"数渲染出来 ★★
                      #   用户实测: 点一下就采 -> 人数还没画出来 -> 记 0,
                      #   看着像"这个路段没人"。链接比人数先出现, 只等链接不够。
                      "SEG_ATH_WAIT = 2.5", "SEG_ATH_READY_JS",
                      'key="segath"',
                      # ★★ 2026-09-23 用户要求: 取消环带距离, 只要美国境内 ★★
                      #   做法不是删代码, 而是把环带放成 0~20000:
                      #   距离这关永远通过, states_in_band 自然覆盖全美 51 个州。
                      "BAND_OFF_KM = 20000.0"],
    "strava_bit.py": ["_ADMIN_POLICY_REV = 2", "enforce_admin_policy()",
                      # ★★ 2026-09-20: 同 ADS 版说明 —— 原标记长在被删掉的
                      #   _ADMIN_POLICY 字典里, 改成查真正的纠正语句。
                      'fixed["collect_regions"] = ["New York"]',
                      "_PREMIUM_JS", '("是" if _prem is True', "read_settings_info(page)",
                      "_reload_claim_client", "已自动补上",
                      "AGE_GROUPS_VALID", "def _lb_filters", "region_search_key",
                      "def region_is_ny", "lb_gender",
                      "GRID_PAN_COLS", "pan_rounds", "enough_segments",
                      "def resolve_min_athletes", "min_athletes_floor",
                      # ★ 年龄只留 55+
                      "AGE_GROUPS_MIN_ALLOWED", "def age_bucket_low",
                      'AGE_GROUPS_DEFAULT = ("55_64", "65_69")',
                      # ★ 成果文件改成"一天一个", 名字 = 「链接-」+ 日期
                      "def _daily_path", "采集日期", 'task["final"] = _daily_path()',
                      'DAILY_FILE_PREFIX = "链接-"',
                      'd.glob(DAILY_FILE_PREFIX + "*.txt")',
                      'd.glob(TASK_FILE_PREFIX + "*.txt")',
                      # ★ 扫描完关浏览器
                      "def scan_should_close", "scan_should_close()",
                      # ★ 只采美国境内 + 圆心按脚本位置
                      "def is_us_location", "_US_WORDS", "州表不可用",
                      "geo_center=config", "us_only",
                      # ★★ 2026-09-21: 同 ADS 版 —— 上传标题/类型在上传页卡片上写死
                      #   ★ 2026-09-24 升级成【跟着素材走】(骑行 -> Morning Ride/Ride),
                      #     标志同步成新写法, 见上面 ADS 那段的说明。
                      'ACT_TITLE = "Morning Run"', 'ACT_SPORT = "Run"',
                      "def sport_of(files):",
                      "_SPORT_MAP = {",
                      "def set_act_title(page, want=0, title=None, sport=None):",
                      "set_act_title(page, len(batch), *sport_of(batch))",
                      "form.good:visible",
                      # ★★ 2026-09-22: 老号也要能上传轨迹 ★★
                      #   `not skip_setup and files and upload_needed` 把整段上传
                      #   挡住了 —— 老号(有头像)skip_setup=True, 选"仅上传轨迹"
                      #   也什么都不传。和 09-19 修的"老号不补隐私"是同一个坑。
                      "这一步【不再受 skip_setup 管】",
                      # ★★ 2026-09-22: 采集从「开始任务」里摘出去了 ★★
                      #   开始任务只做 注册/改资料/传轨迹, 采集只归「◎ 只采集」
                      #   (它走 collect_one)。改回去就又变成"点开始任务也会采"。
                      #   ★ 会员状态/真实姓名仍要读 —— 表格那三列靠它回填。
                      "「▶ 开始任务」只做 注册/改资料/传轨迹",
                      "要采集请用「◎ 只采集」",
                      # ★★ 2026-09-22: 只采"近期还有活动"的人(默认 60 天) ★★
                      #   数据来自资料页的 <time datetime="ISO"> —— 结构化属性,
                      #   不用解析 "7 hours ago" 那种文字, 也不受界面语言影响。
                      #   check_athlete 本来就要打开资料页, 所以是零额外请求。
                      "recent_days=0", "out.recent_dates",
                      'CFG.get("recent_days", 60)',
                      "近{recent_days}天没活动",
                      # ★★ 2026-09-22: 点完地图标记要等"运动达人"数渲染出来 ★★
                      #   用户实测: 点一下就采 -> 人数还没画出来 -> 记 0,
                      #   看着像"这个路段没人"。链接比人数先出现, 只等链接不够。
                      "SEG_ATH_WAIT = 2.5", "SEG_ATH_READY_JS",
                      'key="segath"',
                      # ★★ 2026-09-23 用户要求: 取消环带距离, 只要美国境内 ★★
                      #   做法不是删代码, 而是把环带放成 0~20000:
                      #   距离这关永远通过, states_in_band 自然覆盖全美 51 个州。
                      "BAND_OFF_KM = 20000.0"],
    "update.py": ['"_policy_rev"', "POLICY_KEYS", "按管理员口径纠正"],
    "fix_update.py": ['"_policy_rev"', "POLICY_KEYS", "urllib.request.urlopen"],
}
bad = 0
for f, ms in MARKS.items():
    t = (dist / f).read_text(encoding="utf-8")
    for m in ms:
        ok = m in t
        bad += 0 if ok else 1
        print("  %-16s %s  %s" % (f, "OK  " if ok else "MISS", m))

# ============================================================================
# ★★ 两个引擎必须逐行一致(2026-09-20 新增) ★★
#   这两个引擎是"一个程序的两份拷贝", 全靠手工保持同步 ——
#   这几天已经因此出过 4 次事故(只改 ADS 忘了 Bit):
#     · _reload_claim_client -> Bit 报"缺 claim_client.py", 退回本地去重(多机重复采)
#     · scan_should_close    -> Bit 扫描不关浏览器(内存扛不住)
#     · is_us_location       -> Bit 的"只要美国境内"根本没生效, 界面看着却像生效
#     · geo_lookup           -> Bit 引用了 ADS 才有的名字, 被 except 吞掉、静默失效
#   所以在这里加一道闸门: 发版前就报出来, 不让"两边不一致"溜出去。
#   只比【去掉注释后的纯代码】, 避免注释措辞差异造成误报。
# ============================================================================
print()
print("=== 两个引擎的纯代码一致性(去掉注释后对比) ===")
try:
    import ast as _ast
    import io as _io
    import tokenize as _tk

    def _code_map(p):
        src = p.read_text(encoding="utf-8")
        lines = src.splitlines()
        drop = set()
        try:
            for tok in _tk.generate_tokens(_io.StringIO(src).readline):
                if tok.type == _tk.COMMENT:
                    drop.add(tok.start[0])
        except Exception:
            pass
        out = {}
        for n in _ast.walk(_ast.parse(src)):
            if not isinstance(n, _ast.FunctionDef):
                continue
            ds = set()
            b0 = n.body[0] if n.body else None
            if isinstance(b0, _ast.Expr) and isinstance(b0.value, _ast.Constant) \
                    and isinstance(b0.value.value, str):
                ds = set(range(b0.lineno, (b0.end_lineno or b0.lineno) + 1))
            body = []
            for ln in range(n.lineno, (n.end_lineno or n.lineno) + 1):
                if ln in drop or ln in ds:
                    continue
                code = lines[ln - 1].strip()
                if code:
                    body.append(code)
            out[n.name] = body
        return out

    _ma = _code_map(root / "主脚本" / "strava_ads.py")
    _mb = _code_map(root / "主脚本" / "strava_bit.py")
    _both = sorted(set(_ma) & set(_mb))
    _same = [n for n in _both if _ma[n] == _mb[n]]
    _diff = [n for n in _both if _ma[n] != _mb[n]]
    print("  ADS %d 个函数, Bit %d 个; 共同 %d 个"
          % (len(_ma), len(_mb), len(_both)))
    print("  纯代码逐行相同: %d 个" % len(_same))
    print("  纯代码有差异  : %d 个" % len(_diff))
    print("     %s" % ", ".join(_diff))
    print("  (有差异不一定是错 —— 浏览器适配层本来就该不同;")
    print("   但每次发版都列出来, 方便一眼看出'这次是不是只改了一边')")
except Exception as _e:
    print("  ★ 一致性检查没跑起来: %s" % str(_e)[:90])

# 旧代码必须消失(★ 只查真正的代码写法; 新注释里为了讲清根因会提到这个名字)
print()
print("=== 旧代码写法必须已消失 ===")
gone_bad = 0
for f in ("strava_ads.py", "strava_bit.py"):
    t = (dist / f).read_text(encoding="utf-8")
    for m in ("not skip_setup and files and upload_needed",):
        still = m in t
        gone_bad += 1 if still else 0
        print("  %-16s %s  %s" % (f, "★还在!" if still else "已清除", m))
for f in ("_gui_ads.py", "_gui_bit.py"):
    t = (dist / f).read_text(encoding="utf-8")
    for m in ("_LEGACY_REGIONS = [", "if _cur == _LEGACY_REGIONS:"):
        still = m in t
        gone_bad += 1 if still else 0
        print("  %-16s %s  %s" % (f, "★还在!" if still else "已清除", m))
    # 新机制必须在
    for m in ("if _rev < _ADMIN_POLICY_REV:", "_fixed[\"_policy_rev\"]"):
        ok = m in t
        gone_bad += 0 if ok else 1
        print("  %-16s %s  %s" % (f, "OK  " if ok else "MISS", m))

# ★★ .bat 合规闸门 ★★
#   铁律(踩过两次): .bat 必须【CRLF 换行】+【纯 ASCII 内容】。
#   LF 换行 或 内容里带中文 -> cmd 解析错位, 报出莫名其妙的
#   "'eDelayedExpansion' 不是内部或外部命令" / "'tart_*.bat' ..." 之类。
#   中文只能出现在 bat 的【文件名】上(启动.bat / 更新.bat 就是这样)。
print()
print("=== .bat 必须 CRLF + 纯 ASCII ===")
bat_bad = 0
for b in sorted(dist.glob("*.bat")):
    raw = b.read_bytes()
    crlf = raw.count(b"\r\n")
    bare_lf = raw.count(b"\n") - crlf
    non_ascii = sum(1 for x in raw if x > 127)
    ok = (bare_lf == 0 and non_ascii == 0)
    bat_bad += 0 if ok else 1
    print("  %s %-24s CRLF=%-4d 裸LF=%-3d 非ASCII=%-3d %s"
          % ("OK  " if ok else "★FAIL", b.name, crlf, bare_lf, non_ascii,
             "" if ok else "<- 必须修!"))

print()
print("标记缺失 = %d   旧写法残留 = %d   bat 不合规 = %d"
      % (bad, gone_bad, bat_bad))

# ★ 分发包 config.json 的采集口径(用户 2026-09-19 要求"时间范围=今年")
print()
print("=== 分发包 config.json 的采集口径 ===")
_c = json.loads((dist / "config.json").read_text(encoding="utf-8"))
for k in ("collect_regions", "collect_gender", "collect_date_range",
          "collect_age_groups", "min_athletes", "jobs", "_policy_rev"):
    print("  %-22s = %r" % (k, _c.get(k)))
_cfg_bad = 0
if _c.get("collect_date_range") != "this_year":
    print("  ★ 时间范围不是 this_year(今年) —— 用户明确要求改成今年")
    _cfg_bad = 1
if "_policy_rev" in _c:
    print("  ★ 分发包里出现了 _policy_rev —— 绝不能下发(见 update.py 注释)")
    _cfg_bad = 1

raise SystemExit(1 if (bad or gone_bad or bat_bad or _cfg_bad) else 0)
