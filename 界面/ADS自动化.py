# -*- coding: utf-8 -*-
"""ADS自动化 — 可视化程序 (基于 strava_ads.py)
"""
import importlib.util, json, logging, os, queue, sys, threading, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "task_state.json"
def _find(*rels):
    """在 当前目录/配置/数据/上级目录 里找文件(兼容分层备份包)"""
    for base in (ROOT, ROOT.parent, ROOT.parent / "配置", ROOT.parent / "数据"):
        for r in rels:
            fp = base / r
            if fp.exists():
                return fp
    for base in (ROOT, ROOT.parent / "配置", ROOT.parent / "数据"):
        for r in rels:
            if (base / r).exists():
                return base / r
    return ROOT / rels[0]


ACC_FILE = _find("ads_accounts.json")
RES_FILE = _find("ads_results.json")

# 顺序即表格列序。
# ★★ 2026-09-20 用户要求: 「备注还是恢复成原样吧。移到后面去」★★
#   备注(note)从"账号前面"改回【最后一列】—— 恢复成改之前的布局。
#   ★ 表头文字在 HEADS 里(按 key 取), 改顺序不影响它;
#   ★ 所有取值都走 FIELDS.index(...) / I_XXX 常量(见下面), 不再有写死的
#     数字下标 —— 所以这次调列序不会像上次那样把刷新/保存/登录搞错位。
FIELDS = ("seq", "win", "email", "password", "login",
          "name", "city", "acts", "prem", "priv", "region", "age", "note")
HEADS = {"seq": "编号", "win": "窗口", "email": "账号", "password": "密码", "login": "登录",
         "name": "名字", "city": "城市", "acts": "活动", "prem": "会员", "priv": "隐私",
         # ★ 2026-09-24 用户要求: 「每个账号可以单独选择采集什么地区, 比如说三个
         #   账号采集三个不同的地区。年纪。」—— 这两列是【按号】的设置,
         #   双击单元格就能选; 留空 = 用上面那个下拉框的默认值。
         "region": "采集地区(空=默认)", "age": "采集年龄(空=默认)", "note": "备注"}

# ★★ 下标一律从 FIELDS 推出来, 不许再写死数字 ★★
#   2026-09-20 用户实测报"点刷新结果, 备注自动跑到后面去了"。
#   根因: FIELDS 的顺序改过一次 ——「备注」原来是【最后一列】, 后来被挪到第 3 位
#   (备注在账号前面), 但下面几处代码还在用老顺序的写死下标:
#       v[2] 当成账号、v[3] 当成密码、v[4..10] 当成 login..note
#   实际 v[2] 是【备注】、v[3] 才是【账号】—— 整体错位一格。后果分三处:
#     · 刷新结果  -> 邮箱被写进「备注」列, 之后每一列都左移一格,
#                    用户看到的就是"备注自己跑到后面去了"
#     · 保存账号  -> 把备注当账号、把账号当密码写进磁盘(真会写坏文件)
#     · 取登录凭据-> 拿备注当账号去登录, 必然登不上
#   改成从 FIELDS 取下标之后, 以后不管列序怎么调都不会再错位。
I_SEQ = FIELDS.index("seq")
I_WIN = FIELDS.index("win")
I_EMAIL = FIELDS.index("email")
I_PWD = FIELDS.index("password")
# 会被刷新写入的那些资料列(按 FIELDS 动态取下标)
PROFILE_COLS = ("login", "name", "city", "acts", "prem", "priv", "note")


def app_ver():
    """显示用的版本号。真源是引擎加载的 app_version.py。

    ★ 界面自己【不】import app_version: 开发时它在 主脚本/ 下, 发包后在包根,
      路径不一样; 而引擎两条路径都找得到它, 从引擎拿最省事。
    ★ 拿不到就返回空串 —— 版本号显示不出来是小事, 不能让界面起不来。
    """
    try:
        _l = getattr(SA, "ver_label", None)
        if callable(_l):
            return str(_l() or "")
        return str(getattr(SA, "APP_VERSION", "") or "")
    except Exception:
        return ""


# ---------------- 列错位【自愈】 ----------------
# ★★ 2026-09-21 用户报「脚本主页信息又错位了。不能固定死吗?」★★
#   错位的样子: login 里是名字、name 里是城市、city 里是活动数……整行【左移一格】。
#   源头是历史遗留: 「备注列位置改过一次, 而有些地方用了写死的列下标」。
#   那些地方现在已经全部改成按字段名取(见上面的 I_XXX), 不会再【新产生】错位;
#   但【磁盘上早就被写坏的那些行】会被界面读进来、原样显示、再原样存回去 ——
#   于是永远错下去, 看起来就像"又错位了"。
#   所以这里在读入时自愈: 认出这种错位就掰回来, 并写回磁盘, 一次性根治。
#   判据用的是取值范围固定的两列(它们移没移一眼能看出来):
#       login 只能是 是/否        acts 只能是数字(可以是 -1)
#   ★ 掰回来之后逐列复验, 验不过就【保持原样】—— 绝不越修越坏。
_UNSHIFT = (("login", "password"), ("name", "login"), ("city", "name"),
            ("acts", "city"), ("prem", "acts"), ("priv", "prem"),
            ("note", "priv"))
_YESNO = ("是", "否")


def _is_num(s):
    try:
        int(str(s).strip())
        return True
    except Exception:
        return False


def _looks_shifted(d):
    """看这一行是不是"左移一格"了。"""
    if not isinstance(d, dict):
        return False
    lg = str(d.get("login") or "").strip()
    ac = str(d.get("acts") or "").strip()
    if lg and lg not in _YESNO:
        return True                 # login 里是人名 -> 错位
    if ac in _YESNO:
        return True                 # acts 里是 是/否 -> 错位
    return False


def _unshift(d):
    """掰回一格。复验不过返回 None(= 别动它)。"""
    src = {f: d.get(f, "") for f in ("password", "login", "name", "city",
                                     "acts", "prem", "priv", "note")}
    nv = dict(d)
    for dst, s in _UNSHIFT:
        nv[dst] = src[s]
    lg = str(nv.get("login") or "").strip()
    ac = str(nv.get("acts") or "").strip()
    pr = str(nv.get("prem") or "").strip()
    nm = str(nv.get("name") or "").strip()
    ct = str(nv.get("city") or "").strip()
    if lg and lg not in _YESNO:
        return None
    if ac and not _is_num(ac):
        return None
    if pr and pr not in _YESNO:
        return None
    if "," in nm:
        return None                 # 人名不带逗号; 带逗号说明这列其实是城市
    if _is_num(ct):
        return None                 # 城市不会是纯数字
    return nv


def _pwd_index(acc):
    """{邮箱小写: 密码} —— 自愈时用它把被覆盖掉的真密码找回来。"""
    idx = {}
    if isinstance(acc, dict):
        for av in acc.values():
            if not isinstance(av, dict):
                continue
            e = str(av.get("email") or "").strip().lower()
            p = str(av.get("password") or "").strip()
            if e and p and p not in _YESNO:
                idx.setdefault(e, p)
    return idx


def heal_shifted(data, acc=None):
    """把一整份结果里错位的行掰回来。返回 (新字典, 修了几条)。

    ★★ 密码列必须单独补(用户: "你确定修好了吗? 密码呢") ★★
      错位时 password 被原 login 覆盖成 是/否, 掰回来也【推不出原值】。
      所以按邮箱去账号文件查; 查不到就【清空】, 让刷新时再按账号文件补。
      绝不能把 是/否 留在密码列 —— 它会被 _save_accounts 写回账号文件,
      把里面仅存的那份真密码也冲掉(这次就是这么丢的)。
    """
    if not isinstance(data, dict):
        return data, 0
    idx = _pwd_index(acc)
    out, n = {}, 0
    for k, v in data.items():
        if _looks_shifted(v):
            nv = _unshift(v)
            if nv is not None:
                e = str(nv.get("email") or "").strip().lower()
                nv["password"] = idx.get(e, "")
                out[k] = nv
                n += 1
                continue
        out[k] = v
    return out, n


def row_from(seq, r, a):
    """把结果文件/账号文件里的一条, 转成【按 FIELDS 顺序】的表格值。

    ★ 刷新"补入新行"时必须用它 —— 原来那串 values=(seq, win, email, ...)
      是按老列序手写的, 和新 FIELDS 对不上, 新补进来的行整行错位。
    """
    r = r or {}
    a = a or {}
    vals = {f: "" for f in FIELDS}
    vals["seq"] = str(seq)
    vals["win"] = str(r.get("win") or seq)
    vals["email"] = r.get("email") or a.get("email", "")
    vals["password"] = r.get("password") or a.get("password", "")
    for f in PROFILE_COLS:
        vals[f] = r.get(f, "")
    return tuple(vals[f] for f in FIELDS)

# 「执行内容」下拉框的选项 —— 和旧界面保持一致
# 引擎按 cfg["task_mode"] 决定跳过哪些步骤
TASK_MODES = ("全部(资料+隐私+轨迹)", "仅资料+隐私", "仅隐私", "仅上传轨迹")

# ★★ 管理员采集口径 ★★
#   机制: config.json 里有个 "_policy_rev" 版本号。
#     本地版本号 < _ADMIN_POLICY_REV  ->  纠正【老包遗留值】并把版本号写回去。
#     本地版本号 >= _ADMIN_POLICY_REV ->  完全不动, 尊重同事自己改的值。
#
# ★★ 2026-09-20【删掉了 _ADMIN_POLICY 这个字典】★★
#   它原本长这样:  _ADMIN_POLICY = {"min_athletes": 5000, ...}
#   以前界面【无条件】按它覆盖, 于是你在界面上改成 2000 之后,
#   只要 _policy_rev 落后就被写回 5000 —— 那就是用户报的
#   "我改了同事那边却没变"。修好之后这个字典再没有任何代码读它。
#   可它还写着 min_athletes: 5000, 谁看到都会以为 5000 是公司口径。
#   留着就是给下一个人预备的坑, 所以整个删掉。
#   ★ 现在唯一的口径开关是下面的 _ADMIN_POLICY_REV。
_ADMIN_POLICY_REV = 2

# ★★ 2026-09-19 用户要求: 采集地区 / 性别 / 时间 / 年纪 都做成框框供选择 ★★
#   这里的每个取值都做过校验, 选哪个都不会让 Strava 报错:
#     性别/时间/年龄 的合法集合在引擎里(_lb_filters / _age_groups_of),
#     非法值会被剔除并退回默认, 不会发出 400 请求。
_LEGACY_REGION_CHOICES = (
    "New York",
    "Chicago",
    "Los Angeles",
    "Boston",
    "Central Park (New York)",
    "Lakefront Trail (Chicago)",
    "The 606 (Chicago)",
    "Chicago Riverwalk (Chicago)",
    "The Strand or Marvin Braude Bike Trail (Los Angeles)",
    "Griffith Observatory (Los Angeles)",
    "Charles River Esplanade (Boston)",
)

# ★★ 2026-09-23 用户要求: 精准采集那 29 个地区 ★★
#   一开始它是「◎ 精准采集」按钮专用的固定名单; 用户随后要求
#   【和原有地区共用同一个下拉框】—— 所以下面 REGION_CHOICES 是两者合并的。
#   这个常量本身还留着: 「◎ 精准采集」仍按它一次性扫全 29 个。
PRECISE_REGIONS = (
    "New Jersey", "Boston", "Texas",
    "Hawaii", "Idaho", "Florida", "Georgia", "Connecticut",
    "Massachusetts", "Maryland", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "South Carolina", "South Dakota",
    "Tennessee", "Indiana", "Illinois", "Utah", "West Virginia", "Wisconsin",
)

# ★★ 采集地区下拉框 = 原有的 + 精准的, 去重后的全部 ★★
#   dict.fromkeys 保序去重: "Boston" 两边都有, 只留第一次出现的位置。
#   ★ 只在这一个框里选: 「◎ 只采集」用你选的那个, 「◎ 精准采集」用全 29 个。
REGION_CHOICES = tuple(dict.fromkeys(
    list(_LEGACY_REGION_CHOICES) + list(PRECISE_REGIONS)))

# ★★ 2026-09-23 用户要求: 「位置」也做成下拉框 ★★
#   原来是个自由输入框(默认 "Chicago, Illinois"), 现在改成只读下拉,
#   选哪个, 改资料时就往 Strava 上写哪个。
#   覆盖采集目标那些州的主要城市 + 全美几个大城市。
LOCATION_CHOICES = (
    "Chicago, Illinois",
    "New York, New York",
    "Los Angeles, California",
    "Boston, Massachusetts",
    "Newark, New Jersey",
    "Jersey City, New Jersey",
    "Houston, Texas",
    "Dallas, Texas",
    "Austin, Texas",
    "San Antonio, Texas",
    "Honolulu, Hawaii",
    "Boise, Idaho",
    "Miami, Florida",
    "Orlando, Florida",
    "Tampa, Florida",
    "Atlanta, Georgia",
    "Hartford, Connecticut",
    "Baltimore, Maryland",
    "Jackson, Mississippi",
    "St. Louis, Missouri",
    "Billings, Montana",
    "Omaha, Nebraska",
    "Las Vegas, Nevada",
    "Nashua, New Hampshire",
    "Charlotte, North Carolina",
    "Raleigh, North Carolina",
    "Fargo, North Dakota",
    "Columbus, Ohio",
    "Cleveland, Ohio",
    "Oklahoma City, Oklahoma",
    "Portland, Oregon",
    "Columbia, South Carolina",
    "Sioux Falls, South Dakota",
    "Nashville, Tennessee",
    "Indianapolis, Indiana",
    "Milwaukee, Wisconsin",
    "Salt Lake City, Utah",
    "Charleston, West Virginia",
    "Philadelphia, Pennsylvania",
    "Phoenix, Arizona",
    "San Diego, California",
    "San Francisco, California",
    "San Jose, California",
    "Seattle, Washington",
    "Denver, Colorado",
    "Minneapolis, Minnesota",
    "Detroit, Michigan",
    "New Orleans, Louisiana",
    "Pittsburgh, Pennsylvania",
    "Sacramento, California",
    "Albuquerque, New Mexico",
)

# (显示文字, 存进 config 的值)
GENDER_CHOICES = (("男性", "male"), ("女性", "female"), ("全部", "overall"))
DATE_CHOICES = (("本月", "this_month"), ("本周", "this_week"),
                ("今年", "this_year"), ("全部", "all"))
# ★★ 2026-09-19 用户要求:「每段」也做成框框供选择 ★★
#   原来是一行静态文字 "每段≥5000人", 想改只能翻 config.json。
#   下面是可选门槛(单位: 这个路段上共有多少个运动达人):
#     · 5000 是原有口径, 放第一并标默认
MIN_ATH_CHOICES = (
    # ★★ 2026-09-22 用户要求: 100~900 这些小路段也要能采 ★★
    #   以前最低只到 1000, 小路段全被门槛挡在外面, 一个都进不来。
    #   ★ 光加选项不够: 界面和引擎里各有一道"低于 200 就抬回 200"的闸
    #     (见本文件下面 _policy_rev 那段 / 引擎的 enforce_admin_policy),
    #     不一起放开的话, 选 100 会被【悄悄改回 200】—— 就是"选了没用"。
    ("100", 100),
    ("200", 200),
    ("300", 300),
    ("400", 400),
    ("500", 500),
    ("600", 600),
    ("700", 700),
    ("800", 800),
    ("900", 900),
    ("1000", 1000),
    ("2000 (发行包默认)", 2000),
    ("3000", 3000),
    ("5000 (原有口径)", 5000),
    ("8000", 8000),
    ("10000", 10000),
    ("20000", 20000),
    ("50000", 50000),
    ("0 (不设门槛, 所有采样到的路段都入选)", 0),
)

AGE_CHOICES = (
    # ★★ 2026-09-19 用户要求:「45-54 岁及以下的选项取消, 保留 55 以上的即可」★★
    #   所以不再提供 45-54 及以下(3x_4x / 0_19 那些全删)。
    #   ★ 引擎侧也拦了一道(_age_groups_of 会剔掉低于 55 的桶)——
    #     光删下拉选项不够: 老配置里的 '45_54' 仍然生效, 而界面因为
    ("55-64 + 65-69 两个都采(默认)", ("55_64", "65_69")),
    ("只要 55-64 (单个)", ("55_64",)),
    ("只要 65-69 (单个)", ("65_69",)),
    ("只要 70-74 (单个)", ("70_74",)),
    ("只要 75+ (单个)", ("75_plus",)),
    ("55 岁及以上全部(四个都采)", ("55_64", "65_69", "70_74", "75_plus")),
)


def _label_of(pairs, value, default_index=0):
    """值 -> 显示文字(找不到就用第一项), 用于把 config 里的值填回下拉框"""
    for lab, val in pairs:
        if val == value:
            return lab
    return pairs[default_index][0]


def _value_of(pairs, label, default_index=0):
    """显示文字 -> 值(找不到就用第一项)"""
    for lab, val in pairs:
        if lab == label:
            return val
    return pairs[default_index][1]


def _spin_int(text, dflt):
    """输入框里的整数: 空/非法就退回默认(不能让它把整份 cfg 搞崩)。"""
    try:
        s = str(text).strip()
        return int(s) if s else dflt
    except Exception:
        return dflt


def load_json(p, default=None):
    """★ 解析失败返回 None(而不是 default): 调用方必须能区分
       "文件不存在/本来就是空" 与 "文件被写坏了", 否则会把坏文件当空,
       再在 destroy() 时无条件落盘 -> 100 行结果一次性清零。"""
    try:
        if Path(p).exists():
            return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None
    return default if default is not None else {}


def save_json(p, data):
    """★ 原子写: 先写临时文件再 os.replace, 写到一半崩掉不会弄坏原文件。"""
    try:
        p = Path(p)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def load_json_checked(p):
    """读关键 json 的统一入口 -> (字典, 是否坏文件)。

    ★ 为什么单独包一层: load_json 现在把"读不出来"和"文件不存在"都变成 None,
      调用方必须自己区分。这里的口径是: 文件存在且非空却解析不出来 = 坏文件;
      此时【绝不能用空值重建表格或落盘】(那正是 100 行结果一次性清零的链路),
      只能 self.log 报错并中止本次操作 —— 磁盘内容一个字节都不动。
    """
    d = load_json(p, {})
    if d is None:
        try:
            bad = bool(Path(p).read_text(encoding="utf-8",
                                         errors="replace").strip())
        except Exception:
            bad = Path(p).exists()      # 读不出来但路径还在 -> 按坏文件处理更安全
        return {}, bad
    return (d if isinstance(d, dict) else {}), False


def call_engine(fn, *args, **kwargs):
    """按引擎函数的真实签名调用(多余的位置参数自动丢弃)。

    ★ 界面和引擎是两个文件, 两个代理的落地顺序不保证: 引擎还没加上 task 形参时
      多传一个位置参数会直接 TypeError, 那等于「只采集/开始任务」整个跑不起来。
      这里先用签名判一次(不靠 try/except 重试, 不会重复执行一次采集),
      也不吞引擎自己抛出来的 TypeError。
    """
    try:
        import inspect as _ins
        _n = len(_ins.signature(fn).parameters)
        if _n and len(args) > _n:
            args = args[:_n]
    except Exception:
        pass
    return fn(*args, **kwargs)


class _NoTheme(Exception):
    """内部信号: 本次不启用 sv-ttk(默认走快的 clam 配色)。

    ★ 2026-09-20 加。起因: 实测 sv-ttk 让界面启动慢 2.4 倍(381ms -> 923ms)。
      工具的第一要求是不拖慢干活, 所以默认不用它; 想用再在 config.json 里开。
    """
    pass


def _find_ui_cfg():
    """找 config.json(和引擎同一套顺序), 只为读 ui_theme。

    ★★ 2026-09-20 修: 上一版这段被插成了【上一个函数的嵌套函数】(缩进 4 空格),
       _apply_theme 里裸调它就是 NameError —— 而那个调用被 try/except 包着,
       异常被静默吞掉, 表现是"深色主题怎么设都还是浅色", 完全不报错。
       教训: 带兜底的 except 会把"名字写错"也一起吞掉, 排查时先怀疑它。
    """
    for c in (ROOT / "config.json", ROOT / "配置" / "config.json",
              ROOT.parent / "配置" / "config.json",
              ROOT.parent / "config.json"):
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return None


_GUI_FILE_LOG = None


def _gui_file_logger():
    """给"界面自己的消息"准备一个【只写文件】的 logger(幂等)。

    ★ 为什么不直接用 getLogger("strava"):
      那个 logger 上挂着 _GuiLogHandler(负责把日志塞进界面日志框),
      再走它一遍, 同一条消息会在界面上出现两次。
      这里挂 propagate=False 的独立 logger + 自己的 FileHandler,
      指向同一个文件, 于是: 界面显示一次、文件记一次, 互不干扰。
    """
    global _GUI_FILE_LOG
    if _GUI_FILE_LOG is not None:
        return _GUI_FILE_LOG
    lg = logging.getLogger("strava.gui")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    try:
        for h in logging.getLogger("strava").handlers:
            if isinstance(h, logging.FileHandler):
                fh = logging.FileHandler(h.baseFilename, encoding="utf-8")
                fh.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)s %(message)s"))
                lg.addHandler(fh)
                break
    except Exception:
        pass
    _GUI_FILE_LOG = lg
    return lg


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ADS自动化  " + app_ver())
        self.geometry("1300x780")
        self.logq = queue.Queue()
        self.uiq = queue.Queue()
        self.items = []
        self.stop_flag = threading.Event()
        self.running = False
        # ★ 扫描中标志: 「1.连接并加载」的守卫要认它, 否则扫描跑着还能加载,
        #   加载会 delete 掉全部行再重建, 把扫描刚回填的结果一次性抹掉。
        self.scanning = False
        self._alive = True
        self._build()
        self._after_log = None
        self._after_ui = None
        self._after_log = self.after(200, self._drain_log)
        self._after_ui = self.after(150, self._drain_ui)
        n = self._restore()
        if n:
            self.log(f"已恢复上次结果 {n} 条")

    # ---------------- 界面 ----------------
    def _apply_theme(self):
        """统一外观。

        优先级: ① 内置的 sv-ttk(Sun Valley, MIT, 约 80KB, 随包分发, 不用 pip)
                ② 找不到就退回 clam + 自己那套配色
        ★ 两级都带兜底: 主题文件被误删也绝不因为美化把界面搞崩。
        """
        _sv = False
        try:
            # ★ sv_ttk 就在脚本同级(分发包里)或上一级(开发目录里)
            import sys as _s
            for _p in (ROOT, ROOT.parent):
                if str(_p) not in _s.path:
                    _s.path.insert(0, str(_p))
            import sv_ttk
            # ★★ 2026-09-20 实测后改成【默认不用】★★
            #   本机对比: 不带主题 启动 381ms / 填200行  60ms
            #             带 sv-ttk  启动 923ms / 填200行 136ms  (2.3~2.4 倍)
            #   sv-ttk 每个控件都要跑 Tcl 脚本做圆角/DPI 适配, 启动开销集中。
            _want = ""
            try:
                _c = _find_ui_cfg()
                if _c is not None:
                    _w = str(json.loads(_c.read_text(encoding="utf-8"))
                             .get("ui_theme") or "").strip().lower()
                    if _w in ("light", "dark"):
                        _want = _w
            except Exception:
                pass
            if _want:
                sv_ttk.set_theme(_want)
                _sv = True
                self._ui_theme = _want
            else:
                # 没显式要求 -> 不启用 sv-ttk, 走下面那套快的配色
                self._ui_theme = "clam"
                raise _NoTheme()
        except _NoTheme:
            pass                      # 正常路径: 本次就是不用 sv-ttk(默认)
        except Exception as _e:
            self._ui_theme = "clam"
            try:
                print("[ui] sv-ttk 不可用(%s) -> 退回内置配色" % str(_e)[:50])
            except Exception:
                pass
        try:
            st = ttk.Style(self)
            # ---- 主题: 用 clam ----
            # ★★ 2026-09-20 截图验收发现的问题 ★★
            #   一开始优先用 vista(Windows 原生主题), 结果【开始任务/停止两个按钮
            #   几乎看不见】: vista 忽略按钮的 background 映射, 却仍然应用
            _themes = set(st.theme_names())
            if not _sv:
                # 只有没启用 sv-ttk 时才自己选主题
                for _t in ("clam", "vista", "winnative", "default"):
                    if _t in _themes:
                        st.theme_use(_t)
                        break
            # ---- 字体: 微软雅黑优先, 找不到就交给系统默认 ----
            _fam = "Microsoft YaHei UI"
            try:
                import tkinter.font as _tkf
                _have = set(_tkf.families(self))
                for _cand in ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei",
                              "Segoe UI"):
                    if _cand in _have:
                        _fam = _cand
                        break
            except Exception:
                pass
            _F = (_fam, 10)
            _FB = (_fam, 10, "bold")
            _FT = (_fam, 15, "bold")          # 标题
            try:
                for _w in ("TLabel", "TButton", "TEntry", "TCombobox",
                           "TCheckbutton", "TRadiobutton", "TLabelframe.Label"):
                    st.configure(_w, font=_F)
                st.configure("TButton", padding=(10, 5))
                st.configure("TLabelframe.Label", font=_FB, foreground="#2C3E50")
                st.configure("Title.TLabel", font=_FT, foreground="#1F3A5F")
                st.configure("Sub.TLabel", font=(_fam, 9), foreground="#7F8C8D")
                # ---- 三种语义按钮 ----
                st.configure("Primary.TButton", font=_FB, padding=(14, 6))
                st.configure("Danger.TButton", font=_FB, padding=(12, 6))
                st.configure("Ghost.TButton", padding=(10, 5))
                self._st_ghost = "TButton" if _sv else "Ghost.TButton"
                if _sv:
                    # ★★ sv-ttk 有自己的主按钮样式, 直接用它。
                    #   千万不要在这里 map 按钮的 background/foreground ——
                    #   sv-ttk 和 vista 一样【忽略 background 却应用 foreground】,
                    #   于是白字落在浅色按钮上, 按钮直接"消失"(实测踩过两次)。
                    self._st_primary = "Accent.TButton"
                    self._st_danger = "TButton"
                else:
                    self._st_primary = "Primary.TButton"
                    self._st_danger = "Danger.TButton"
                    try:
                        st.map("Primary.TButton",
                               background=[("active", "#27AE60"),
                                           ("!disabled", "#2ECC71")],
                               foreground=[("!disabled", "#FFFFFF")])
                        st.map("Danger.TButton",
                               background=[("active", "#C0392B"),
                                           ("!disabled", "#E74C3C")],
                               foreground=[("!disabled", "#FFFFFF")])
                    except Exception:
                        pass              # 某些主题不支持改按钮底色, 无妨
                # ---- 表格: 行高 + 表头 ----
                st.configure("Treeview", font=_F, rowheight=30)
                st.configure("Treeview.Heading", font=_FB, padding=(6, 6))
                st.map("Treeview", background=[("selected", "#D6EAF8")])
            except Exception:
                pass
        except Exception:
            pass

    def _build(self):
        # ★ 先给样式名兜底: 万一 _apply_theme 内部异常没设成, 按钮创建时
        #   也不能因为拿不到属性而崩(美化代码绝不能拖垮主流程)。
        self._st_primary = getattr(self, "_st_primary", "TButton")
        self._st_danger = getattr(self, "_st_danger", "TButton")
        self._st_ghost = getattr(self, "_st_ghost", "TButton")
        self._apply_theme()
        bar = ttk.Frame(self); bar.pack(fill="x", padx=8, pady=6)
        # ★ 必须保存引用: 原来这一行没存 self.btn_load, 运行中想禁用它都做不到
        self.btn_load = ttk.Button(bar, text="1.连接并加载", command=self.load_items)
        self.btn_load.pack(side="left")
        ttk.Button(bar, text="2.扫描状态", command=self.scan_all).pack(side="left", padx=5)
        ttk.Button(bar, text="⟳ 刷新结果", command=self.refresh_results).pack(side="left", padx=5)
        ttk.Button(bar, text="3.预览分配", command=self.preview).pack(side="left")
        ttk.Label(bar, text="  编号").pack(side="left")
        self.var_from = tk.StringVar(value="1")
        self.var_to = tk.StringVar(value="50")
        ttk.Entry(bar, textvariable=self.var_from, width=5).pack(side="left", padx=2)
        ttk.Label(bar, text="~").pack(side="left")
        ttk.Entry(bar, textvariable=self.var_to, width=5).pack(side="left", padx=2)
        self.btn_start = ttk.Button(bar, text="▶ 开始任务", command=self.start_task,
                                    style=self._st_primary)
        self.btn_start.pack(side="left", padx=8)
        self.btn_collect = ttk.Button(bar, text="◎ 只采集", command=self.start_collect,
                                      style=self._st_ghost)
        self.btn_collect.pack(side="left")
        # ★★ 2026-09-23 用户要求: 单独一个「◎ 精准采集」★★
        #   只扫 PRECISE_REGIONS 那 29 个地区; 其它筛选和「只采集」一模一样。
        self.btn_precise = ttk.Button(bar, text="◎ 精准采集", command=self.start_precise,
                                      style=self._st_ghost)
        self.btn_precise.pack(side="left", padx=5)
        self.btn_stop = ttk.Button(bar, text="■ 停止", command=self.stop_task,
                                   state="disabled", style=self._st_danger)
        self.btn_stop.pack(side="left", padx=5)
        self.btn_clean = ttk.Button(bar, text="✕ 关闭全部浏览器", command=self.close_browsers)
        self.btn_clean.pack(side="left", padx=5)
        self.lbl_run = ttk.Label(bar, text="空闲", foreground="#0a7")
        self.lbl_run.pack(side="left", padx=8)
        # ★★ 2026-09-20 用户要求:「在脚本界面加一个采集计数, 每天过了十二点更新」★★
        #   以前要看今天采了多少, 只能去翻 数据\链接-日期.txt 的行数 ——
        #   而窗口显示会卡住(点一下黑窗口就停), 很容易误判成"没在采"。
        #   这里直接在界面上显示, 每 5 秒自己刷一次。
        self.lbl_today = ttk.Label(bar, text="今日 -- 条", foreground="#06c")
        self.lbl_today.pack(side="left", padx=10)
        self.after(1200, self._tick_today)

        cfg = ttk.LabelFrame(self, text="配置"); cfg.pack(fill="x", padx=8)
        # ★ 2026-09-23: 位置改成下拉框。★ 这里【只能用字面默认值】★ ——
        #   _rc 要到下面(配置区之后)才加载, 在这儿读它会 NameError。
        #   读到 config 的 location 后再 set 一次校正。
        self.var_loc = tk.StringVar(value=LOCATION_CHOICES[0])
        self.var_avdir = tk.StringVar(value=str(Path.home() / "Desktop" / "运动头像"))
        self.var_gpxdir = tk.StringVar(value=str(Path.home() / "Desktop" / "芝加哥运动"))
        self.var_batch = tk.StringVar(value="15")
        self.var_cap = tk.StringVar(value="38")
        self.var_jobs = tk.StringVar(value="3")
        self.var_bg = tk.BooleanVar(value=True)
        self.var_close = tk.BooleanVar(value=True)
        # ★ 配置查找顺序和引擎(strava_ads.py)完全一致:
        #   本目录/config.json -> 本目录/配置/config.json
        #   -> 上级/配置/config.json -> 上级/config.json
        #   以前只找 界面/config.json, 开发布局下这个文件根本不存在, _rc 恒为 {},
        _rc = {}
        for _c in (ROOT / "config.json", ROOT / "配置" / "config.json",
                   ROOT.parent / "配置" / "config.json", ROOT.parent / "config.json"):
            try:
                if _c.exists():
                    _rc = json.loads(_c.read_text(encoding="utf-8"))
                    break
            except Exception:
                _rc = {}
        # ★ 采集州: 默认就是 config.json 里的 New York(纽约必扫)
        self._regions = _rc.get("collect_regions") or ["New York"]
        # ★★ 2026-09-23: 位置下拉框的初值在这里校正 ★★
        #   那个控件是在 _rc 加载【之前】建的(在配置区那一段), 所以建的时候
        #   只能用 LOCATION_CHOICES[0] 当默认 —— 不这样写会 NameError:
        #   _rc 要到这一行才存在。读到 config 的 location 后再 set 一次。
        #   ★ 不在名单里的老值也照样 set(只读下拉框允许显示名单外的值),
        #     不会把人家原来填的城市悄悄换成 Chicago。
        try:
            _lv = str(_rc.get("location") or "").strip()
            if _lv:
                self.var_loc.set(_lv)
        except Exception:
            pass
        # ★ 每段路段门槛: 默认 5000(不再是 200)
        # ★★ 这里不能写 `or 5000` ★★ —— 0 表示"不设门槛", 而 0 是 falsy,
        #   老写法会把 0 变成 5000, 下拉框里那个"0 (不设门槛)"选项
        #   选完再打开界面就变回 5000, 从来没真正生效过。
        try:
            self._min_ath = (int(_rc["min_athletes"])
                             if "min_athletes" in _rc else 5000)
        except Exception:
            self._min_ath = 5000

        # ★★ 2026-09-19 【管理员采集口径 —— 按版本号一次性生效】★★
        #   现象(用户实测): 同事更新完代码, 界面上却仍写着
        #       "12州(纽约必扫) ... 每段≥5000人"
        #   —— 门槛改了、采集州没改, 半截生效。两个根因都要治:
        #     1) 老发行包把 collect_regions 写成 12 个州、min_athletes 写成 200;
        #        update.py 的合并策略是"只补缺失的键, 绝不改已有值",
        #        所以这两个旧值永远改不掉(老 update.py 也替换不了自己)。
        #     2) 上一版纠正代码写的是 `_cur == _LEGACY_REGIONS`(列表全等),
        _fixed = {}
        try:
            _rev = int(_rc.get("_policy_rev") or 0)
        except Exception:
            _rev = 0
        if _rev < _ADMIN_POLICY_REV:
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
            # ★★ 2026-09-22: 地板从 200 降到 100 ★★
            #   下拉框新增了 100~900; 原来卡 `<200` 会把选中的 100
            #   【悄悄改成 200】再写回磁盘 —— 又是"选了没用"那个坑。
            if 0 < _ma_now < 100:
                self._min_ath = 200
                _fixed["min_athletes"] = 200
            # ★ 地板要跟着走: 引擎读的是 min_athletes_floor,
            #   只改 min_athletes 不动它, 引擎照样会抬回去。
            _fixed["min_athletes_floor"] = self._min_ath
            _fixed["_policy_rev"] = _ADMIN_POLICY_REV
        if _fixed:
            # ★★ 关键: 纠正结果必须【回写进 _rc】★★
            #   下面的 _max_fol / var_target / var_jobs 都还在读 _rc(见 L240/243/250)。
            #   不回写的话: 磁盘已经是对的, 界面却还显示旧值
            #   (实测到的现象: 磁盘 jobs 已是 3, 界面 var_jobs 仍显示 '1');
            _rc = {**_rc, **_fixed}
            try:
                # ★ 原子写: 直接 write_text 写一半被打断会留下截断的 JSON,
                #   下次启动 json.loads 失败 -> 界面直接起不来。
                _txt = json.dumps({**_rc, **_fixed}, ensure_ascii=False,
                                  indent=2) + "\n"
                _tmp = _c.with_name(_c.name + ".tmp")
                _tmp.write_text(_txt, encoding="utf-8")
                os.replace(_tmp, _c)
                self.log(f"★ 已按管理员口径纠正配置: {_fixed} (写回 {_c.name})")
            except Exception as _e:
                self.log(f"★ 纠正配置失败(仅本次生效): {str(_e)[:60]}")

        self._max_fol = int(_rc.get("max_followers") or 200)
        # ★ 原「每州路段」/「每段查人」两个输入框作废, 换成一个「每号目标人数」
        self.var_target = tk.StringVar(
            value=str(_rc.get("collect_target_per_account") or 200))
        # ★ 并发口径统一: 配置优先。
        #   以前并发数只在上面写死 "3", 而 config.json 里写的是 1 —— 同一份代码
        #   两个上游给同一个下游喂不同的值, 现场必然按写死的跑。
        #   ★ 2026-09-19 并发改造后: 界面/引擎的速率闸门已改成【按号分桶】,
        self.var_jobs.set(str(_rc.get("jobs", 3)))
        ttk.Label(cfg, text="位置").grid(row=0, column=0, sticky="e")
        # ★ 2026-09-23 用户要求: 位置也做成下拉框(原来是自由输入)
        #   state="readonly" —— 和性别/时间/年龄/每段那几个框一个样式,
        #   只能从名单里选; 选中的值由 _cfg() 的 "location" 带下去。
        ttk.Combobox(cfg, textvariable=self.var_loc, state="readonly",
                     width=22, values=list(LOCATION_CHOICES)).grid(
            row=0, column=1, sticky="w")
        ttk.Label(cfg, text="头像目录").grid(row=0, column=2, sticky="e")
        ttk.Entry(cfg, textvariable=self.var_avdir, width=36).grid(row=0, column=3, sticky="w")
        ttk.Button(cfg, text="浏览", width=5, command=lambda: self._pick(self.var_avdir)).grid(row=0, column=4)
        ttk.Label(cfg, text="轨迹目录").grid(row=1, column=2, sticky="e")
        ttk.Entry(cfg, textvariable=self.var_gpxdir, width=36).grid(row=1, column=3, sticky="w")
        ttk.Button(cfg, text="浏览", width=5, command=lambda: self._pick(self.var_gpxdir)).grid(row=1, column=4)
        f = ttk.Frame(cfg); f.grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="每批").pack(side="left")
        ttk.Entry(f, textvariable=self.var_batch, width=4).pack(side="left")
        ttk.Label(f, text="上限").pack(side="left")
        ttk.Entry(f, textvariable=self.var_cap, width=4).pack(side="left")
        # ★★ 2026-09-19 用户要求: 采集地区 / 年纪 做成框框供选择 ★★
        #   以前这两个位置是【静态文字】("12州(纽约必扫)" / "45-54 / 55-64 / 65-69"),
        #   想改只能去翻 config.json。
        #   采集地区单选 -> collect_regions = [选中项]。
        ttk.Label(cfg, text="采集地区").grid(row=2, column=0, sticky="e")
        _reg0 = self._regions[0] if self._regions else REGION_CHOICES[0]
        if _reg0 not in REGION_CHOICES:      # 兼容手改过 config 的老值
            _reg0 = REGION_CHOICES[0]
        self.var_region = tk.StringVar(value=_reg0)
        ttk.Combobox(cfg, textvariable=self.var_region, state="readonly",
                     width=32, values=list(REGION_CHOICES)).grid(
            row=2, column=1, sticky="w")
        ttk.Label(cfg, text="年纪").grid(row=2, column=2, sticky="e")
        self.var_age = tk.StringVar(value=_label_of(
            AGE_CHOICES, tuple(_rc.get("collect_age_groups") or ())))
        ttk.Combobox(cfg, textvariable=self.var_age, state="readonly",
                     width=26, values=[x[0] for x in AGE_CHOICES]).grid(
            row=2, column=3, sticky="w")
        f2 = ttk.Frame(cfg); f2.grid(row=2, column=4, sticky="w")
        ttk.Label(f2, text="并发").pack(side="left")
        ttk.Entry(f2, textvariable=self.var_jobs, width=4).pack(side="left")
        # ★ 原「每州路段」「每段查人」两个框已删, 合并成「每号目标人数」(1~2000)
        ttk.Label(f2, text="每号目标人数").pack(side="left")
        ttk.Spinbox(f2, from_=1, to=2000, width=5,
                    textvariable=self.var_target).pack(side="left")
        ttk.Checkbutton(cfg, text="后台运行", variable=self.var_bg).grid(row=0, column=5, sticky="w", padx=6)
        ttk.Checkbutton(cfg, text="完成关浏览器", variable=self.var_close).grid(row=1, column=5, sticky="w", padx=6)
        # ★ 执行内容: 用「▶ 开始任务」时才生效(「◎ 只采集」不受影响)
        # ★★ 2026-09-22 用户要求: 「开始任务」只管 注册/改资料/传轨迹, 【不采集】★★
        #   采集只归「◎ 只采集」。标签点名说清楚, 免得再被误会成"开始任务也会采"。
        ttk.Label(cfg, text="执行内容(不含采集)").grid(row=2, column=5, sticky="e", padx=(8, 2))
        self.var_taskmode = tk.StringVar(value=TASK_MODES[0])
        ttk.Combobox(cfg, textvariable=self.var_taskmode, state="readonly",
                     width=20, values=list(TASK_MODES)).grid(row=2, column=6, sticky="w")

        # ★★ 第二排: 性别 / 时间范围 (2026-09-19 用户要求做成框框) ★★
        #   以前这两项【写死】在引擎的榜单 URL 里(gender=male&date_range=this_month),
        #   界面上只印了"男性 · 本月"四个字, 没法改。
        #   现在存进 config.json 的 collect_gender / collect_date_range,
        ttk.Label(cfg, text="性别").grid(row=3, column=0, sticky="e")
        self.var_gender = tk.StringVar(value=_label_of(
            GENDER_CHOICES, str(_rc.get("collect_gender") or "male")))
        ttk.Combobox(cfg, textvariable=self.var_gender, state="readonly",
                     width=8, values=[x[0] for x in GENDER_CHOICES]).grid(
            row=3, column=1, sticky="w")
        ttk.Label(cfg, text="时间范围").grid(row=3, column=2, sticky="e")
        self.var_daterange = tk.StringVar(value=_label_of(
            DATE_CHOICES, str(_rc.get("collect_date_range") or "this_month")))
        ttk.Combobox(cfg, textvariable=self.var_daterange, state="readonly",
                     width=8, values=[x[0] for x in DATE_CHOICES]).grid(
            row=3, column=3, sticky="w")
        # ★ 2026-09-19 用户要求:「每段」做成框框供选择(原来是静态文字)
        ttk.Label(cfg, text="每段≥").grid(row=3, column=4, sticky="e")
        self.var_minath = tk.StringVar(value=_label_of(
            MIN_ATH_CHOICES, int(self._min_ath)))
        ttk.Combobox(cfg, textvariable=self.var_minath, state="readonly",
                     width=30, values=[x[0] for x in MIN_ATH_CHOICES]).grid(
            row=3, column=5, sticky="w")
        # ★★ 2026-09-23 用户要求: 活跃度自己设置 ★★
        #   = 资料页上"最近 N 天内有活动"的天数(引擎的 recent_days)。
        #   填 0 = 不按这条筛。默认读 config, 改完保存回 config。
        ttk.Label(cfg, text="活跃度").grid(row=4, column=0, sticky="e")
        self.var_recent = tk.StringVar(value=str(_rc.get("recent_days", 60)))
        ttk.Spinbox(cfg, from_=0, to=3650, width=6,
                    textvariable=self.var_recent).grid(row=4, column=1, sticky="w")
        ttk.Label(cfg, text="天内有过活动（0 = 不筛）").grid(
            row=4, column=2, columnspan=3, sticky="w", padx=(4, 0))
        ttk.Label(cfg, text="人 · 只判美国境内").grid(row=3, column=6,
                                                      sticky="w")
        # ★ 改选后立刻写回 config.json —— 下次打开界面还是你选的那个。
        #   用 trace_add 监听变量, 不用给控件存引用, 也不会漏绑。
        for _v in (self.var_region, self.var_age, self.var_gender,
                   self.var_daterange, self.var_minath, self.var_loc):
            try:
                _v.trace_add("write", self._save_collect_choice)
            except Exception:
                pass

        self.tree = ttk.Treeview(self, columns=FIELDS, show="headings", selectmode="extended", height=14)
        # ★★ 宽度按【字段名】给, 不再按位置 ★★
        #   原来是一串位置元组 widths = (50, 60, 190, 200, ...), 它对应的是
        #   "备注在第 3 列"那版列序。备注挪回最后一列之后, 位置元组会把宽度
        #   整体错配一格(账号变 190、密码变 200…), 表格看着乱七八糟。
        #   改成字典后, 不管列序怎么调, 每列宽度都跟着字段走。
        WIDTHS = {"seq": 50, "win": 60, "email": 200, "password": 100,
                  "login": 60, "name": 110, "city": 110, "acts": 60,
                  "prem": 60, "priv": 130, "note": 190,
                  "region": 170, "age": 180}
        # ★ 表格配色标签(斑马纹 + 登录状态)。背景和前景是两个不同的属性,
        #   同时挂 odd/even 和 good/bad 不会互相覆盖。
        try:
            self.tree.tag_configure("even", background="#FFFFFF")
            self.tree.tag_configure("odd", background="#F4F7FB")
            self.tree.tag_configure("good", foreground="#1E8449")
            self.tree.tag_configure("bad", foreground="#C0392B")
        except Exception:
            pass
        for c in FIELDS:
            self.tree.heading(c, text=HEADS[c])
            self.tree.column(c, width=WIDTHS.get(c, 100))
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", self._on_dbl)

        logf = ttk.LabelFrame(self, text="日志"); logf.pack(fill="both", expand=False, padx=8, pady=(0, 6))
        # ★ 2026-09-20 美化: 日志区从 9 行收到 6 行(把空间让给表格),
        #   换浅底 + 内边距, 看着像控制台而不是一块空白。
        self.logt = tk.Text(logf, height=6, relief="flat", background="#FBFCFD",
                            foreground="#2C3E50", padx=8, pady=6,
                            font=("Microsoft YaHei UI", 9))
        self.logt.pack(fill="both", expand=True, padx=2, pady=2)

    def _pick(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    # ---------------- 线程安全 ----------------
    def ui(self, fn, *a):
        try:
            self.uiq.put((fn, a))
        except Exception:
            pass

    def ui_sync(self, fn, *a):
        """在主线程里执行并等它返回。

        ★ 为什么必须有这个: Tk 不是线程安全的。子线程里直接读
          tree.get_children() 会【永久死锁】—— 不是抛异常, 是卡住不动。
          之前 _save_results() 就在扫描线程里读 tree, 于是扫描线程
          永远停在那一行, 结果一个字都没存, 界面还显示"已保存"。
        """
        if threading.current_thread() is threading.main_thread():
            return fn(*a)
        box, done = {}, threading.Event()

        def _do():
            try:
                box["r"] = fn(*a)
            except Exception as e:
                box["e"] = e
            finally:
                done.set()

        self.ui(_do)
        if not done.wait(timeout=15):
            raise RuntimeError("主线程未响应(界面可能在关闭)")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def _drain_ui(self):
        if not getattr(self, "_alive", True):
            return
        try:
            while not self.uiq.empty():
                fn, a = self.uiq.get()
                try:
                    fn(*a)
                except Exception as e:
                    self.log(f"UI错误: {e}")
            self._after_ui = self.after(150, self._drain_ui)
        except Exception:
            pass

    # ---------------- 采集计数 ----------------
    # ★★ 2026-09-20 用户要求:「在脚本界面加一个采集计数, 每天过了十二点更新」★★
    #   显示成   本次 1/3000 · 今日 1077
    #     · 本次 = 这次任务采到的条数 / 本次目标(号数 × 每号目标)
    #     · 今日 = 当天成果文件的总条数(过了 00:00 自动从新文件重新算)
    #   以前想知道采了多少只能去翻 数据\链接-日期.txt 的行数, 而窗口显示
    #   会卡住(点一下黑窗口就停), 很容易误判成"没在采"。

    def _today_file(self):
        """当天成果文件。★ 直接用引擎的 _daily_path(), 保证和真正写盘的是同一个。"""
        try:
            return SA._daily_path()
        except Exception:
            return None

    def _count_today(self):
        """当天成果文件里有多少条链接(跳过 # 注释和空行)。读不到返回 None。"""
        p = self._today_file()
        if p is None:
            return None
        try:
            if not p.is_file():
                return 0
            n = 0
            for line in p.read_text(encoding="utf-8",
                                    errors="replace").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    n += 1
            return n
        except Exception:
            return None

    def _tick_today(self):
        """实时刷新计数(每 1 秒)。

        ★★ 2026-09-20 用户要求:「链接改成实时更新」★★
          原来是 5 秒一次, 看着还是"半天不动"。现在 1 秒一次。
        ★ 每秒都重读文件是浪费 —— 这里用 (mtime, 大小) 当指纹, 只有文件
          真的变了才重新数一遍。采集时每秒都有新链接, 界面上就是一条一条
          往上跳; 空闲时那次 stat 的开销可以忽略。
        ★ 跨零点自动归零: 文件名里带日期(_daily_path 按当天算), 过了 00:00
          路径就变成新的一天, 今日计数自然从头开始 —— 不需要任何"到点重置"
          的定时器, 也不会出现"过了十二点还显示昨天"。
        ★ 任务跨零点时, 把本次任务的起点也挪到新的一天, 否则"本次"会算成负数。
        """
        try:
            p = self._today_file()
            n = None
            if p is not None:
                try:
                    st = p.stat() if p.is_file() else None
                except Exception:
                    st = None
                if st is None:
                    n = 0
                    self._cnt_key, self._cnt_val = None, 0
                else:
                    key = (str(p), st.st_mtime_ns, st.st_size)
                    if key == getattr(self, "_cnt_key", None):
                        n = getattr(self, "_cnt_val", 0)    # 没变, 沿用上次的数
                    else:
                        n = self._count_today()
                        self._cnt_key, self._cnt_val = key, n
            day = datetime.datetime.now().strftime("%Y%m%d")
            if n is None:
                txt = "今日 -- 条"
            else:
                if getattr(self, "_task_day", None) != day and getattr(
                        self, "_task_goal", 0):
                    self._task_base = 0      # 新的一天: 今天的都算本次的
                    self._task_day = day
                if getattr(self, "_task_goal", 0):
                    done = max(0, n - (self._task_base or 0))
                    txt = f"本次 {done}/{self._task_goal} · 今日 {n}"
                else:
                    txt = f"今日 {n} 条"
            if txt != getattr(self, "_cnt_txt", None):    # 文字没变就不动控件
                self.lbl_today.config(text=txt)
                self._cnt_txt = txt
        except Exception:
            pass
        finally:
            try:
                self.after(1000, self._tick_today)
            except Exception:
                pass

    def log(self, msg):
        self.logq.put(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
        # ★★ 2026-09-20 修: 界面自己的消息以前【一个字都不落盘】★★
        #   只有 self.logq.put -> 屏幕上显示一下就没了。后果:
        #   用户报"怎么又停了", 我们去翻 logs/run_*.log, 里面全是引擎的消息,
        #   界面的「N 号没账号密码,跳过」「60 秒内没跑完」「界面已先复位」
        #   一条都查不到 —— 而这些恰恰是判断"到底发生了什么"最关键的几句。
        #   现在同一条也写进那个日志文件。
        try:
            _gui_file_logger().info("[gui] %s", msg)
        except Exception:
            pass

    # 日志框里最多留多少行。超了从【头部】删掉一批。
    # ★ 只影响屏幕上显示的内容; logs/run_*.log 那个文件是完整的
    #   (界面自己的消息现在也会写进去, 见 log())。
    LOG_MAX_LINES = 800
    LOG_TRIM_TO = 500        # 超限时一次删到剩这么多(避免每轮都删一点)

    def _drain_log(self):
        """把日志队列搬到文本框。

        ★★ 2026-09-20 性能修复(用户反馈"换上主题非常卡") ★★
          实测真正的瓶颈不是主题, 是这里:
            旧写法 while not empty(): insert(...)  —— 【一行一次 insert】,
            而且【从不删除旧行】。Tk 的 Text 每插一行都要重排, 行数上万后
            每次插入都越来越慢, 采集跑久了界面就点不动了。
          现在:
            ① 一次取出全部, join 成一段, 只 insert 【一次】
            ② 超过 LOG_MAX_LINES 就从头部删到 LOG_TRIM_TO
        """
        if not getattr(self, "_alive", True):
            return
        try:
            n = self.logq.qsize()
            if n:
                lines = []
                for _ in range(n):
                    try:
                        lines.append(self.logq.get_nowait())
                    except Exception:
                        break
                if lines:
                    self.logt.insert("end", "\n".join(lines) + "\n")
                    # 行数上限: 超了就从头部删一批
                    try:
                        _cur = int(self.logt.index("end-1c").split(".")[0])
                        if _cur > self.LOG_MAX_LINES:
                            _cut = _cur - self.LOG_TRIM_TO
                            self.logt.delete("1.0", f"{_cut + 1}.0")
                    except Exception:
                        pass
                    self.logt.see("end")
            self._after_log = self.after(200, self._drain_log)
        except Exception:
            pass

    def destroy(self):
        self._alive = False
        # ★ 取消还在排队的 after 定时器。不取消的话窗口一关, Tk 会去调
        #   已经消失的回调, 控制台就冒
        #   invalid command name "..._drain_ui" 这种报错。
        for _aid in ("_after_ui", "_after_log"):
            try:
                _i = getattr(self, _aid, None)
                if _i:
                    self.after_cancel(_i)
                    setattr(self, _aid, None)
            except Exception:
                pass
        try:
            self._save_results()
        except Exception:
            pass
        try:
            SA.STOP_EVENT.set()
        except Exception:
            pass
        try:
            n = SA.ads_close_all()
            if n:
                print(f"退出前已关闭 {n} 个浏览器")
        except Exception:
            pass
        super().destroy()

    # ---------------- 结果持久化 ----------------
    def _save_results(self):
        """保存扫描结果。返回文件里的总条数, 0 表示失败。

        ★ 两个坑都在这儿:
          1) 子线程里读 tree 会死锁 —— 所以先切回主线程再读。
          2) 合并写入, 不是整体覆盖。表格里没有的行必须保留文件里的
             原值, 否则一次"加载到 0 个账号"就能把结果全清空。
        """
        if threading.current_thread() is not threading.main_thread():
            try:
                return self.ui_sync(self._save_results)
            except Exception as e:
                self.log(f"结果保存失败(切主线程超时): {str(e)[:60]}")
                return 0
        try:
            # ★ 读不出来 + 文件非空 = 坏文件: 此时 data 只剩表格里的行,
            #   落盘就等于把文件里其余结果一次性清零 —— 宁可这次不保存。
            old, _bad = load_json_checked(RES_FILE)
            if _bad:
                self.log(f"★ 结果文件解析失败(可能写坏了): {RES_FILE}")
                self.log("  已中止本次保存 —— 不用空表覆盖磁盘上的结果")
                return 0
            data = dict(old)
            for iid in self.tree.get_children():
                try:
                    v = self.tree.item(iid, "values")
                except Exception:
                    continue
                if not v:
                    continue
                data[str(v[I_SEQ])] = dict(zip(FIELDS, v))
            if not save_json(RES_FILE, data):
                self.log("★ 结果写入失败 —— 检查文件是否被占用/只读")
                return 0
            return len(data)
        except Exception as e:
            self.log(f"★ 结果保存失败: {str(e)[:80]}")
            return 0

    def _restore(self):
        # ★ 坏文件不拿空值重建表格(表格一空, 下一次 _save_results 就会把结果清零)
        data, _bad = load_json_checked(RES_FILE)
        if _bad:
            self.log(f"★ 上次的结果读不出来(文件可能写坏了): {RES_FILE}")
            self.log("  已跳过恢复 —— 表格保持空白, 磁盘上的文件没有被改动")
            return 0
        # ★★ 读入时自愈: 磁盘上若有"整行左移一格"的历史坏数据, 在这里掰回来,
        #   并写回磁盘 —— 否则界面会一直显示错的、再原样存回去, 永远错下去。
        _acc, _ = load_json_checked(ACC_FILE)      # ★ 密码要按邮箱从这里找回来
        data, _healed = heal_shifted(data, _acc)
        if _healed:
            self.log(f"★ 检测到 {_healed} 条记录的列是错位的(备注列位置改过的后遗症), "
                     f"已自动掰回并写回文件")
            try:
                save_json(RES_FILE, data)
            except Exception as e:
                self.log(f"  (写回失败, 仅本次内存生效: {str(e)[:50]})")
        n = 0
        for k, d in data.items():
            try:
                self.tree.insert("", "end", iid=str(k), values=[d.get(f, "") for f in FIELDS])
                n += 1
            except Exception:
                continue
        return n

    # ---------------- 手动刷新结果 ----------------
    def refresh_results(self):
        """⟳ 从磁盘重新读结果文件, 把表格整个重刷一遍。

        什么时候用:
          * 扫描完了, 表格里却没出现结果
          * 表格里的资料看着不完整 / 对不上
          * 想确认磁盘上到底存了多少

        ★ 跑在主线程上(只读一个小 json), 不碰任何线程相关的东西。
        ★ 只读不写 —— 刷新不会改变磁盘上的内容。
        """
        try:
            # ★ 刷新绝不会把"读坏"当成"文件是空的": 后者会清空表格并谎报
            #   "结果文件是空的", 用户以为成果丢了就可能去重扫/重跑。
            res, _rbad = load_json_checked(RES_FILE)
            acc, _abad = load_json_checked(ACC_FILE)
            if _rbad or _abad:
                self.log(f"★ 读不出来的文件: {RES_FILE if _rbad else ACC_FILE}")
                self.log("  已中止本次刷新 —— 不拿空值重建表格, 磁盘内容未改动")
                return
            # ★★ 刷新时也自愈一次: 别把错位的数据原样搬到表格里
            res, _healed = heal_shifted(res, acc)
            if _healed:
                self.log(f"★ 刷新时检测到 {_healed} 条记录列错位, 已自动掰回")

            before = len(self.tree.get_children())
            updated = added = 0

            # 1) 表格里已有的行: 用文件里的值补齐/更新
            for iid in self.tree.get_children():
                try:
                    v = list(self.tree.item(iid, "values"))
                except Exception:
                    continue
                seq = str(v[I_SEQ])
                r = res.get(seq) or {}
                a = acc.get(str(v[I_WIN])) or acc.get(seq) or {}
                # 账号密码: 空着才补, 不覆盖手工填的
                # ★ 下标必须走 I_EMAIL / I_PWD —— 写死 2/3 会把邮箱填进备注列
                if not str(v[I_EMAIL]).strip() and a.get("email"):
                    v[I_EMAIL] = a["email"]
                # ★ 密码: 空着【或者还赖着 是/否 这种坏值】都得补 ——
                #   旧版只在空着时补, 坏值就永远顶不掉, 还会被存回账号文件
                pwd = str(v[I_PWD]).strip()
                if not pwd or pwd in _YESNO:
                    src = str(r.get("password") or "").strip() \
                        or str(a.get("password") or "").strip()
                    if src and src not in _YESNO:
                        v[I_PWD] = src
                # 资料字段: 文件里有值就以文件为准
                for name in PROFILE_COLS:
                    idx = FIELDS.index(name)
                    val = r.get(name)
                    if str(val or "").strip() and str(val) != str(v[idx]):
                        v[idx] = val
                self.tree.item(iid, values=tuple(v))
                updated += 1

            # 2) 文件里有、表格里没有的 -> 补进来
            for seq, r in res.items():
                if not isinstance(r, dict) or self.tree.exists(str(seq)):
                    continue
                a = acc.get(str(r.get("win") or "")) or acc.get(str(seq)) or {}
                # ★ 用 row_from 按 FIELDS 生成, 不再手写列序 ——
                #   手写的那串是按老列序(备注在最后)排的, 补进来的行会整行错位
                self.tree.insert("", "end", iid=str(seq),
                                 values=row_from(seq, r, a))
                added += 1

            withdata = sum(1 for v in res.values()
                           if isinstance(v, dict)
                           and str(v.get("name") or "").strip())
            self.log(f"⟳ 已刷新: 表格 {before} 行 → "
                     f"{len(self.tree.get_children())} 行 "
                     f"(更新 {updated}, 补入 {added})")
            self.log(f"   结果文件共 {len(res)} 条, 其中 {withdata} 条带资料")
            if not res:
                self.log(f"   ★ 结果文件是空的: {RES_FILE}")
                self.log("     还没扫描过, 或者扫描结果存到了别的位置")
        except Exception as e:
            self.log(f"刷新失败: {str(e)[:100]}")

    # ---------------- 账号密码编辑 ----------------
    def _on_dbl(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        try:
            cname = FIELDS[int(col[1:]) - 1]
        except Exception:
            return
        if cname not in ("email", "password", "region", "age"):
            return
        rowid = self.tree.identify_row(event.y)
        if not rowid:
            return
        bbox = self.tree.bbox(rowid, col)
        if not bbox:
            return
        x, y, w, h = bbox
        if cname in ("region", "age"):
            # ★ 2026-09-24 用户要求: 「每个账号可以单独选择采集什么地区…年纪」。
            #   双击这两列弹下拉框, 选完只写回本行; 清空(第一项"")= 用默认。
            #   和上面两个下拉框同一份选项, 口径天然一致。
            opts = ("",) + (tuple(REGION_CHOICES) if cname == "region"
                            else tuple(lab for lab, _ in AGE_CHOICES))
            cb = ttk.Combobox(self.tree, values=opts, state="readonly")
            cb.place(x=x, y=y, width=max(w, 180), height=h)
            cb.set(self.tree.set(rowid, cname))
            cb.focus_set()

            def commit2(_=None, _cb=cb):
                self.tree.set(rowid, cname, _cb.get().strip())
                _cb.destroy()
                self._save_results()
                self.log(f"  {self.tree.set(rowid, 'seq')} 号 {HEADS[cname]} = "
                         f"{_cb.get().strip() or '(默认)'}")
            cb.bind("<<ComboboxSelected>>", commit2)
            cb.bind("<FocusOut>", commit2)
            cb.bind("<Return>", commit2)
            try:
                cb.event_generate("<Button-1>")     # 直接展开, 少点一次
            except Exception:
                pass
            return
        e = tk.Entry(self.tree)
        e.place(x=x, y=y, width=w, height=h)
        e.insert(0, self.tree.set(rowid, cname))
        e.focus_set(); e.select_range(0, "end")

        def commit(_=None):
            self.tree.set(rowid, cname, e.get().strip())
            e.destroy()
            self._save_accounts()
            self._save_results()
        e.bind("<Return>", commit)
        e.bind("<FocusOut>", commit)
        e.bind("<Escape>", lambda ev: e.destroy())

    def _save_accounts(self):
        try:
            # ★ 账号文件读坏时不能拿"表格里这几行"当全部覆盖写回:
            #   那会把文件里其余账号密码整批抹掉。
            data, _bad = load_json_checked(ACC_FILE)
            if _bad:
                self.log(f"★ 账号文件解析失败(可能写坏了): {ACC_FILE}")
                self.log("  已中止本次保存 —— 刚才手工填的密码没写进文件")
                return
            for iid in self.tree.get_children():
                v = self.tree.item(iid, "values")
                key = str(v[I_WIN]) if v[I_WIN] else str(v[I_SEQ])
                # ★★ 这里原来写的是 v[2] / v[3] ★★
                #   v[2] 是【备注】、v[3] 才是【账号】—— 错位一格, 会把
                #   备注当账号、账号当密码写进磁盘, 是真的写坏账号文件。
                # ★★ 最后一道闸: 密码列若是 是/否 这种坏值(列错位的后遗症),
                #    绝不能写进账号文件 —— 一写就把里面仅存的那份真密码冲掉,
                #    这次真密码就是这么丢的。坏值一律保留文件里原来的密码。
                pwd = v[I_PWD]
                if str(pwd).strip() in _YESNO:
                    pwd = (data.get(key) or {}).get("password") or ""
                if v[I_EMAIL] or pwd:
                    data[key] = {"email": v[I_EMAIL], "password": pwd}
            save_json(ACC_FILE, data)
        except Exception as e:
            self.log(f"账号保存失败: {str(e)[:80]}")

    # ---------------- 范围 ----------------
    def _range_ids(self):
        try:
            a = int(str(self.var_from.get()).strip() or 1)
        except Exception:
            a = 1
        try:
            b = int(str(self.var_to.get()).strip() or 9999)
        except Exception:
            b = 9999
        if b < a:
            a, b = b, a
        out = []
        for iid in self.tree.get_children():
            v = self.tree.item(iid, "values")
            try:
                s = int(v[I_SEQ])
            except Exception:
                continue
            if a <= s <= b:
                out.append(s)
        if not out and self.items:
            for it in self.items:
                s = it["seq"]
                if a <= s <= b:
                    out.append(s)
            out.sort()
        return out

    # ---------------- 加载/扫描 ----------------
    def load_items(self):
        # ★ 运行中不许加载: _fill 会把表格整个 delete 再重建, 扫描回填/任务
        #   结果会被一次性抹掉(而表格是 _save_results 的数据源)。
        if getattr(self, "running", False) or getattr(self, "scanning", False):
            self.log("任务/扫描进行中 —— 加载会覆盖已回填结果, 已忽略")
            return
        threading.Thread(target=self._load_work, daemon=True).start()

    def _load_work(self):
        try:
            items = SA.list_items()
            self.items = items
            # ★ 读坏(文件非空却解析不出来)时中止加载: 下面 _fill 会重建整张表,
            #   用空值重建 = 屏幕上 100 行结果当场消失。
            acc, _abad = load_json_checked(ACC_FILE)
            res, _rbad = load_json_checked(RES_FILE)
            if _abad or _rbad:
                self.log(f"★ 读不出来的文件: {ACC_FILE if _abad else RES_FILE}")
                self.log("  已中止加载 —— 表格保持原样, 磁盘内容未改动")
                return
            rows = []
            for it in items:
                seq, win = it["seq"], it["win"]
                email, pwd = it.get("email", ""), it.get("password", "")
                a = acc.get(win) or acc.get(str(seq)) or {}
                if a.get("email"):
                    email = a["email"]
                if a.get("password"):
                    pwd = a["password"]
                r = res.get(str(seq), {})
                # ★ 列序必须和 FIELDS 一致: 备注在账号前面
                #   账号来源优先级: 账号文件(acc) > 环境信息(it)
                #   备注来源优先级: 扫描结果(r) > 环境信息(it)
                _note = r.get("note", "") or it.get("note", "")
                if not pwd:
                    pwd = it.get("password", "")
                rows.append((seq, win, _note, email, pwd,
                             r.get("login", ""), r.get("name", ""), r.get("city", ""),
                             r.get("acts", ""), r.get("prem", ""), r.get("priv", "")))
            if not rows:
                self.log("加载到 0 个环境 —— 已保留表格里的原有内容(不清空)")
                return
            self.ui(self._fill, rows)
            self.log(f"加载 {len(rows)} 个账号")
        except Exception as e:
            self.log(f"加载失败: {str(e)[:120]}")

    def _fill(self, rows):
        """重建表格。★ 只加视觉标签(斑马纹/登录状态配色), 数据结构一字未动。"""
        self.tree.delete(*self.tree.get_children())
        try:
            _li = FIELDS.index("login")
        except Exception:
            _li = -1
        for _i, r in enumerate(rows):
            tags = ["odd" if _i % 2 else "even"]
            try:
                _v = str(r[_li]).strip() if _li >= 0 else ""
                if _v == "是":
                    tags.append("good")
                elif _v == "否":
                    tags.append("bad")
            except Exception:
                pass
            self.tree.insert("", "end", iid=str(r[0]), values=r, tags=tuple(tags))

    def scan_all(self):
        ids = self._range_ids()
        if not ids:
            self.log("没有可扫描的账号")
            return
        self.log(f"开始扫描 {len(ids)} 个...")
        # ★ 扫描中: 置标志 + 禁用「1.连接并加载」(它重建表格会抹掉回填结果)
        self.scanning = True
        try:
            self.btn_load.config(state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._scan_work, args=(ids,), daemon=True).start()

    def _scan_work(self, ids):
        try:
            for seq in ids:
                if self.stop_flag.is_set():
                    self.log("已停止扫描")
                    break
                try:
                    r = SA.scan_one(seq)
                    if not r:
                        self._set(seq, "note", "打不开")
                        continue
                    # ★ 2026-09-19 修复: 只写【非空】值。
                    #   以前是无条件写这 6 列, 于是"扫描到未登录 / 读不到数据"时,
                    #   空值会把表格和 ads_results.json 里【原有的好数据一起清掉】。
                    #   登录列例外: "是/否" 本身就是有效结论, 永远写。
                    for k in ("login", "name", "city", "acts", "prem", "priv"):
                        v = r.get(k, "")
                        _empty = str(v or "").strip() in ("", "None", "-1", "?",
                                                          "小组None/地图None/时间None")
                        if k == "login" or not _empty:
                            self._set(seq, k, v)
                        else:
                            _old = ""
                            try:
                                _old = str(self.tree.set(str(seq), k) or "")
                            except Exception:
                                pass
                            if _old.strip():
                                self.log(f"  {seq} {k} 本次读不到, 保留原值 {_old[:30]}")
                    self.log(f"  {seq}: 登录={r.get('login')} 名字={r.get('name')} 活动={r.get('acts')} 会员={r.get('prem')}")
                except Exception as e:
                    self.log(f"  {seq} 扫描异常: {str(e)[:80]}")
            n = self._save_results()
            if n:
                self.log(f"扫描完成, 结果已保存(共 {n} 条)")
            else:
                self.log("★ 扫描完成, 但结果保存失败 —— 截图发管理员")
        finally:
            # ★ 无论扫描怎么结束都要放开守卫, 否则「加载」按钮永远点不动
            self.scanning = False
            self.ui(self._scan_idle)

    def _scan_idle(self):
        try:
            self.btn_load.config(state="normal")
        except Exception:
            pass

    def _set(self, seq, col, val):
        def _do():
            try:
                v = list(self.tree.item(str(seq), "values"))
                v[FIELDS.index(col)] = val
                self.tree.item(str(seq), values=tuple(v))
            except Exception:
                pass
        self.ui(_do)

    def preview(self):
        ids = self._range_ids()
        if not ids:
            self.log("没有可分配的账号")
            return
        # ★ 必须和执行口径完全一致: 引擎 run_one_seq 是 (seq-1)%50 取名字,
        #   老写法 english_names(len(ids)) + zip 是按顺序发, 编号一错位,
        #   预览显示的名字和真跑出来的人完全对不上(预览骗人)。
        #   name_for_seq 是引擎新增的; 引擎还没更新时退回老逻辑, 保证界面能起来。
        _name_of = getattr(SA, "name_for_seq", None)
        if _name_of is None:
            self.log("提示: 引擎未更新(没有 name_for_seq), 预览按老方式顺序分配")
        try:
            if _name_of is not None:
                for seq in ids:
                    try:
                        self._set(seq, "note", _name_of(seq))
                    except Exception:
                        pass
            else:
                names = SA.english_names(len(ids))
                for seq, nm in zip(ids, names):
                    self._set(seq, "note", nm)
            self.log(f"已预览 {len(ids)} 个名字(执行时按编号分配头像)")
        except Exception as e:
            self.log(f"分配失败: {e}")

    # ---------------- 执行 ----------------
    def _save_collect_choice(self, *_a):
        """★ 把界面上选的采集口径写回 config.json —— 下次打开还是你选的那个。

        ★★ 为什么必须写盘(两条路缺一不可) ★★
          引擎的模块级 CFG 是【导入时】读的一次性快照, 而界面只在启动时
          加载一次引擎。所以:
            · 同一次会话内 -> 靠 _cfg() 把值当参数传给引擎(已打通)
            · 下次启动     -> 靠这里写进 config.json
          只做一条, 就会出现"在下拉框选了 Central Park, 跑起来还是 New York"。
        ★ 只动这 4 个键; 浏览器 key / 头像目录 / 账号文件一律不碰。
        """
        try:
            _p = None
            for _c in (ROOT / "config.json", ROOT / "配置" / "config.json",
                       ROOT.parent / "配置" / "config.json",
                       ROOT.parent / "config.json"):
                if _c.exists():
                    _p = _c
                    break
            if _p is None:
                return
            _d = json.loads(_p.read_text(encoding="utf-8"))
            # ★ 2026-09-23: 位置也一起写回 —— 它现在是下拉框, 改选后必须落盘,
            #   否则下次打开又变回旧城市, 而改资料时用的是框里那个值。
            _d["location"] = str(self.var_loc.get() or "").strip() \
                or _d.get("location") or "Chicago, Illinois"
            _d["collect_regions"] = [self.var_region.get()]
            _d["collect_gender"] = _value_of(GENDER_CHOICES,
                                             self.var_gender.get())
            _d["collect_date_range"] = _value_of(DATE_CHOICES,
                                                 self.var_daterange.get())
            _d["collect_age_groups"] = list(_value_of(AGE_CHOICES,
                                                      self.var_age.get()))
            # ★ 每段人数门槛: 两个键一起写。
            #   min_athletes 是实际用的值; min_athletes_floor 是引擎里的地板 ——
            #   只写前者的话, 选 2000 会被地板抬回 5000(选了没用)。
            _ma = int(_value_of(MIN_ATH_CHOICES, self.var_minath.get()))
            _d["min_athletes"] = _ma
            _d["min_athletes_floor"] = _ma
            # ★ 原子写: 直接 write_text 写一半被打断会留下截断的 JSON,
            #   下次启动 json.loads 失败 -> 界面直接起不来。
            _tmp = _p.with_name(_p.name + ".tmp")
            _tmp.write_text(json.dumps(_d, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            os.replace(_tmp, _p)
        except Exception as _e:
            try:
                self.log(f"★ 采集口径写回配置失败(仅本次生效): {str(_e)[:60]}")
            except Exception:
                pass

    def _cfg(self):
        # ★ 「每号目标人数」: 取不到合法整数就退回 200(Spinbox 正常只会给数字)
        try:
            _tgt = int(str(self.var_target.get()).strip())
        except Exception:
            _tgt = 200
        if _tgt <= 0:
            _tgt = 200
        return {
            "location": self.var_loc.get(),
            "avatar_dir": self.var_avdir.get(),
            "gpx_dir": self.var_gpxdir.get(),
            "per_batch": self.var_batch.get(),
            "daily_cap": self.var_cap.get(),
            "jobs": self.var_jobs.get(),
            "background": bool(self.var_bg.get()),
            "auto_close": bool(self.var_close.get()),
            # ★ 2026-09-19: 这四项改成读界面上的下拉框(用户要求"做框框供选择")
            #   引擎侧: collect_regions 决定去哪个地区找路段(会去掉括号里的城市名);
            #           collect_gender / collect_date_range / collect_age_groups
            #           决定排行榜筛选(以前写死 男性/本月/45-54+55-64+65-69)。
            "collect_regions": [self.var_region.get()],
            "collect_gender": _value_of(GENDER_CHOICES, self.var_gender.get()),
            "collect_date_range": _value_of(DATE_CHOICES,
                                            self.var_daterange.get()),
            "collect_age_groups": list(_value_of(AGE_CHOICES, self.var_age.get())),
            # ★ 每段人数门槛走界面下拉框(同时把地板设成同一个值,
            #   否则引擎的 MIN_ATHLETES_FLOOR 会把低于 5000 的选择抬回去)
            "min_athletes": int(_value_of(MIN_ATH_CHOICES,
                                          self.var_minath.get())),
            "min_athletes_floor": int(_value_of(MIN_ATH_CHOICES,
                                                self.var_minath.get())),
            "max_followers": self._max_fol,
            # ★ 「每州路段」「每段查人」已作废, 不再下发 segs_per_region /
            #   check_per_segment; 每个号要采到多少人由这里决定
            "collect_target_per_account": _tgt,
            "task_mode": self.var_taskmode.get(),
            # ★ 2026-09-23: 活跃度(最近 N 天内要有活动)。0 = 不筛。
            #   ★ 年龄和时间【不在这里写死】—— 上面 collect_age_groups /
            #     collect_date_range 就是界面那两个下拉框的值,
            #     「◎ 精准采集」走的也是这份 cfg, 所以两边口径天然一致。
            "recent_days": _spin_int(self.var_recent.get(), 60),
        }

    def _start(self, mode):
        if self.running:
            self.log("任务正在运行")
            return
        ids = self._range_ids()
        if not ids:
            self.log("没有可执行的账号")
            return
        creds = {}
        # ★★ 2026-09-24: 按号采集设置(地区/年龄)【必须在主线程读出来】★★
        #   子线程里读 self.tree 会死锁 —— _save_results 的注释里记过这个坑。
        #   所以在这里一次读完, 打包传给 _work。
        rowset = {}
        for iid in self.tree.get_children():
            v = self.tree.item(iid, "values")
            try:
                # ★ 下标走 FIELDS —— 写死 (v[2], v[3]) 会拿【备注】当账号去登录
                _s = int(v[I_SEQ])
                creds[_s] = (v[I_EMAIL], v[I_PWD])
                _r = str(v[FIELDS.index("region")] or "").strip()
                _a = str(v[FIELDS.index("age")] or "").strip()
                if _r or _a:
                    rowset[_s] = (_r, _a)
            except Exception:
                continue
        if rowset:
            self.log("按号采集设置: " + "; ".join(
                f"{s}号→{r or '默认地区'}/{a or '默认年龄'}"
                for s, (r, a) in sorted(rowset.items())))
        miss = [s for s in ids if not (creds.get(s, ("", ""))[0] and creds.get(s, ("", ""))[1])]
        if miss:
            self.log(f"注意: {len(miss)} 个没填账号密码,会跳过: {miss[:10]}")
        self.stop_flag.clear()
        try:
            SA.STOP_EVENT.clear()
        except Exception:
            pass
        self.running = True
        self.btn_start.config(state="disabled")
        self.btn_collect.config(state="disabled")
        try:
            self.btn_precise.config(state="disabled")
        except Exception:
            pass
        self.btn_stop.config(state="normal")
        # ★ 运行中也禁用「加载」: 它会把表格 delete 掉重建, 冲掉正在回填的结果
        try:
            self.btn_load.config(state="disabled")
        except Exception:
            pass
        self.lbl_run.config(text=f"运行中({mode})")
        self.log(f"开始{mode}: 编号 {ids[0]}~{ids[-1]} 共 {len(ids)} 个")
        # ★ 采集计数: 记下本次任务的【起点条数】和【本次目标】
        #   起点用差值算, 所以"本次"不会被今天早先采的那些污染。
        try:
            self._task_base = self._count_today() or 0
        except Exception:
            self._task_base = 0
        try:
            _each = int(str(self.var_target.get()).strip())
        except Exception:
            _each = 200
        if _each <= 0:
            _each = 200
        self._task_goal = max(0, len(ids) * _each)
        self._task_day = datetime.datetime.now().strftime("%Y%m%d")
        try:
            threading.Thread(target=self._work,
                             args=(ids, mode, creds, self._cfg(), rowset),
                             daemon=True).start()
        except Exception as e:
            # ★ 线程都没起来就别把界面锁在"运行中"(按钮已禁用, 只能靠 _idle 放开)
            self.log(f"★ 任务线程启动失败: {str(e)[:80]}")
            self._idle()

    def start_task(self):
        self._start("任务")

    def start_collect(self):
        self._start("采集")

    def start_precise(self):
        """精准采集: 地区固定为 PRECISE_REGIONS(29 个), 其它筛选和「只采集」一样。"""
        self._start("精准采集")

    def close_browsers(self):
        """关闭所有残留浏览器"""
        self.log("正在关闭全部浏览器...")

        def _do():
            try:
                n = SA.ads_close_all()
                self.log(f"已关闭 {n} 个浏览器")
            except Exception as e:
                self.log(f"关闭失败: {str(e)[:80]}")
        threading.Thread(target=_do, daemon=True).start()

    def stop_task(self):
        if self.running:
            self.stop_flag.set()
            try:
                SA.STOP_EVENT.set()
            except Exception:
                pass
            self.log("已停止:正在中断当前动作并关闭浏览器(最多几秒)...")
            self.lbl_run.config(text="停止中...")
            try:
                self.btn_stop.config(state="disabled")
            except Exception:
                pass

    def _work(self, ids, mode, creds, cfg, rowset=None):
        import concurrent.futures as cf
        try:
            # ★ 配置优先(以前写死 3, 与 config.json 打架)。上限收到 3:
            #   原上限 8 是"防跑飞"数字, 不是建议值。
            jobs = max(1, min(int(cfg["jobs"] or 1), 3))
        except Exception:
            jobs = 1
        if jobs > 1:
            self.log(f"并发 {jobs} 个号: 每个号各有一份独立的请求速率预算"
                     f"(rate_*_sec), 真并行。机器负载与 AdsPower 接口仍是共享的, "
                     f"卡顿就把并发调小。")

        # ★ 任务上下文: 一次任务 = 界面点一次开始。t_start 只在这里取一次,
        #   号级明细和任务成品文件都靠它命名(用户硬需求: 每次任务独立带时间的 txt)。
        #   引擎没更新 / 建上下文失败都不许影响采集, 失败就退回 None(老行为)。
        try:
            _task = SA.new_task_ctx(
                target=int(cfg.get("collect_target_per_account") or 0) or None,
                mode=mode,
                worker=os.environ.get("STRAVA_WORKER", "") or "")
        except Exception:
            _task = None
        self.log(f"任务开始 {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

        def _autofill(seq, res):
            """把引擎返回的状态自动填回表格

            ★ 「▶ 开始任务」和「◎ 只采集」共用这一套。用户明确要求:
              "不管开始任务还是扫描任务, 都要自动把数据填入脚本。"
              以前只有开始任务会填, 扫描任务跑完表格那几列还是空的。
            """
            if not isinstance(res, dict):
                return
            _lg = res.get("login")
            if _lg is not None:
                self._set(seq, "login", "是" if _lg else "否")
            for _k in ("name", "city", "acts", "prem", "priv"):
                _v = res.get(_k)
                if _v not in (None, ""):
                    self._set(seq, _k, _v)

        if mode == "精准采集":
            # ★★ 2026-09-23: 地区换成固定名单, 【其余一个都不动】——
            #   年龄/时间/性别/门槛/活跃度全部照界面上那套走。
            cfg = dict(cfg)
            cfg["collect_regions"] = list(PRECISE_REGIONS)
            self.log(f"精准采集: 地区固定为 {len(PRECISE_REGIONS)} 个 —— "
                     + "、".join(PRECISE_REGIONS[:5]) + " …")
            self.log(f"   年龄={cfg.get('collect_age_groups')} "
                     f"时间={cfg.get('collect_date_range')} "
                     f"性别={cfg.get('collect_gender')} "
                     f"活跃度={cfg.get('recent_days')}天")

        def _one(seq):
            if self.stop_flag.is_set():
                self.log(f"  {seq} 已停止,跳过")
                return
            email, pwd = creds.get(seq, ("", ""))
            if not (email and pwd):
                self.log(f"  {seq} 没账号密码,跳过")
                return
            try:
                if mode in ("采集", "精准采集"):
                    # ★★ 2026-09-24: 按号盖地区/年龄 ★★
                    #   用户要求「三个账号采集三个不同的地区…如果没有选择,
                    #   就默认下拉框的地区」。所以只在【这一行填了】的时候才覆盖,
                    #   留空一行都不动 cfg —— 默认口径原封不动。
                    _c = cfg
                    _rs = (rowset or {}).get(seq)
                    if _rs:
                        _c = dict(cfg)
                        if _rs[0]:
                            _c["collect_regions"] = [_rs[0]]
                            # ★★ 必须同时锁死 ★★
                            #   光设地区没用: 引擎里"每个号必扫纽约"会把 New York
                            #   插到第一位, collect_auto_regions 再撒全美 50 州 ——
                            #   采集从纽约开始填, 目标人数一满就轮不到指定的地区。
                            #   用户实测报过:"选了自己的地区, 还是按默认地区采"。
                            _c["collect_only_regions"] = True
                            _c["collect_auto_regions"] = False
                        if _rs[1]:
                            _c["collect_age_groups"] = list(
                                _value_of(AGE_CHOICES, _rs[1]))
                        self.log(f"  {seq} 按号口径: 地区={_rs[0] or '默认'} "
                                 f"年龄={_rs[1] or '默认'}")
                    # ★ collect_one 以前成功失败都返回 None/True/False, 界面
                    #   只判真假; 现在它返回带状态的 dict, 顺手把表格填上。
                    _r = call_engine(SA.collect_one, seq, _c, _task)
                    _autofill(seq, _r)
                    _ok = _r.get("ok") if isinstance(_r, dict) else bool(_r)
                    _err = (_r.get("error") or "") if isinstance(_r, dict) else ""
                    if _ok:
                        self.log(f"  {seq} 采集完成")
                    else:
                        self.log(f"  ★ {seq} 采集未执行 —— "
                                 f"{_err or '原因见上方日志'}")
                else:
                    res = call_engine(SA.run_one_seq, seq, email, pwd, cfg, _task)
                    self.log(f"  {seq} 完成: {res}")
                    # ★ 自动把这次跑出来的状态填回表格（和「2.扫描状态」一样），
                    #   省得再手动点「⟳ 刷新结果」。整批跑完会统一落盘。
                    _autofill(seq, res)
            except SA.UserStopped:
                self.log(f"  {seq} 已停止(浏览器已关)")
            except Exception as e:
                self.log(f"  {seq} 失败: {str(e)[:100]}")

        # ★ 不能用 with ThreadPoolExecutor: with 退出时会 join 所有线程, 只要有一个
        #   号卡在浏览器里(实跑证实过), 界面就永远停在"运行中", 停止按钮也没用。
        #   这里改成有界等待 + 不 join: 60 秒到点照样往下走, 先把界面放回空闲,
        #   没跑完的号在后台自己收尾。
        ex = cf.ThreadPoolExecutor(max_workers=jobs)
        _futs = [ex.submit(_one, s) for s in ids]
        try:
            cf.wait(_futs, timeout=60)          # ★ 有界等待: 超时也要把界面放回空闲
        finally:
            ex.shutdown(wait=False)
        if not all(f.done() for f in _futs):
            # ★★ 2026-09-20 修: 这句原来只说"还在后台收尾", 紧接着引擎却打
            #   「本次任务 0 条 ... 0 个号」—— 因为 finalize 只统计【已经跑完
            #   并登记过的号】, 还没启动完的号一个都没算进去。
            #   用户看到"0 条 / 0 个号"就以为白跑了, 其实后台还在正常采。
            #   这里把话说明白: 下面那行汇总是不完整的, 链接不会丢。
            self.log("提示: 60 秒内没启动完的号还在后台继续跑, 界面已先复位")
            self.log("★ 注意: 下面那行「本次任务 N 条 / M 个号」只统计【已经跑完的号】,"
                     " 数字偏小是正常的 —— 后台的号仍在采, 链接照样写进同一个文件, 不会丢。")
        _finish_note = (not all(f.done() for f in _futs))
        self._save_results()
        self.ui(self._idle)
        # ★ 任务成品文件: 把本次所有号级明细汇总成一份带时间戳的 txt
        try:
            _fin = SA.finalize_task(_task)
            if _fin:
                # ★★ 2026-09-20 修: 原来只打【文件名】(链接-20260920.txt)。
                #   成果文件在平铺包里就躺在包根, 和 20 多个 .py/.bat 混在一起,
                #   同事翻不到, 报的是"生成了文档却不在文件夹里面"。
                #   打全路径, 一眼能看到在哪、能直接复制去打开。
                self.log(f"★ 链接已存到: {_fin}")
                if _finish_note:
                    self.log("(后台还有号在跑, 它们新采到的链接会【继续写进同一个文件】)")
        except Exception as e:
            self.log(f"任务汇总失败: {str(e)[:80]}")
        self.log(f"{mode}结束")

    def _idle(self):
        self.running = False
        try:
            self.btn_start.config(state="normal")
            self.btn_collect.config(state="normal")
            try:
                self.btn_precise.config(state="normal")
            except Exception:
                pass
            self.btn_stop.config(state="disabled")
            self.btn_load.config(state="normal")
            self.lbl_run.config(text="空闲")
        except Exception:
            pass


class _GuiLogHandler(logging.Handler):
    """把底层模块的日志转发到界面"""
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


if __name__ == "__main__":
    # 找引擎脚本: 同级 -> 主脚本/ -> 上级目录 都能找到
    _mod = None
    for _c in (ROOT / "strava_ads.py", ROOT / "主脚本" / "strava_ads.py",
               ROOT.parent / "主脚本" / "strava_ads.py", ROOT.parent / "strava_ads.py"):
        if _c.exists():
            _mod = _c
            break
    if _mod is None:
        _hit = sorted(ROOT.parent.rglob("strava_ads.py"))
        _hit = [h for h in _hit if "__pycache__" not in str(h)]
        _mod = _hit[0] if _hit else None
    if _mod is None:
        print("=" * 64)
        print("[错误] 找不到 strava_ads.py —— 请确认它和本文件放在一起, 或在 主脚本/ 目录下")
        print("=" * 64)
        sys.exit(1)
    sys.path.insert(0, str(_mod.parent))          # 保留原有 import 语义
    os.chdir(str(_mod.parent))                    # 相对路径(头像/轨迹目录)按引擎目录解析
    _spec = importlib.util.spec_from_file_location("strava_ads", _mod)
    SA = importlib.util.module_from_spec(_spec)
    sys.modules["strava_ads"] = SA
    _spec.loader.exec_module(SA)
    print(f"[启动] 引擎: {_mod}")
    print(f"[启动] 配置: {getattr(SA, 'ROOT', '?')}")
    print(f"[启动] 版本: {app_ver() or '★ 拿不到(检查 app_version.py 在不在)'}")
    app = App()
    _h = _GuiLogHandler(app.logq)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    _lg = logging.getLogger("strava")
    _lg.addHandler(_h)
    _lg.setLevel(logging.INFO)
    app.mainloop()
