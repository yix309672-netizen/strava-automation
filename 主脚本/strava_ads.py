#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strava x 比特浏览器 自动化 (Playwright 版)
技术栈: Python + Playwright(CDP连接比特窗口) + 随机等待 + Stealth + 分步异常截图 + config分离

用法:
  python strava_pw.py --window _10                 # 跑单个窗口
  python strava_pw.py --batch                      # 按config里windows列表批量
  python strava_pw.py --window _10 --check-only    # 只看登录状态
  python strava_pw.py --window _10 --recheck       # 强制重做

配置文件: config.json
日志: logs/run_YYYYmmdd.log   截图: logs/shot_*.png
"""
import argparse, csv, io, json, os, logging, random, re, socket, sys, threading, time, traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

# 领取服务客户端(可选): 多台机器共享"谁已经被处理过", 避免重复采集
# 没配置 claim_server 时完全不启用, 原有单机行为不变
# ★ 引擎可能被放在 主脚本/ 下, 而 claim_client.py 在项目根目录 ——
#   界面加载引擎时只把【引擎所在目录】插进 sys.path, 于是这里 import 不到,
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent, _HERE.parent / "配置"):
    try:
        if _p.is_dir() and str(_p) not in _sys.path:
            _sys.path.insert(0, str(_p))
    except Exception:
        pass
try:
    from claim_client import ClaimClient, ServerDown, resolve_worker_id
except Exception as _imp_err:
    ClaimClient = None
    # ★ 用 print: 这一行在 logging 配置之前执行
    print(f"[claim] ★★ 导入 claim_client 失败: {_imp_err}", flush=True)
    print("[claim] ★★ 将退回【本地去重】—— 多台机器同时跑会重复采集!", flush=True)

    class ServerDown(Exception):
        """服务端不可用"""

    def resolve_worker_id(explicit=""):
        return explicit or "local"


class BrowserGone(RuntimeError):
    """浏览器/页面已经没了

    ★ 真机教训(2026-09-19 01:17 实跑): 浏览器被关掉后, check_athlete 会把每一个人
      都读成"读不到数据", 引擎就带着一个死页面把剩下的几百个候选人一个个刷完, 再
      白跑下一个路段/地区(日志一路 "Target page ... has been closed")。
      这类故障必须像 ServerDown 一样整体中止。
    """

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 零配置默认值
# 同事下载即用: 服务器地址和密钥内置, 不需要改 config.json
DEFAULT_CLAIM_SERVER = "http://137.175.71.171:8000"
DEFAULT_CLAIM_KEY = "g1jVQg7y_K5UOtfHUgUEg6seJ4WeKJjAUGJt7shPYvk"


def auto_worker_id(engine="ads"):
    """自动生成机器号: 环境变量 > config > 主机名 + 版本后缀

    为什么带版本后缀:
        同一台机器可能同时跑 ADS 版和比特版, 若机器号相同,
        两者的 claim_cache_<机器号>.json 会互相覆盖。
        加 _ads/_bit 后缀后互不干扰。

    注意: 这里【只影响去重服务和本地缓存】, 不影响 task_state 的键 ——
          那套用的是窗口名, 改动会让已有进度失效, 所以不动。
    """
    sfx = "_" + re.sub(r"[^A-Za-z0-9]", "", str(engine or ""))[:6]
    env = (os.environ.get("STRAVA_WORKER") or "").strip()
    if env:
        return env + sfx          # 手动指定也带后缀, 两个版本仍不冲突
    try:
        cfgv = str(CFG.get("worker") or "").strip()
        if cfgv:
            return cfgv + sfx
    except Exception:
        pass
    try:
        h = socket.gethostname().strip()
        if h:
            return (re.sub(r"[^A-Za-z0-9_-]", "", h)[:16] or "PC") + sfx
    except Exception:
        pass
    return "PC" + sfx


def _find_cfg():
    """config.json 在哪: 平铺=本目录; 分层备份包=../配置/"""
    cands = [ROOT / "config.json", ROOT / "配置" / "config.json",
             ROOT.parent / "配置" / "config.json", ROOT.parent / "config.json"]
    for c in cands:
        if c.exists():
            return c
    return None


def _find_data_dir():
    """数据目录 —— 用"config.json 在哪"这个决定性信号判断布局:

      平铺目录(原始桌面版): config.json 就在脚本同级
          -> 数据文件也写同级, 与原版行为完全一致
      分层备份包:           config.json 在 配置/, 脚本在 主脚本/ 或根目录
          -> 数据文件写 数据/ (本目录或上一级)

    这样即使脚本被单独拷进一个"恰好也有 数据/ 目录"的文件夹, 也不会误写进去。"""
    if (ROOT / "config.json").exists():
        return ROOT                                   # 平铺: 同级
    for cand in (ROOT / "数据", ROOT.parent / "数据"):
        if cand.is_dir():
            return cand                               # 备份包: 数据/
    return ROOT


DATA_DIR = _find_data_dir()


def _data_path(name):
    """数据文件路径: 优先复用 数据/ 里已有的, 其次本目录已有的, 否则新建在 DATA_DIR"""
    for c in (DATA_DIR / name, ROOT / name):
        if c.exists():
            return c
    return DATA_DIR / name


_CFG_P = _find_cfg()
if _CFG_P is None:
    CFG = {}
    print("[!] 找不到 config.json (找过: 本目录 / 配置/) —— 将以默认参数运行", file=sys.stderr)
else:
    CFG = json.loads(_CFG_P.read_text(encoding="utf-8"))
LOGDIR = ROOT / "logs"
LOGDIR.mkdir(exist_ok=True)
STATE_FILE = _data_path("task_state.json")
COLLECT_OUT = _data_path("collected_users.txt")
COLLECT_SEEN = _data_path("collected_seen.json")
API = CFG.get("bitbrowser_api", "http://127.0.0.1:54345")

# ★ Strava 用户名里常带 emoji(🚴🏽‍♀️ 之类)。控制台是 GBK 时编码不了,
#   logging 会报 UnicodeEncodeError, 那一行日志直接丢掉。
#   这里保留控制台原编码(不乱码中文), 只把不可编码字符换成 ?,
#   这样整行照样打出来, 不再报错。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOGDIR / f"run_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("strava")


def _disable_quick_edit():
    """关掉 Windows 控制台的【快速编辑】模式。

    ★★ 2026-09-20 用户报"ads 脚本停止不动了", 根因就是这个 ★★
      Windows 控制台默认开着快速编辑: 只要有人在窗口里点一下(开始选文字),
      控制台就【挂起所有输出】。而这里的 logging 是
          先 FileHandler(写文件) -> 再 StreamHandler(写控制台)
      所以现象非常像"卡死":
          日志文件还在不停增长, 但那个黑窗口停在原地一动不动。
      更严重的是: 那次写控制台的调用【永远不返回】, 主线程跟着停住 ->
      心跳不跳了 -> 15 分钟后 _stall_watchdog 判定"卡在没有超时的调用里",
      os._exit(9) 把整个进程杀掉。
      用户 10:49:34 看到的那条 watchdog 报错, 就是这么来的 ——
      不是 CDP 卡住, 是窗口被点了。

    ★ 关掉快速编辑之后, 在窗口里点击/拖选都不会再阻断程序。
      (同事那边日常启动器已经把窗口藏了, 本来就点不到; 这条是给
       管理员自己直接跑界面时兜底的。)
    """
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)                  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return                               # 没控制台(被隐藏/重定向) -> 不用管
        ENABLE_QUICK_EDIT = 0x0040
        # ★ 必须同时置上 EXTENDED_FLAGS, 否则清快速编辑这一位是不生效的
        ENABLE_EXTENDED_FLAGS = 0x0080
        new = (mode.value & ~ENABLE_QUICK_EDIT) | ENABLE_EXTENDED_FLAGS
        if new != mode.value:
            k.SetConsoleMode(h, new)
    except Exception:
        pass


_disable_quick_edit()

# ------------------------------------------------------- 管理员采集口径
# ★★ 2026-09-19【为什么引擎里也要有这一份】★★
#   根因有两个, 引擎这份是最后一道保险:
#     1) 老 update.py 的合并策略是"只补缺失的键、绝不覆盖已有值",
#        所以老包里写死的旧值(12 州 / 每段 200 人)永远改不掉。
#     2) 老机器上 update.py 自己也换不掉自己。
#
# ★★ 2026-09-20【删掉了 _ADMIN_POLICY 这个字典】★★
#   它原本长这样:  _ADMIN_POLICY = {"min_athletes": 5000, ...}
#   后来修掉了"无条件覆盖"的 bug(enforce_admin_policy 改成只纠正
#   【确定属于老包遗留】的值), 于是这个字典【再没有任何代码读它】。
#   但它在最显眼的位置写着 min_athletes: 5000 —— 谁看到都会以为
#   5000 是公司口径, 这正是当初吃掉用户设置的那个值。留着就是给
#   下一个人预备的坑, 所以整个删掉。
#   ★ 现在唯一的口径开关是下面的 _ADMIN_POLICY_REV。
_ADMIN_POLICY_REV = 2

# ★ 2026-09-24: 给人看的版本号 —— 唯一真源在 app_version.py。
#   以前只有服务器算的内容哈希, 同事报问题说不上来自己跑的是哪一版。
#   ★ 丢了也不能让整个程序起不来, 所以兜底成 "v?"。
try:
    from app_version import VERSION as APP_VERSION, label as ver_label
except Exception:                       # noqa: BLE001
    APP_VERSION, ver_label = "v?", (lambda: "v?")


def enforce_admin_policy():
    """版本号落后就纠正【老包遗留值】, 并原子写回 config.json。

    ★ 只在 _policy_rev < _ADMIN_POLICY_REV 时动作一次;
      之后同事自己在界面上改的值照常保留, 不会被反复覆盖。
    ★ 只纠正这两类确定是老包的东西:
        · collect_regions 恰好是那串老 12 州 -> 改成 ["New York"]
        · min_athletes 低于硬地板(200)      -> 改成 200
      ★ 正在用的口径(比如 2000)一律不碰 —— 以前无条件写 5000,
        把用户在界面上改的值吃掉了, 那是 bug 不是特性。
    ★ 浏览器 key / 头像目录 / 轨迹目录 / 账号文件一律不碰。
    """
    global CFG
    if _CFG_P is None or not isinstance(CFG, dict):
        return
    try:
        rev = int(CFG.get("_policy_rev") or 0)
    except Exception:
        rev = 0
    if rev >= _ADMIN_POLICY_REV:
        return
    # ★★ 2026-09-20 修: 以前这里【无条件】把 CFG 改成 _ADMIN_POLICY 里
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
        # ★★ 2026-09-22: 地板从 200 降到 100 ★★
        #   下拉框新增了 100~900, 原来卡 `<200` 会把选中的 100
        #   改成 200 并写回磁盘 —— 界面上"选了没用"就是这个原因。
        if 0 < _v < 100:
            fixed[_k] = 200
    CFG = dict(CFG)
    CFG.update(fixed)
    CFG["_policy_rev"] = _ADMIN_POLICY_REV
    try:
        # ★ 原子写: 写一半被打断会留下截断的 JSON, 下次启动直接起不来
        _tmp = _CFG_P.with_name(_CFG_P.name + ".tmp")
        _tmp.write_text(json.dumps(CFG, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        os.replace(_tmp, _CFG_P)
        log.info("★ 已按管理员口径纠正 %s: %s", _CFG_P.name,
                 ", ".join(fixed) if fixed else "(版本号已对齐)")
        log.info("   现在: 采集州=%s 每段>=%s人 目标=%s 并发=%s",
                 CFG.get("collect_regions"), CFG.get("min_athletes"),
                 CFG.get("collect_target_per_account"), CFG.get("jobs"))
    except Exception as _e:
        log.warning("★ 纠正配置失败(仅本次生效, 不改磁盘): %s", str(_e)[:80])


enforce_admin_policy()

# ---------------------------------------------------------------- utils
def human_delay(a=None, b=None):
    h = CFG.get("human", {})
    lo = a if a is not None else h.get("delay_min", 0.4)
    hi = b if b is not None else h.get("delay_max", 1.4)
    time.sleep(random.uniform(lo, hi))

def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

# ★ 界面上最多 8 个线程并发 mark_step: load -> 改 -> save 会互相覆盖,
#   而且以前是直接 write_text, 写到一半崩掉会把整份 JSON 弄坏 ->
#   load_state() 返回 {} -> 所有进度清零、全部账号重跑一遍。
_STATE_LOCK = threading.Lock()


def _state_write(st):
    """原子落盘: 先写 .tmp 再 os.replace"""
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def save_state(st):
    with _STATE_LOCK:
        try:
            _state_write(st)
        except Exception as e:
            log.warning(f"state保存失败: {e}")

def mark_step(win, step, value=True):
    with _STATE_LOCK:
        st = load_state()
        st.setdefault(str(win), {})[step] = value
        try:
            _state_write(st)
        except Exception as e:
            log.warning(f"state保存失败: {e}")

def task_state_key(win):
    """算这个账号在 task_state.json 里的键(单点定义)

    ★ 为什么要有它: 这个键原来只在 run_one 里现算一遍, collect_one
      (「◎ 只采集」)那边没有, 于是扫描任务既读不到进度也不知道城市。
      现在两边都调它, 不会再各算各的。
    ★ 前缀取环境变量 STRAVA_WORKER(20 台机器各设一个, 如 PC01..PC20),
      各跑各的进度不互相覆盖; ADS 引擎再加 ads_ 前缀, 避免和比特派
      同名窗口的进度串味。
    """
    _mw = (os.environ.get("STRAVA_WORKER") or "").strip()
    _mp = (_mw + "_") if _mw else ""
    return f"{_mp}ads_{str(win).lstrip('_')}"


def _today_upload_remain(tag, daily_cap=None):
    """今天还能传多少个轨迹 = 每日上限 - 今天已传。拿不到就返回 None(不限制)。

    ★★ 2026-09-24 用户问"我设的上限38, 为什么显示轨迹60个" ★★
      upload_gpx 提交前有一句 `todo = todo[:remain]`, 那个 remain 就是这里算的。
      抽成一个函数, 让"显示的数量"和"真传的数量"用同一套算法 ——
      以前 pending_todo 只数文件总数, 于是显示 60 而实际传 38。
    """
    try:
        cap = int(daily_cap) if daily_cap else int(CFG.get("daily_cap") or 38)
    except Exception:
        cap = 38
    if cap <= 0:
        return None
    try:
        counter = _data_path(f"upload_counter_{str(tag).lstrip('_')}.txt")
        today = datetime.now().strftime("%Y-%m-%d")
        used = 0
        if counter.exists():
            d, n = counter.read_text().strip().split(",")
            if d == today:
                used = int(n)
        return max(0, cap - used)
    except Exception:
        return None


def pending_todo(win, name=None, location=None, avatar=None, gpx_files=None,
                 daily_cap=None):
    st = load_state().get(str(win), {})
    todo = []
    if name and st.get("name") != name:
        todo.append("资料")
    if location and st.get("location") != location:
        todo.append("位置")
    if avatar and st.get("avatar") != str(avatar):
        todo.append("头像")
    if st.get("privacy") is not True:
        todo.append("隐私")
    if st.get("units") != "feet":
        todo.append("单位")
    if gpx_files:
        done = set(st.get("uploaded", []))
        rest = [p for p in gpx_files if str(p) not in done]
        if rest:
            # ★★ 显示"今天会传几个", 不是"目录里还剩几个" ★★
            #   用户设的每日上限 38, 这里原来写 60(目录总数), 对不上 ——
            #   因为真正能传几个由 upload_gpx 按每日上限截断。
            _n = len(rest)
            _cap = _today_upload_remain(win, daily_cap)
            if _cap is None or _cap >= _n:
                todo.append(f"轨迹{_n}个")
            else:
                todo.append(f"轨迹{_cap}个(还差{_n - _cap}个, 受每日上限限制)")
    # ★★ 2026-09-22 用户要求: 「▶ 开始任务」不做采集, 采集只归「◎ 只采集」★★
    #   所以不再往待办里塞"采集" —— 否则一个"别的事都干完了、只差采集"的号,
    #   会被判成"还有活"而白开一次浏览器(开了也不会采了)。
    return todo

def parse_remark(remark):
    """从窗口备注里取 邮箱/密码 (兼容 账号：xxx 密码：yyy)"""
    r = remark or ""
    m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", r)
    em = m.group(0) if m else None
    pw = None
    m2 = re.search(r"密码\s*[:：]\s*(\S+)", r)
    if m2:
        pw = m2.group(1)
    else:
        # 没有"密码："前缀时,取邮箱后面第一个非邮箱token
        rest = r
        if em:
            rest = rest.replace(em, " ")
        toks = [t for t in re.split(r"[\s:：\-]+", rest) if t and "@" not in t and t not in ("账号", "密码")]
        if toks:
            pw = toks[0]
    return em, pw

def parse_accounts_txt(path):
    accts = []
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        emails = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", line)
        if not emails:
            continue
        email = emails[0]
        pwd = None
        m = re.search(r"密码\s*[:：]\s*(\S+)", line)
        if m:
            pwd = m.group(1)
        else:
            rest = line
            for e in emails:
                rest = rest.replace(e, " ")
            toks = [t for t in re.split(r"[\s:：\-]+", rest) if t and "@" not in t and t not in ("账号", "密码")]
            if toks:
                pwd = toks[0]
        if pwd:
            accts.append({"email": email, "password": pwd})
    return accts

def sort_gpx(folder):
    files = []
    for ext in ("*.gpx", "*.fit", "*.tcx"):
        files += list(Path(folder).glob(ext))
    def key(p):
        m = re.search(r"(\d+)\.(\d+)", p.name)
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)
    return sorted(files, key=key)

def pick_avatar(win_seq, avatar_dir, all_windows):
    """按窗口序号分配不重复头像"""
    files = sorted([p for p in Path(avatar_dir).glob("*.jpg") if not p.name.startswith("signal-")])
    if not files:
        return None
    idx = (int(str(win_seq).lstrip("_")) - 1) % len(files)
    return str(files[idx])



# ---------------------------------------------------------------- AdsPower
# ★ AdsPower 的本地 API Key 是【每台机器各不相同】的, 在 AdsPower 客户端里
#   生成(设置 → 本地API)。所以绝对不能写死 —— 一写死, 同事用 ADS 版必然报
#   "API Key mismatch. Please replace it", 然后加载出 0 个环境。
ADS_KEY = str(CFG.get("adspower_key") or "").strip()
ADS_BASE = str(CFG.get("adspower_api") or "http://127.0.0.1:50325").strip()
ADS_H = {"Authorization": f"Bearer {ADS_KEY}"}


_ADS_LOCK = threading.Lock()
_ADS_LAST = [0.0]
_ADS_CACHE = {"t": 0.0, "list": []}

# ---- 停止控制(用户点停止 -> 立即中断) ----
STOP_EVENT = threading.Event()


class UserStopped(Exception):
    """用户点了停止"""
    pass


def check_stop():
    """长流程里的检查点:一旦用户停止就抛异常,立刻中断

    ★ 同时给停顿看门狗打心跳: 这个函数被撒在 18 个循环检查点上, 所以
      "心跳还在" == "主线程还在推进"。详见下面的 _stall_watchdog。
    """
    _STALL["beat"] = time.time()
    if not _STALL["armed"]:
        _arm_watchdog()
    if STOP_EVENT.is_set():
        raise UserStopped("用户停止")


# ---------------- ★ 停顿看门狗: 对付"根本没有超时的调用" ----------------
# 为什么必须有它: CDP 的 session.send() 【没有 timeout 参数】(Playwright 没给),
#   页面渲染卡住时它会永久阻塞 —— 这不是本项目能改的。
#   真机铁证: run_20260918.log 共 19100 行, 第 19100 行(就是文件最后一行)停在
STALL_EXIT_SEC = float(CFG.get("stall_exit_sec") or 900)
_STALL = {"beat": time.time(), "armed": False}


def _stall_watchdog():
    """守护线程: 心跳停了就落日志退出。daemon=True, 不阻塞进程退出。"""
    while True:
        time.sleep(5)
        if STALL_EXIT_SEC <= 0:
            continue
        try:
            gap = time.time() - _STALL["beat"]
        except Exception:
            continue
        if gap > STALL_EXIT_SEC:
            try:
                log.error(f"[watchdog] ★ 主线程已 {gap/60:.1f} 分钟没有任何进展 —— "
                          f"卡在一个没有超时的浏览器/CDP 调用里。强制退出进程, "
                          f"避免永久卡死(已采到的链接是逐条落盘的, 不会丢)。")
                for _h in list(logging.getLogger().handlers):
                    try:
                        _h.flush()
                    except Exception:
                        pass
                logging.shutdown()
            except Exception:
                pass
            os._exit(9)


def _arm_watchdog():
    """第一次 check_stop() 时武装一次(幂等)。"""
    if _STALL["armed"] or STALL_EXIT_SEC <= 0:
        return
    _STALL["armed"] = True
    try:
        threading.Thread(target=_stall_watchdog, name="stall-watchdog",
                         daemon=True).start()
        log.info(f"[watchdog] 已武装: 连续 {STALL_EXIT_SEC/60:.0f} 分钟无进展就强制退出"
                 f"(配置键 stall_exit_sec, 设 0 可关闭)")
    except Exception:
        pass


def sleep_or_stop(sec):
    """可中断等待:用户停止时立刻中断(每0.3秒查一次)

    ★ 同时给看门狗打心跳: 能走到这里就说明主线程在正常推进,
      只是在"故意等"(限速/等页面)。以前这里不打心跳, 于是长时间的
      分段等待会被看门狗误判成"卡死"。
      ★ 这不会削弱看门狗: 真正卡在 CDP 调用里时, 线程根本执行不到
        这一行, 心跳照样会停 -> 该杀还是杀。
    """
    end = time.time() + float(sec)
    while True:
        _STALL["beat"] = time.time()      # ★ 有意等待 = 有进展
        if STOP_EVENT.is_set():
            raise UserStopped("用户停止")
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(0.3, left))





# ---------------------------------------------------------------- 网速自适应等待
# 为什么需要: 固定秒数只能照顾一种网速。网快时白等, 网慢时等不够->读不到->重试更慢。
# 做法: 用真实导航/fetch 的耗时估一个"当前网速倍数", 再乘到所有等待上限上。
# 纯算术, 不额外联网探测; 样本全部来自真实页面跳转。
NET_BASE_MS = float(CFG.get("net_baseline_ms") or 1800)   # 基准: 一次文档级跳转的典型耗时
NET_MIN_SAMPLES = 5
_NET = {"ping": 0.0, "api": 0.0, "n": 0, "last": 0.0}

# 两种口径分开算,不能混: 浏览器API在127.0.0.1(几毫秒),混进去会把倍数压到地板上
_NET_BOUNDS = {
    "internet": (0.6, 1.6),   # 页面/接口: 网快最多省40%, 网慢最多放宽1.6倍
    "api": (0.7, 1.8),        # 本地浏览器接口
}


def net_ready():
    """开始计时,返回起始时刻(放在动作之前)"""
    return time.perf_counter()


def net_elapsed(t0, mode="internet"):
    """动作结束调用: 记录本次耗时并更新网速估计,返回本次毫秒数"""
    try:
        ms = (time.perf_counter() - t0) * 1000.0
    except Exception:
        return 0.0
    try:
        _NET["n"] += 1
        _NET["last"] = ms
        if mode == "api":
            # 本地接口: 只剔除明显异常值(限速等待会计入,>5秒才算异常)
            if 0 < ms < 5000:
                _NET["api"] = ms if _NET["api"] <= 0 else _NET["api"] * 0.7 + ms * 0.3
        else:
            # 外网: <120ms 基本是本地缓存/重定向,不具代表性
            if 120 < ms < 60000:
                _NET["ping"] = ms if _NET["ping"] <= 0 else _NET["ping"] * 0.7 + ms * 0.3
    except Exception:
        pass
    return ms


def _net_scale(mode):
    # ★ 2.12: 并发时网速样本被互相污染, 会把 timeout 放大到 48000ms
    #   (实测省 10.5 分钟/号); 单号跑时不受影响。
    if CONCURRENCY_HINT > 1:
        return 1.0
    if _NET["n"] < NET_MIN_SAMPLES:
        return 1.0                      # 样本不够: 完全保持原来的等待时长
    try:
        raw = _NET["api"] if mode == "api" else _NET["ping"]
        if raw <= 0:
            return 1.0
        lo, hi = _NET_BOUNDS.get(mode, _NET_BOUNDS["internet"])
        s = (raw / NET_BASE_MS) ** 0.5   # 开方: 避免抖动把等待放大过头
        return min(hi, max(lo, s))
    except Exception:
        return 1.0


def net_wait(sec):
    """等待上限(元素就绪类): 网快缩短, 网慢放宽"""
    try:
        return float(sec) * _net_scale("internet")
    except Exception:
        return float(sec)


def net_timeout(sec, mode="internet"):
    """超时(浏览器/接口调用类)"""
    try:
        return float(sec) * _net_scale(mode)
    except Exception:
        return float(sec)


def net_info():
    """日志用: 当前网速估计"""
    return (f"样本{_NET['n']} 页面{_NET['ping']:.0f}ms 接口{_NET['api']:.0f}ms "
            f"倍数 页面x{_net_scale('internet'):.2f} 接口x{_net_scale('api'):.2f}")
def ads_headers():
    """AdsPower 请求头。★ key 为空时【重新读一次 config.json】。

    ★★ 2026-09-20 真机实测(同事报"一直显示 API 不正确") ★★
      证据: 用【空 key】走请求头, AdsPower 返回的正是
              {"code":-1,"msg":"Require api-key"}
            —— 和同事日志里的那句一字不差。
            而日志同时打印 "当前用的是: ..." —— 空字符串做 [:8]...[-4:] 就是 "..."。
      所以那句 "Require api-key" 的真正含义是【key 是空的】, 不是"key 填错了"。

      根因: ADS_KEY 是【模块导入时】读的一次性快照。同事改完 config.json
            没重启程序 -> 引擎用的还是那个空 key -> 一直报错。
            (和之前 claim_client 导入失败被永久缓存是同一类问题。)

      修法: 每次发请求前检查 —— 只要当前 key 还是空的, 就重新读一次配置文件。
            改完保存即可生效, 不用重启。
    """
    global ADS_KEY, ADS_H
    if not ADS_KEY and _CFG_P is not None:
        try:
            _d = json.loads(_CFG_P.read_text(encoding="utf-8"))
            _k = str(_d.get("adspower_key") or "").strip()
            if _k:
                ADS_KEY = _k
                ADS_H = {"Authorization": f"Bearer {_k}"}
                log.info(f"[ads] 从 {_CFG_P.name} 重新读到 adspower_key"
                         f"(长度 {len(_k)}) —— 不用重启程序")
        except Exception:
            pass
    return ADS_H


def ads_req(path, **params):
    """AdsPower 接口限速(官方限制约 1 次/秒)

    ★ 3.5: _allow_stop —— 关窗路径必须传 False。
      现状: 点停止 -> 这里的限速等待抛 UserStopped -> 关窗路径一个窗口都没关
      (日志 "close err: 用户停止" ×4 却报"已关闭 4 个")。
      为 True 时保持可中断; 为 False 时用普通 time.sleep(关窗不可打断)。

    ★ 2026-09-20: 同时带上 URL 参数 ?api_key=。
      实测本机 AdsPower【只认请求头】, 带参数反而多余; 但老版本客户端只认
      参数、不认请求头。两种一起发, 两边都覆盖(实测"两种一起发"正常工作)。
    """
    _allow_stop = bool(params.pop("_allow_stop", True))
    import requests as _rq
    with _ADS_LOCK:
        gap = time.time() - _ADS_LAST[0]
        if gap < 1.2:
            if _allow_stop:
                sleep_or_stop(1.2 - gap)   # 可中断等待: 停止时不再干等
            else:
                time.sleep(1.2 - gap)      # ★ 关窗路径: 不可中断, 必须关干净
        _ADS_LAST[0] = time.time()
    _t_api = net_ready()
    _h = ads_headers()
    _p = dict(params)
    if ADS_KEY:
        _p.setdefault("api_key", ADS_KEY)   # 兼容只认 URL 参数的老版本
    r = _rq.get(f"{ADS_BASE}{path}", params=_p, headers=_h, timeout=60)
    net_elapsed(_t_api, "api")
    return r.json()


def wait_text(page, js_expr, timeout=2.0, key=None, on_poll=None):
    """有界轮询: 条件一满足就返回,最多等 timeout 秒(替代固定 time.sleep)。
    数字/字符串返回取到的值;布尔返回 True/False;超时返回 0/False。
    页面更慢时与替换前等价(仍是等 timeout),页面更快时立刻通过。
    on_poll: 每轮可选回调(传 check_stop 即可保持"随时可停止")。"""
    end = time.time() + net_wait(timeout)   # 上限随实测网速伸缩
    last = 0
    while True:
        if on_poll is not None:
            on_poll()
        try:
            v = page.evaluate("() => (" + js_expr + ")")
        except Exception:
            v = 0
        if isinstance(v, bool):
            if v:
                return True
            last = False
        elif isinstance(v, (int, float)):
            last = v
            if v > 0:
                return v
        else:
            if v:
                return v
        if time.time() >= end:
            return last
        time.sleep(0.2)


# ---- 冗余导航去重: 同一账号内短时间内重复 goto 同一个 URL 直接跳过 ----
# ★ 2026-09-19 并发改造: 改成【线程局部】。
#   原来是一个模块级单例 dict, 3 个号并发时共用同一份记账 —— 一个号的
#   reset_goto_guard() 会清掉另一个号刚写进去的记录, 而且"我刚导航过"这个
_GOTO_TLS = threading.local()
GOTO_SAME_WINDOW = 10.0


def _goto_guard():
    g = getattr(_GOTO_TLS, "g", None)
    if g is None:
        g = {"url": "", "t": 0.0, "win": None}
        _GOTO_TLS.g = g
    return g


def reset_goto_guard(win=None):
    """每个账号开始时调用,清空【本线程】的去重记忆"""
    try:
        g = _goto_guard()
        g["url"] = ""
        g["t"] = 0.0
        g["win"] = win
    except Exception:
        pass


# ---------------- 只留脚本工作页, 多余标签自动关掉 ----------------
# ★★ 2026-09-20 用户要求:「一个浏览器只保留两个脚本工作页面, 其他的全部
#   自动关闭。不然内存扛不住。」★★
#   脚本本身只用一个页面(排行榜是页面内 fetch, 不开新标签), 但浏览器里会
#   慢慢堆起别的标签: 上一次留下的、浏览器自带的"新建标签页"、手点出来的。
#   每个标签都是一份完整渲染进程, 十几个就能把内存吃光。
#   —— 所以每次进新地区(以及开号时)都清一次, 只留脚本正在用的那个。
#
# ★ 判断"哪个是工作页"用的是【对象身份】(is), 这里确认过可靠性:
#     playwright 的 ChannelOwner 按 GUID 缓存对象
#     (_connection.py: self._objects[guid] = self; parent = self._objects[guid]),
#     所以 ctx.pages 每次返回的是【同一个 Python 对象】, is / id() 都可信。
#     另外 playwright 没有自定义 __eq__, 也就是默认的身份比较 —— 一致。
_INTERNAL_URL_PREFIX = ("chrome://", "about:", "devtools://", "edge://",
                        "extension://", "chrome-extension://", "brave://")
# ★ 这几个【看着像内部页, 其实是普通标签页】, 而且要关的就是它们:
#   空白页最占内存又完全没用。第一版把它们也算进"内部页"保护起来了,
#   等于把最该清的那一类放过了。
_CLOSABLE_BLANK = ("", "about:blank", "chrome://newtab/",
                   "chrome://new-tab-page/")


def _is_browser_internal_page(url):
    """指纹浏览器自己的内部页 —— 关掉会影响它自身的界面, 一律不碰。

    ★ 注意区分: about:blank / 新建标签页【不算】内部页, 它们是要关的。
    """
    u = (url or "").strip().lower()
    if u in _CLOSABLE_BLANK:
        return False
    if u.startswith(_INTERNAL_URL_PREFIX):
        return True
    return "console.bitbrowser" in u


def close_extra_pages(page, tag=""):
    """关掉这个浏览器里【脚本用不到】的标签页, 只留正在用的那一个。

    返回关掉的数量。任何异常都吞掉 —— 清标签是"锦上添花", 绝不能因为它
    把正常采集搞挂。

    ★ 两条安全线:
      1) 浏览器内部页不碰(console.bitbrowser / chrome:// …)
      2) 【绝不把页面关到一个不剩】: 万一工作页已经不在 ctx.pages 里
         (页面已失效), 也要留下最后一个, 否则整个浏览器上下文就空了。
    """
    try:
        ctx = page.context
    except Exception:
        return 0
    try:
        pages = list(ctx.pages)
    except Exception:
        return 0

    victims = []
    for pg in pages:
        try:
            if pg is page:                    # ★ 工作页, 绝对不能关
                continue
            try:
                u = pg.url or ""
            except Exception:
                u = ""
            if _is_browser_internal_page(u):
                continue
            victims.append(pg)
        except Exception:
            continue
    # ★ 安全线 2: 一个都不留是不行的
    if len(victims) >= len(pages):
        victims = victims[:-1]

    closed = 0
    for pg in victims:
        try:
            pg.close()
            closed += 1
        except Exception:
            continue
    if closed:
        log.info(f"[page] 已自动关闭 {closed} 个多余标签页{tag}"
                 f"(只留脚本工作页, 省内存)")
    return closed


def goto_same(page, url):
    """已经在这个页面(且10秒内刚加载过)就不再重复加载。
    只省掉重复导航,页面内容不变。返回 True 表示可直接复用当前页面。"""
    try:
        cur = (page.url or "").split("#")[0].rstrip("/")
        want = (url or "").split("#")[0].rstrip("/")
        g = _goto_guard()
        if (cur == want and g["url"] == want
                and (time.time() - g["t"]) < GOTO_SAME_WINDOW):
            log.info(f"[goto] 同页跳过重复导航 {want.split('/')[-1] or want}")
            return True
    except Exception:
        pass
    return False


def note_goto(page, url):
    """goto 成功后记账,供 goto_same 去重"""
    try:
        g = _goto_guard()
        g["url"] = (url or "").split("#")[0].rstrip("/")
        g["t"] = time.time()
    except Exception:
        pass


# ---------------- ★ 风控闸门: 按"每分钟动作次数"限速(★ 按号分桶) ----------------
# 为什么需要: 第一批把所有"裸等待"换成了"有界就绪轮询", 单个看是纯赚, 但叠加后
#   "单位时间的交互次数"会翻倍 —— 现状 5.4 次资料页导航/分钟/号, 改后可能到 11.5。
#   真人手动浏览约 6~12 次/分钟。所以必须有一个显式的速率闸门把上限钉死,
RATE_NAV_SEC = float(CFG.get("rate_nav_sec") or 6.0)   # 资料页文档级导航
RATE_API_SEC = float(CFG.get("rate_api_sec") or 1.5)   # 榜单接口 fetch
RATE_ACT_SEC = float(CFG.get("rate_act_sec") or 0.6)   # 地图点击/拖拽
_RATE_LOCK = threading.Lock()
# 默认桶: 没有账号作用域时用它(单账号 CLI 路径 / 自测直接调 rate_gate)。
# 结构保持 {kind: {"min_gap", "last"}} 不变 —— 兼容既有断言与运维习惯。
_RATE = {
    "nav": {"min_gap": RATE_NAV_SEC, "last": 0.0},   # 资料页文档级导航: >=6.0s/次 => <=10 次/分钟
    "api": {"min_gap": RATE_API_SEC, "last": 0.0},   # 榜单接口 fetch:    >=1.5s/次
    "act": {"min_gap": RATE_ACT_SEC, "last": 0.0},   # 地图点击/拖拽:      >=0.6s/次
}
_RATE_BUCKETS = {}          # (账号作用域, kind) -> {"last": ...}  ← 每个号一份独立预算

_RATE_TLS = threading.local()


def set_rate_scope(scope):
    """按号开始采集时调用: 之后【本线程】的 rate_gate 都走这个号自己的桶。

    ★ 线程局部而不是全局: 3 个号各跑一个线程, 互不干扰。
    """
    try:
        _RATE_TLS.scope = str(scope or "")
    except Exception:
        pass


def _rate_scope():
    """本线程当前的账号作用域。空字符串 = 没有作用域 -> 退回默认桶。"""
    try:
        return getattr(_RATE_TLS, "scope", "") or ""
    except Exception:
        return ""


def rate_gate(kind, scope=None):
    """到点才放行; 超速就补等。用 sleep_or_stop -> 停止键随时可打断。

    ★ 按号分桶: scope(默认取本线程的账号作用域)不同 -> 各算各的预算。
      没有作用域时退回模块级默认桶, 行为与改造前完全一致。
    """
    sc = _rate_scope() if scope is None else str(scope or "")
    try:
        with _RATE_LOCK:
            gap_min = _RATE[kind]["min_gap"]
            if sc:
                b = _RATE_BUCKETS.get((sc, kind))
                if b is None:
                    b = {"last": 0.0}
                    _RATE_BUCKETS[(sc, kind)] = b
            else:
                b = _RATE[kind]                 # 默认桶: 单账号/自测路径
            wait = gap_min - (time.time() - b["last"])
            b["last"] = time.time() + max(0.0, wait)
    except KeyError:
        return                                  # 未知 kind: 放行(与改造前一致)
    if wait > 0:
        sleep_or_stop(wait)                     # UserStopped 直接上抛, 绝不吞


def ads_list(size=200, use_cache=True):
    """账号列表(带缓存,避免频繁请求被限流)"""
    if use_cache and _ADS_CACHE["list"] and (time.time() - _ADS_CACHE["t"] < 120):
        return _ADS_CACHE["list"]
    r = ads_req("/api/v1/user/list", page=1, page_size=size)
    lst = (r.get("data") or {}).get("list") or []
    if lst:
        if len(lst) < len(_ADS_CACHE["list"]):
            log.warning(f"[ads] 列表返回偏短({len(lst)}<{len(_ADS_CACHE['list'])}),保留旧列表")
            _ADS_CACHE["t"] = time.time()
            return _ADS_CACHE["list"]
        _ADS_CACHE["list"] = lst
        _ADS_CACHE["t"] = time.time()
        return lst
    _msg = str(r.get("msg") or "")
    log.warning(f"[ads] 列表拉取失败: {_msg}")
    if "key" in _msg.lower():
        if not ADS_KEY:
            # ★ 2026-09-20: "Require api-key" 的真正含义是【key 是空的】。
            #   实测: 空 key 走请求头, AdsPower 返回的就是这一句。
            #   以前一律说"Key 不对", 把人往"填错了"的方向带, 白折腾很久。
            log.warning("[ads] ★ 程序读到的 adspower_key 是【空的】"
                        " —— 不是填错了, 是压根没读到")
            log.warning("[ads]   常见原因: ① 改完 config.json 没重开程序;"
                        " ② 改的不是程序真正在读的那份 config.json")
        else:
            log.warning("[ads] ★ AdsPower 的 API Key 不对(每台机器的 key 都不一样)")
        log.warning("[ads]   解决: 打开 AdsPower 客户端 → 设置 → 本地API,")
        log.warning("[ads]        复制那一串 Key, 填进 config.json 的 "
                    "\"adspower_key\" 里, 然后重开本程序")
        log.warning(f"[ads]   当前用的是: {ADS_KEY[:8]}...{ADS_KEY[-4:]}"
                    f"  (来自 {ADS_BASE})")
    return _ADS_CACHE["list"]


def ads_find(profile_no=None, user_id=None):
    """按编号/ID找环境(缓存找不到时强制刷新一次,防止列表不完整导致误判)"""
    for attempt in (0, 1):
        for u in ads_list(use_cache=(attempt == 0)):
            if user_id and u.get("user_id") == user_id:
                return u
            if profile_no and str(u.get("serial_number")) == str(profile_no):
                return u
        if attempt == 0:
            log.warning(f"[ads] 缓存里没有 {profile_no or user_id},强制刷新列表")
    return None


def ads_active(_allow_stop=True):
    """活动环境列表。

    ★ 3.5: 关窗路径(_allow_stop=False)必须能穿过限速等待 —— 否则点停止后
      连"有哪些环境要关"都拿不到, 关窗路径 0 个关闭。
    """
    r = ads_req("/api/v1/browser/local-active", _allow_stop=_allow_stop)
    return (r.get("data") or {}).get("list") or []



def ads_close_all():
    """关闭所有已打开的环境(清理残留)

    ★ 以前这里会数错: ads_close() 内部自己吞掉异常、返回 True/False,
      但这个循环忽略了返回值, 无条件 n += 1。于是实测出现过:
          [ads] close err: 用户停止   ×4
          [ads] 已关闭 4 个环境          <- 一个都没关掉, 却报"已关闭 4 个"
      界面上还会跟着打印"退出前已关闭 4 个浏览器", 纯属骗人。
      现在只数真正关掉的, 没关掉的单独警告。
    """
    n = 0
    tried = 0
    try:
        act = ads_active(_allow_stop=False)   # ★ 3.5: 关窗路径不可被"停止"打断
    except Exception as e:
        log.warning(f"[ads] 取活动列表失败: {str(e)[:60]}")
        return 0
    for a in act:
        uid = a.get("user_id")
        if not uid:
            continue
        tried += 1
        try:
            if ads_close(uid):          # ★ 只有真关掉才算
                n += 1
        except Exception:
            pass
    if n:
        log.info(f"[ads] 已关闭 {n} 个环境")
    if tried > n:
        log.warning(f"[ads] 还有 {tried - n} 个环境没关掉(可能正被占用或已停止)")
    return n


def ads_open(user_id):
    last = ""
    for i in range(3):
        r = ads_req("/api/v1/browser/start", user_id=user_id)
        if r.get("code") == 0:
            d = r.get("data") or {}
            ws = (d.get("ws") or {}).get("puppeteer") or ""
            log.info(f"[ads] opened {user_id}")
            return ws
        last = str(r.get("msg"))
        if i < 2:
            log.warning(f"[ads] 打开 {user_id} 失败({last}),重试 {i+2}/3")
            sleep_or_stop(backoff(i, base=2.0, cap=8.0))   # O2: 退避+可被停止中断
    raise RuntimeError(f"AdsPower open failed: {last}")


def ads_close(user_id):
    try:
        # ★ 3.5: 关窗不可被"停止"打断 —— 否则限速等待抛 UserStopped,
        #   报 "close err: 用户停止" 却一个都没关掉
        ads_req("/api/v1/browser/stop", user_id=user_id, _allow_stop=False)
        log.info(f"[ads] closed {user_id}")
        return True
    except Exception as e:
        log.warning(f"[ads] close err: {str(e)[:60]}")
        return False
# ---------------------------------------------------------------- playwright helpers
def shot(page, tag):
    try:
        p = LOGDIR / f"shot_{tag}_{datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=str(p), full_page=False)
        log.info(f"[shot] {p.name}")
    except Exception as e:
        log.warning(f"截图失败: {e}")

def step(name):
    """分步异常保护:失败截图+日志,不中断整体"""
    def deco(fn):
        def wrapper(page, *a, **kw):
            try:
                log.info(f"== {name} 开始")
                r = fn(page, *a, **kw)
                log.info(f"== {name} 完成 -> {r}")
                return r
            except UserStopped:
                log.info(f"== {name} 被用户停止中断")
                raise            # 停止信号必须继续往上抛,不能被当成"这一步失败"
            except Exception as e:
                log.error(f"== {name} 失败: {e}")
                log.error(traceback.format_exc(limit=2))
                shot(page, f"err_{name}")
                return False
        return wrapper
    return deco

def human_click(page, locator, timeout=15000):
    loc = locator if hasattr(locator, "click") else page.locator(locator).first
    loc.wait_for(state="visible", timeout=timeout)
    try:
        box = loc.bounding_box()
        if box:
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            h = CFG.get("human", {})
            page.mouse.move(x, y, steps=random.randint(h.get("move_steps_min", 8), h.get("move_steps_max", 25)))
            human_delay(0.1, 0.35)
            page.mouse.click(x, y)
        else:
            loc.click(timeout=timeout)
    except Exception:
        loc.click(timeout=timeout)
    human_delay(0.2, 0.6)
    return True

def exact_btn(page, *texts, timeout=8000):
    """精确文字按钮(排除Apple/试用等),返回可见的第一个locator或None"""
    for t in texts:
        try:
            loc = page.get_by_role("button", name=t, exact=True)
            for i in range(loc.count()):
                b = loc.nth(i)
                try:
                    if b.is_visible():
                        return b
                except Exception:
                    continue
        except Exception:
            continue
    return None

def human_type(page, locator, text):
    loc = locator if hasattr(locator, "click") else page.locator(locator).first
    human_click(page, loc)
    try:
        loc.fill("")
    except Exception:
        pass
    h = CFG.get("human", {})
    for ch in text:
        page.keyboard.type(ch, delay=random.randint(h.get("type_delay_min", 60), h.get("type_delay_max", 180)))
    human_delay(0.2, 0.6)

def scroll_to_bottom(page):
    """滚到页面最底部:先点滚动箭头按钮,再JS强制滚动,再按End"""
    # 点圆形"滚到底部"箭头按钮
    for sel in ("[aria-label*='bottom' i]", "[aria-label*='\u5e95\u90e8']", "[aria-label*='\u6700\u4e0b']",
                "[data-tooltip*='bottom' i]", "button[jsname='z0IW4c']"):
        try:
            b = page.locator(sel).first
            if b.count() and b.is_visible():
                human_click(page, b)
                time.sleep(0.5)
                break
        except Exception:
            continue
    try:
        page.keyboard.press("End")
    except Exception:
        pass
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    try:
        page.evaluate("document.querySelectorAll('div,main,section').forEach(function(el){try{if(el.scrollHeight>el.clientHeight+50)el.scrollTop=el.scrollHeight}catch(e){}})")
    except Exception:
        pass
    time.sleep(0.6)

def accept_cookies(page, timeout=6):
    """关闭 Strava cookie 弹窗(优先 Accept All)"""
    # ★ 2.10: 绝大多数页面根本没有 cookie 弹窗, 而下面 6 个 CSS + 7 个 role + 1 个文本
    #   locator 每轮要花 3~7 秒(真机实测占 34~80 分钟/号)。先用一次 evaluate 判定,
    #   没有就立刻返回。
    try:
        _has = page.evaluate(
            "() => !!(document.querySelector("
            "'#onetrust-banner-sdk, #onetrust-consent-sdk, .optanon-alert-box-wrapper, "
            "[id*=cookie i], [class*=cookie-banner i], [aria-label*=cookie i]'))")
        if not _has:
            return False
    except Exception:
        pass          # 判定失败 -> 走原来的完整逻辑, 绝不因为加速而漏点
    end = time.time() + timeout
    while time.time() < end:
        # 类名匹配(cookieconsent 库)
        for sel in (".cc-btn.cc-allow", ".cc-allow", "button.cc-allow",
                    ".cc-dismiss", "[data-cy='accept-all']", "a.cc-btn.cc-dismiss"):
            try:
                b = page.locator(sel).first
                if b.count() and b.is_visible():
                    b.click()
                    log.info("[cookies] 已点 Accept All")
                    human_delay(0.5, 1)
                    return True
            except Exception:
                continue
        # 文本匹配(多语言)
        for nm in ("Accept All", "Accept all cookies", "全部接受", "接受全部", "接受所有",
                   "Accept", "同意全部"):
            try:
                b = page.get_by_role("button", name=re.compile("^" + re.escape(nm) + "$", re.I))
                if b.count() and b.first.is_visible():
                    b.first.click()
                    log.info(f"[cookies] 已点 {nm}")
                    human_delay(0.5, 1)
                    return True
            except Exception:
                continue
        # 兜底:任意含 Accept All 的可点元素
        try:
            el = page.locator("text=/Accept All/i").first
            if el.count() and el.is_visible():
                el.click()
                log.info("[cookies] 已点(兜底) Accept All")
                human_delay(0.5, 1)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def goto_retry(page, url, attempts=4, wait_until="domcontentloaded", timeout=30000):
    """goto带重试:被其他跳转打断时等待后重试"""
    for i in range(attempts):
        check_stop()
        try:
            if goto_same(page, url):
                return True
            _t_net = net_ready()
            page.goto(url, timeout=net_timeout(timeout), wait_until=wait_until)
            net_elapsed(_t_net)          # 用真实跳转耗时估计网速
            note_goto(page, url)
            accept_cookies(page, timeout=3)
            return True
        except Exception as e:
            msg = str(e)
            # ★ 2.9: 页面/环境已经关了, 重试毫无意义 —— 每次白付 4 次 goto
            #   + 1+2+4+8 秒退避(真机日志里这类重试刷了几百行)
            if "has been closed" in msg or "Target closed" in msg:
                return False
            if "interrupted by another navigation" in msg or "Navigation" in msg:
                log.info(f"[goto] 被跳转打断,等待重试 {i+1}/{attempts}")
                time.sleep(backoff(i))
                continue
            log.warning(f"[goto] 失败: {msg[:120]}")
            time.sleep(backoff(i))
    return False

def wait_url(page, predicate, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if predicate(page.url or ""):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False

# ---------------------------------------------------------------- steps
def is_logged_in(page):
    """登录判定。

    ★ 2026-09-19 修复(用户报"刚注册好的号, 扫描/跑任务却判未登录"):
      老写法只看标签页当前 URL —— 只要 URL 里有 /login /register /session 就
      【立刻】返回 False, 而且【不会再去验证一次】。后果: 标签页只要停在上一次的
      登录页(注册流程、上次掉线留下的页面, 都很常见), 即使浏览器里的 session
      cookie 已经有效(号其实早就登录好了), 也会被永久判成"未登录" ——
      于是 run_one 直接 "未登录,跳过", 界面回填登录=否, 其它列全空。
      新写法: 只有"停在 Strava 的【非登录页】"才算快速通过; 其余情况(登录页/
      注册页/非 Strava 页/空白页)一律实地访问一次 /login —— 有效会话会被
      Strava 自动重定向离开 /login, 加载后 URL 不再是登录页就是已登录。
      另外把 goto 的异常兜住: 原来它一抛异常就直接冒到调用方, 被 scan_one 的
      except 吞掉, 结果"打不开"和"未登录"混为一谈, 日志里也看不出原因。
    """
    def _looks_login(u):
        return ("/login" in u) or ("/register" in u) or ("/session" in u)

    try:
        u0 = page.url or ""
    except Exception:
        u0 = ""
    # 快速通过: 停在 Strava 的【非登录页】—— 说明会话是活的
    if "strava.com" in u0 and "console.bitbrowser" not in u0 and not _looks_login(u0):
        return True
    # ★ 其余情况必须实地验证一次(旧写法在这里直接 return False, 正是误判根源)
    for _try in range(2):
        try:
            page.goto("https://www.strava.com/login", timeout=30000,
                      wait_until="domcontentloaded")
            accept_cookies(page, timeout=4)
            human_delay(0.5, 1.0)
            u = page.url or ""
            _ok = ("strava.com" in u) and (not _looks_login(u))
            log.info(f"[login] 判定={('已登录' if _ok else '未登录')} | "
                     f"起始URL={u0[:70]!r} -> 访问/login后={u[:70]!r}")
            return _ok
        except Exception as e:
            log.warning(f"[login] 判定异常({_try + 1}/2): {str(e)[:70]}")
            try:
                time.sleep(backoff(_try))
            except Exception:
                time.sleep(1)
    log.warning("[login] 连续两次都没判出来 -> 按未登录处理(请查上面的异常)")
    return False

OAUTH_URL = ("https://accounts.google.com/o/oauth2/v2/auth?client_id=541588808765.apps.googleusercontent.com"
               "&redirect_uri=https%3A%2F%2Fwww.strava.com%2Fo_auth%2Fgoogle&response_type=code"
               "&scope=email%20profile&access_type=offline&prompt=select_account")

LAO_NEXT = "\u0e96\u0e31\u0e14\u0e44\u0e1b"      # ຖັດໄປ
LAO_NEXT2 = "\u0e95\u0e48\u0e2d\u0e44\u0e1b"     # ຕໍ່ໄປ
LAO_UNDERSTAND2 = "\u0e82\u0ec9\u0ead\u0e8d\u0ec0\u0e82\u0ebb\u0ec9\u0eb2\u0ec3\u0e88"

def _next_texts():
    return ["Next", "下一步", "下一个", LAO_NEXT, LAO_NEXT2, "Suivant", "Siguiente",
            "Weiter", "\u0414\u0430\u043b\u0435\u0435", "ถัดไป", "Ti\u1ebfp theo", "Avanti",
            "Pr\u00f3ximo", "Volgende", "N\u00e6ste"]

def google_next(page, kind="identifier"):
    """点谷歌'下一步':完全不依赖语言(容器ID -> 回车 -> 坐标 -> 多语言文本)"""
    ids = ("#identifierNext", "#passwordNext") if kind == "identifier" else ("#passwordNext", "#identifierNext")
    # 1) 容器内按钮(语言无关)
    for cid in ids:
        try:
            b = page.locator(f"{cid} button").first
            if b.count() and b.is_visible():
                try:
                    b.click(timeout=5000)
                except Exception:
                    box = b.bounding_box()
                    if box:
                        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                log.info(f"[google] 点下一步({cid})")
                return True
        except Exception:
            continue
    # 2) 回车提交
    try:
        page.keyboard.press("Enter")
        log.info("[google] 回车提交")
        return True
    except Exception:
        pass
    # 3) 坐标点容器
    for cid in ids:
        try:
            box = page.locator(cid).first.bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                log.info(f"[google] 坐标点下一步({cid})")
                return True
        except Exception:
            continue
    # 4) 多语言文本兜底
    for txt in _next_texts():
        try:
            b = page.get_by_role("button", name=re.compile("^" + re.escape(txt) + "$", re.I))
            if b.count() and b.first.is_visible():
                b.first.click()
                log.info(f"[google] 文本点下一步({txt})")
                return True
        except Exception:
            continue
    log.warning("[google] 没找到下一步按钮")
    return False

def wait_password_field(page, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            n = page.locator("input[type=password]").count()
            if n:
                for i in range(n):
                    if page.locator("input[type=password]").nth(i).is_visible():
                        return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def wait_left_google(page, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            u = page.url or ""
            if "accounts.google.com" not in u:
                return True
            if page.locator("#passwordNext, #identifierNext").count() == 0 and page.locator("input[type=password]").count() == 0:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def handle_google_midpage(page):
    """谷歌中间页(speedbump/条款/同意):滚到底点确认,返回是否处理了"""
    try:
        u = page.url or ""
    except Exception:
        u = ""
    if "accounts.google.com" not in u:
        return False
    if "identifier" in u or "challenge/pwd" in u:
        return False
    log.info(f"[google] 中间页: {u[:70]}")
    scroll_to_bottom(page)
    for txt in ("我了解", "我明白", "\u0e82\u0ec9\u0ead\u0e8d\u0ec0\u0e82\u0ebb\u0ec9\u0eb2\u0ec3\u0e88",
                "I understand", "Got it", "接受", "同意", "Accept", "I agree", "Agree",
                "Continue", "继续", "Allow", "允许"):
        try:
            b = page.locator("button").filter(has_text=re.compile("^" + re.escape(txt) + "$")).first
            if b.count() and b.is_visible():
                human_click(page, b)
                human_delay(1.2, 2)
                return True
        except Exception:
            continue
    try:
        btns = page.locator("button:visible")
        picked = None
        for i in range(btns.count()):
            b = btns.nth(i)
            try:
                t = (b.inner_text() or "").strip()
            except Exception:
                continue
            if not t or re.search("返回|Back|取消|Cancel|Decline|拒绝|\u0e8d\u0ebb\u0e81\u0ec0\u0ea5\u0eb5\u0e81", t):
                continue
            cls = (b.get_attribute("class") or "")
            if re.search("primary|Primary|btn-primary|VgQpJ|k8QpJ", cls):
                picked = b
            elif picked is None:
                picked = b
        if picked is not None:
            human_click(page, picked)
            human_delay(1.2, 2)
            return True
    except Exception:
        pass
    time.sleep(1.5)
    return False

def settle_google_flow(page, timeout=120):
    """等谷歌流程彻底走完:处理中间页直到落在稳定的Strava页"""
    end = time.time() + timeout
    stable = 0
    last = ""
    while time.time() < end:
        try:
            u = page.url or ""
        except Exception:
            u = ""
        if "accounts.google.com" in u:
            stable = 0
            handle_google_midpage(page)
            continue
        if "strava.com" in u:
            if u == last:
                stable += 1
            else:
                stable = 0
                last = u
            if stable >= 2:
                break
        time.sleep(2)
    # 新号可能在注册页:点Google注册
    try:
        u = page.url or ""
    except Exception:
        u = ""
    if "/register" in u:
        log.info("[google] 在注册页,点Google注册建号")
        for _ in range(3):
            b = exact_btn(page, "使用 Google 注册", "Sign up with Google")
            if b is None:
                try:
                    btns = page.locator("button[data-testid='google_auth_btn']")
                    for i in range(btns.count()):
                        bb = btns.nth(i)
                        try:
                            if bb.is_visible() and "Apple" not in (bb.inner_text() or ""):
                                b = bb
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
            if b is None:
                break
            human_click(page, b)
            human_delay(1.5, 2.5)
            # 处理随后可能的谷歌中间页
            for _ in range(10):
                try:
                    uu = page.url or ""
                except Exception:
                    uu = ""
                if "strava.com" in uu and "/register" not in uu and "accounts.google" not in uu:
                    break
                if "accounts.google.com" in uu:
                    handle_google_midpage(page)
                else:
                    time.sleep(1.5)
    return check_strava_session(page)

@step("谷歌登录")
def google_login(page, email, password):
    # 走注册页的 Google 注册(对已有谷歌会话可直接登录,新号自动建号)
    ok = False
    goto_retry(page, "https://www.strava.com/register/free")
    accept_cookies(page, timeout=5)
    human_delay(1.5, 2.5)
    for attempt in range(3):
        try:
            u = page.url or ""
            if "accounts.google.com" in u or "onboarding" in u or "dashboard" in u:
                break
            clicked = False
            for nm in ("Sign Up With Google", "使用 Google 注册", "Sign In With Google", "使用 Google 登录"):
                try:
                    b = page.get_by_role("button", name=nm)
                    if b.count() and b.first.is_visible():
                        human_click(page, b.first)
                        clicked = True
                        log.info(f"[google] 点击 {nm}")
                        break
                except Exception:
                    continue
            if clicked:
                # 等跳转(谷歌页或直接进onboarding)
                t_end = time.time() + 40
                while time.time() < t_end:
                    time.sleep(1)
                    try:
                        u2 = page.url or ""
                    except Exception:
                        u2 = ""
                    if "accounts.google.com" in u2 or "onboarding" in u2 or "dashboard" in u2:
                        break
                    try:
                        if page.locator("#identifierId").count() > 0:
                            break
                    except Exception:
                        pass
            if "accounts.google.com" in (page.url or "") or "onboarding" in (page.url or "") or "dashboard" in (page.url or ""):
                ok = True
                break
        except Exception as e:
            log.warning(f"注册页尝试{attempt+1}: {str(e)[:100]}")
    for attempt in range(3):
        try:
            u = page.url or ""
            if "accounts.google.com" in u:
                ok = True
                break
            clicked = False
            b = exact_btn(page, "\u4f7f\u7528 Google \u767b\u5f55", "\u4f7f\u7528 Google \u6ce8\u518c",
                          "Sign in with Google", "Sign up with Google")
            if b is not None:
                human_click(page, b)
                clicked = True
            else:
                try:
                    btns = page.locator("button[data-testid='google_auth_btn']")
                    for i in range(btns.count()):
                        bb = btns.nth(i)
                        try:
                            if bb.is_visible() and "Apple" not in (bb.inner_text() or ""):
                                human_click(page, bb)
                                clicked = True
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
            # 点完耐心等跳转(谷歌很慢);没点到就短等
            if clicked:
                t_end = time.time() + 40
                while time.time() < t_end:
                    time.sleep(1)
                    try:
                        if "accounts.google.com" in (page.url or ""):
                            break
                    except Exception:
                        pass
                    try:
                        if page.locator("#identifierId").count() > 0:
                            break
                    except Exception:
                        pass
            else:
                time.sleep(2)
            if "accounts.google.com" in (page.url or ""):
                ok = True
                break
        except Exception as e:
            log.warning(f"Google按钮尝试{attempt+1}: {e}")
    try:
        u_now = page.url or ""
    except Exception:
        u_now = ""
    if "onboarding" in u_now or "dashboard" in u_now:
        log.info(f"[google] 已直接登录: {u_now[:80]}")
        return check_strava_session(page)
    if not ok:
        # 可能跳转还在路上,再等一次
        wait_url(page, lambda x: "accounts.google.com" in x, timeout=20)
        ok = "accounts.google.com" in (page.url or "")
    if not ok:
        log.warning("没能进入谷歌页")
        return False
    human_delay(1, 2)
    # 邮箱(只认谷歌页的框,等它出现)
    try:
        page.locator("#identifierId").first.wait_for(state="visible", timeout=20000)
    except Exception:
        log.warning("谷歌邮箱框迟迟没出现")
    em = page.locator("#identifierId")
    if em.count() == 0:
        log.warning("没找到谷歌邮箱框")
        return False
    human_type(page, em, email)
    # 邮箱下一步:不依赖语言,点完验证,没生效就重试
    advanced = False
    for attempt in range(3):
        google_next(page, "identifier")
        advanced = wait_password_field(page, timeout=15)
        if advanced:
            break
        log.info(f"[google] 邮箱下一步未生效,重试{attempt+1}")
        human_delay(0.8, 1.5)
        try:
            em.click()
            page.keyboard.press("End")
        except Exception:
            pass
    if not advanced:
        log.warning("[google] 邮箱提交后没出现密码框")
        return False
    # 密码
    pw = page.locator("input[type=password]").first
    human_type(page, pw, password)
    # 密码下一步:同样不依赖语言,点完验证
    for attempt in range(3):
        google_next(page, "password")
        if wait_left_google(page, timeout=15):
            break
        log.info(f"[google] 密码下一步未生效,重试{attempt+1}")
        human_delay(0.8, 1.5)
        try:
            pw = page.locator("input[type=password]").first
            if pw.count():
                pw.click()
        except Exception:
            pass
    human_delay(1.5, 3)
    # 密码下一步后可能出现中间确认页(老挝语按钮等):循环点主按钮直到回Strava
    for _ in range(10):
        try:
            u = page.url or ""
        except Exception:
            u = ""
        if "strava.com" in u:
            break
        done = False
        for txt in ("我明白", "I understand", "Continue", "继续"):
            try:
                b = page.locator("button").filter(has_text=re.compile("^" + re.escape(txt) + "$")).first
                if b.count() and b.is_visible():
                    human_click(page, b)
                    done = True
                    break
            except Exception:
                continue
        if done:
            human_delay(1, 2)
            continue
        # 通用:点主按钮(排除返回/取消,优先primary样式)
        try:
            cands = page.locator("button:visible")
            picked = None
            for i in range(cands.count()):
                b = cands.nth(i)
                try:
                    t = (b.inner_text() or "").strip()
                except Exception:
                    continue
                if not t or re.search("返回|Back|取消|Cancel|后退", t):
                    continue
                cls = (b.get_attribute("class") or "")
                if re.search("primary|Primary|btn-primary", cls):
                    picked = b
                    break
                if picked is None:
                    picked = b
            if picked is not None:
                human_click(page, picked)
                human_delay(1.2, 2)
                continue
        except Exception:
            pass
        time.sleep(1)
    # 谷歌中间页(speedbump/条款/同意):翻到底部点"我了解"(多语言),直到回到Strava
    for _ in range(10):
        try:
            uu = page.url or ""
        except Exception:
            uu = ""
        if "strava.com" in uu or "accounts.google.com" not in uu:
            break
        if "identifier" in uu or "challenge/pwd" in uu:
            break
        log.info(f"[google] 中间页: {uu[:70]}")
        scroll_to_bottom(page)
        hit = False
        for txt in ("我了解", "我明白", "\u0e82\u0ec9\u0ead\u0e8d\u0ec0\u0e82\u0ebb\u0ec9\u0eb2\u0ec3\u0e88",
                    "I understand", "Got it", "接受", "同意", "Accept", "I agree", "Agree",
                    "Continue", "继续", "Allow", "允许"):
            try:
                b = page.locator("button").filter(has_text=re.compile("^" + re.escape(txt) + "$")).first
                if b.count() and b.is_visible():
                    human_click(page, b)
                    hit = True
                    break
            except Exception:
                continue
        if not hit:
            try:
                btns = page.locator("button:visible")
                picked = None
                for i in range(btns.count()):
                    b = btns.nth(i)
                    try:
                        t = (b.inner_text() or "").strip()
                    except Exception:
                        continue
                    if not t or re.search("返回|Back|取消|Cancel|Decline|拒绝|\u0e8d\u0ebb\u0e81\u0ec0\u0ea5\u0eb5\u0e81", t):
                        continue
                    cls = (b.get_attribute("class") or "")
                    if re.search("primary|Primary|btn-primary|VgQpJ|k8QpJ", cls):
                        picked = b
                    elif picked is None:
                        picked = b
                if picked is not None:
                    human_click(page, picked)
                    hit = True
            except Exception:
                pass
        if not hit:
            time.sleep(1.5)
        human_delay(1.2, 2)

    # 服务条款 speedbump 页(Workspace ToS):翻到底部点"我了解"(老挝语等多语言)
    LAO_UNDERSTAND = "\u0e82\u0ec9\u0ead\u0e8d\u0ec0\u0e82\u0ebb\u0ec9\u0eb2\u0ec3\u0e88"
    for _ in range(6):
        try:
            u = page.url or ""
        except Exception:
            u = ""
        if "strava.com" in u:
            break
        if "speedbump" in u or "termsofservice" in u or "/tos" in u or "consent" in u:
            log.info(f"[google] 条款/同意页: {u[:70]}")
            # 先滚到底部(按钮在最下面)
            scroll_to_bottom(page)
            done = False
            for txt in ("我了解", "我明白", LAO_UNDERSTAND, "I understand", "Got it", "接受", "同意",
                        "Accept", "I agree", "Agree", "继续", "Continue"):
                try:
                    b = page.locator("button").filter(has_text=re.compile("^" + re.escape(txt) + "$")).first
                    if b.count() and b.is_visible():
                        human_click(page, b)
                        done = True
                        break
                except Exception:
                    continue
            if not done:
                # 兜底:底部最后一个可见按钮(排除返回/取消/拒绝)
                try:
                    btns = page.locator("button:visible")
                    picked = None
                    for i in range(btns.count()):
                        b = btns.nth(i)
                        try:
                            t = (b.inner_text() or "").strip()
                        except Exception:
                            continue
                        if not t or re.search("返回|Back|取消|Cancel|Decline|拒绝|ຍົກເລີກ", t):
                            continue
                        cls = (b.get_attribute("class") or "")
                        if re.search("primary|Primary|btn-primary|VfPpkd-LgbsSe-OWXEXe-k8QpJ", cls):
                            picked = b
                        elif picked is None:
                            picked = b
                    if picked is not None:
                        human_click(page, picked)
                        done = True
                except Exception:
                    pass
            human_delay(1.5, 2.5)
        else:
            break
    wait_url(page, lambda u: "strava.com" in u, timeout=20)
    # 新谷歌号会落在注册页:点"使用 Google 注册"建号
    try:
        u = page.url or ""
    except Exception:
        u = ""
    if "/register" in u:
        log.info("[google] 新号在注册页,点Google注册建号")
        for _ in range(3):
            try:
                b = exact_btn(page, "使用 Google 注册", "Sign up with Google")
                if b is None:
                    try:
                        btns = page.locator("button[data-testid='google_auth_btn']")
                        for i in range(btns.count()):
                            bb = btns.nth(i)
                            try:
                                if bb.is_visible() and "Apple" not in (bb.inner_text() or ""):
                                    b = bb
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass
                if b is None:
                    break
                human_click(page, b)
                human_delay(1.5, 2.5)
                # 注册后可能再过同意页:通用点主按钮
                for _ in range(6):
                    try:
                        uu = page.url or ""
                    except Exception:
                        uu = ""
                    if "strava.com" in uu and "/register" not in uu and "accounts.google" not in uu:
                        break
                    clicked2 = False
                    for txt in ("Continue", "继续", "我明白", "I understand", "接受", "同意", "Accept", "Allow"):
                        try:
                            bb2 = page.locator("button").filter(has_text=re.compile("^" + re.escape(txt) + "$")).first
                            if bb2.count() and bb2.is_visible():
                                human_click(page, bb2)
                                clicked2 = True
                                break
                        except Exception:
                            continue
                    if not clicked2:
                        time.sleep(1)
                    human_delay(0.8, 1.5)
            except Exception as e:
                log.warning(f"注册建号异常: {e}")
                break
    # 等流程彻底走完(含回调后的条款页/注册页)
    return settle_google_flow(page, timeout=120)

def check_strava_session(page):
    """不跳转判断Strava会话:已在dashboard/onboarding/设置页算成功"""
    try:
        u = page.url or ""
    except Exception:
        return False
    if "strava.com" not in u:
        return False
    if "/login" in u:
        return False
    if "/register" in u:
        return False
    return True

def wait_manual_login(page, timeout=300):
    log.info(f"[manual] 请在窗口手动完成登录,最多等{timeout}秒")
    end = time.time() + timeout
    while time.time() < end:
        try:
            if is_logged_in(page):
                log.info("[manual] 检测到已登录")
                return True
        except Exception:
            pass
        time.sleep(5)
    return False

@step("onboarding")
def do_onboarding(page, eng_name):
    # cookie 接受(多语言,含新弹窗)
    accept_cookies(page, timeout=6)
    human_delay(0.5, 1)
    parts = (eng_name or "Emily Chen").split(" ", 1)
    fn, ln = parts[0], (parts[1] if len(parts) > 1 else "Chen")
    import datetime as _dt
    start = _dt.date(1985, 1, 1); end = _dt.date(1988, 12, 31)
    bday = (start + _dt.timedelta(days=random.randint(0, (end - start).days))).strftime("%Y-%m-%d")
    filled_dialog = False
    # ★★ 2026-09-24 血案: 原来这里只 count() 一次就决定填不填弹窗 ★★
    #   登录后落到 /onboarding/continue 时弹窗还没渲染出来 -> count()==0 ->
    #   下面整段「填名字/生日/性别」被跳过 -> 「Create your profile」一直挂着 ->
    #   Strava 把 /settings/profile 全部重定向回 /onboarding/continue ->
    #   改位置/头像/性别/隐私/单位 五步全报"元素不可见", 号还顶着随机名
    #   (实测 87 号叫 "Mandy Curran")。整批 22 个号会全废。
    #   改成有界等待: 最多 20 秒等弹窗出现, 别抢在渲染之前下结论。
    dlg = None
    _t_dlg = time.time()
    while time.time() - _t_dlg < 20:
        _d = page.locator("[role=dialog]").filter(has_text=re.compile("Create your profile|创建你的个人资料|创建个人资料")).first
        if _d.count() == 0:
            # 兜底:找含 Select... 的可见弹窗
            _d = page.locator("[role=dialog]").filter(has_text="Select").first
        if _d.count():
            dlg = _d
            break
        time.sleep(1)
    if dlg is None:
        log.warning("[onboard] 等 20 秒也没出现「Create your profile」弹窗")
    if dlg is not None:
        texts = dlg.locator("input[type=text]")
        if texts.count() >= 2:
            human_type(page, texts.nth(0), fn)
            human_type(page, texts.nth(1), ln)
        d = dlg.locator("input[type=date]")
        if d.count():
            try:
                d.first.fill(bday)
            except Exception:
                page.evaluate(f"var x=document.querySelector('input[type=date]');if(x){{x.value='{bday}';x.dispatchEvent(new Event('change',{{bubbles:true}}))}}")
        # 性别下拉(点箭头打开,选"女")
        try:
            ctrl = dlg.locator("[class*=control], [class*=indicatorContainer], [class*=ValueContainer]").first
            if ctrl.count() == 0:
                ctrl = dlg.locator("div").filter(has_text=re.compile(r"^Select\.\.\.$")).first
            human_click(page, ctrl)
            human_delay(0.6, 1)
            picked = False
            try:
                opts = page.locator("[class*=option], [role=option]")
                for i in range(opts.count()):
                    o = opts.nth(i)
                    try:
                        t = (o.inner_text() or "").strip()
                    except Exception:
                        continue
                    if re.search("^(女|Woman|Female)$", t, re.I):
                        human_click(page, o)
                        picked = True
                        log.info(f"[onboard] 性别选: {t}")
                        break
                if not picked and opts.count() > 1:
                    human_click(page, opts.nth(1))
                    picked = True
                    log.info("[onboard] 性别选第2项")
            except Exception as e:
                log.warning(f"性别选项异常: {e}")
        except Exception as e:
            log.warning(f"性别选择失败: {e}")
        b = dlg.locator("button").filter(has_text=re.compile("^(Continue|继续|保存|Save)$")).first
        if b.count() == 0:
            b = dlg.locator("button").last
        human_click(page, b)
        # Strava提交慢,等弹窗真正消失(最多90秒);不消失就再点一次
        gone = False
        for i in range(60):
            time.sleep(3)
            try:
                if page.locator("[role=dialog]").count() == 0:
                    gone = True
                    break
            except Exception:
                gone = True
                break
            if i in (10, 25):
                try:
                    b.click(timeout=5000)
                    log.info("[onboard] 再点一次 Continue")
                except Exception:
                    pass
        filled_dialog = gone
        log.info(f"[onboard] 资料弹窗{'已提交' if gone else '仍未消失'}")
        human_delay(1, 2)
    # 跳过链
    for _ in range(14):
        try:
            u = page.url or ""
        except Exception:
            u = ""
        if "onboarding" not in u and "subscribe" not in u:
            break
        scroll_to_bottom(page)
        clicked = False
        if "subscription-trial" in u or "subscribe" in u:
            for txt in ("也许以后", "Maybe later", "No thanks"):
                b = page.locator(f"button:has-text('{txt}')").first
                if b.count() and b.is_visible():
                    human_click(page, b); clicked = True; break
        elif "suggested-friends" in u:
            for txt in ("Skip for Now", "现在跳过", "Skip"):
                b = page.get_by_role("button", name=re.compile("^" + re.escape(txt) + "$", re.I))
                if b.count() and b.first.is_visible():
                    human_click(page, b.first); clicked = True; break
                b2 = page.locator(f"button:has-text('{txt}')").first
                if b2.count() and b2.is_visible():
                    human_click(page, b2); clicked = True; break
        elif u.rstrip("/").endswith("/onboarding"):
            b = page.locator("button:has-text('开始'), button:has-text('Get Started')").first
            if b.count() and b.is_visible():
                human_click(page, b); clicked = True
        else:
            for txt in ("跳过", "Skip", "Skip for Now", "继续", "Continue", "下一步"):
                try:
                    b = page.get_by_role("button", name=re.compile("^" + re.escape(txt) + "$", re.I))
                    if b.count() and b.first.is_visible():
                        human_click(page, b.first); clicked = True; break
                except Exception:
                    pass
                b2 = page.locator(f"button:has-text('{txt}')").first
                if b2.count() and b2.is_visible():
                    human_click(page, b2); clicked = True; break
        if not clicked:
            time.sleep(1)
        human_delay(0.6, 1.4)
    log.info(f"[onboard] 跳过链结束, 新号={filled_dialog}")
    return filled_dialog

@step("改资料")

def current_location(page):
    """读资料页当前位置文本"""
    for _ in range(2):
        try:
            goto_retry(page, "https://www.strava.com/settings/profile")
            accept_cookies(page, timeout=3)
            wait_text(page,
                      "!!(document.querySelector('div.editable-setting') "
                      "&& /Location|\u4f4d\u7f6e/.test(document.body.innerText))",
                      timeout=3.0, key="location")
            return page.evaluate(r"""() => {
                var rows=[...document.querySelectorAll('div.editable-setting')];
                var row=rows.find(r=>/Location|\u4f4d\u7f6e/.test(r.textContent||''));
                return row ? (row.textContent||'').replace(/\\s+/g,' ').trim().slice(0,120) : '';
            }""") or ""
        except UserStopped:
            raise            # ★ 2.7: 点停止不是"读取失败", 不能把在飞的号判成空值
        except Exception as e:
            log.warning(f"[location] check err: {str(e)[:60]}")
            time.sleep(2)
    return ""


def location_ok(text):
    """位置是否已是目标城市(默认 Chicago / Los Angeles)

    ★ 2026-09-24: 以前是 `目标 in 文本`, 于是 "Lake Los Angeles, California"
      含 "Los Angeles" 就被判合格 —— 可它不是洛杉矶市(实测 2 个号卡在这,
      永远修不回来)。现在要求【以目标开头】: Strava 的地址格式就是
      "城市, 州, 国家"; 页面上读回来的文本前面还带着 "Location" 标签, 先剥掉。
    """
    t = re.sub(r"^\s*(location|位置)\s*", "", (text or "").lower()).strip()
    t = t.lstrip("~, ").strip()
    targets = CFG.get("target_locations") or ["Chicago", "Los Angeles"]
    return any(t.startswith(str(x).lower()) for x in targets)


def set_profile(page, name=None, location=None, avatar=None):
    goto_retry(page, "https://www.strava.com/settings/profile")
    human_delay(1.2, 2.2)
    ok = True
    # 名字由 onboarding 弹窗设置,这里不再改(旧号跳过)
    if location:
        row = page.locator("div.editable-setting").filter(has_text=re.compile("Location|位置")).first
        try:
            human_click(page, row.locator(".app-icon").first)
            human_delay(0.5, 1)
            inp = page.locator("input[name='geo-search-box-input'], .geo-search-box-input, .GeoSearchBoxCustom--input--CRWeK").first
            human_type(page, inp, location)
            human_delay(1.5, 2.5)
            # 等联想下拉并选第一项
            # ★★ 2026-09-24 血案: 这里原来【无条件点联想列表第一项】★★
            #   实测 "Los Angeles, California" 的第一项经常是
            #   "Bahía de los Ángeles, Baja California Mexico"(墨西哥!) 或
            #   "Lake Los Angeles, California" —— 22 个号跑下来 7 个城市写错,
            #   6 个住到了墨西哥; 而且末尾还会 ArrowDown+Enter 再盲选一次。
            #   现在按「城市 + 州」逐项比对: 优先"以城市开头"的项, 其次
            #   "含城市且不含墨西哥"; 一项都不匹配就【不点】——
            #   宁可这步留到下一轮重做, 也不许把错城市写上去。
            _city = (location or "").split(",")[0].strip().lower()
            _st = (location.split(",")[1].strip().lower()[:2]
                   if "," in (location or "") else "")
            picked, _hit, _fall = False, None, None
            _cands = []
            for sel in (".pac-item", "[class*=suggestion]", "li[role=option]",
                        "[class*=option]"):
                try:
                    opts = page.locator(sel)
                    _n = min(opts.count(), 12)
                except Exception:
                    continue
                for _i in range(_n):
                    o = opts.nth(_i)
                    try:
                        if not o.is_visible():
                            continue
                        t = (o.inner_text() or "").strip().lower()
                    except Exception:
                        continue
                    _cands.append(f"{sel}#{_i}={t[:46]!r}")
                    if not t or len(t) > 70:
                        continue        # 太长的是容器, 不是列表项
                    if _st and _st not in t:
                        continue
                    if t.startswith(_city):
                        if _hit is None:
                            _hit = o
                    elif _city in t and "mexico" not in t and "méxico" not in t:
                        if _fall is None:
                            _fall = o
                if _hit is not None or _fall is not None:
                    break
            if _cands:
                log.info(f"[location] 「{location}」候选 {len(_cands)} 条: "
                         + " | ".join(_cands[:6]))
            _pick = _hit if _hit is not None else _fall
            if _pick is not None:
                human_click(page, _pick)
                picked = True
            else:
                log.warning(f"[location] 联想里没有匹配「{location}」的项, 不点"
                            f"(免得写成别的城市)")
            human_delay(0.5, 1)
            save = None
            for nm in ("保存", "Save"):
                try:
                    b = row.get_by_role("button", name=nm)
                    if b.count() and b.first.is_visible():
                        save = b.first
                        break
                except Exception:
                    continue
            if save is None:
                try:
                    b = page.get_by_role("button", name=re.compile("保存|Save"))
                    if b.count():
                        save = b.first
                except Exception:
                    pass
            if save is not None:
                human_click(page, save)
            human_delay(1.5, 2.5)
        except Exception as e:
            log.warning(f"改位置失败: {e}"); ok = False
    if avatar and Path(avatar).exists():
        try:
            f = page.locator("#athlete_image")
            f.set_input_files(avatar)
            page.wait_for_url(re.compile(r"/pictures/"), timeout=20000)
            human_delay(0.8, 1.5)
            sb = page.locator("input[type=submit][name=commit], input[type=submit][value=Save]").first
            human_click(page, sb)
            wait_url(page, lambda u: "/pictures/" not in u, timeout=20)
            human_delay(1, 2)
        except Exception as e:
            log.warning(f"换头像失败: {e}"); ok = False
    return ok

@step("性别设置")
def set_gender(page, value="woman"):
    """资料页->性别->选女->保存"""
    goto_retry(page, "https://www.strava.com/settings/profile")
    # 原来固定等 1.2~2 秒;改成等 editable-setting 行渲染出来
    wait_text(page, "document.querySelectorAll('div.editable-setting').length",
              timeout=2.5, key="profile_rows")
    r = page.evaluate("""() => {
      var rows=[...document.querySelectorAll('div.editable-setting')];
      var row=rows.find(x=>/Gender|性别/.test(x.textContent||''));
      if(!row) return 'NOROW';
      var cur=(row.textContent||'').replace(/\\s+/g,' ');
      if(/女|Woman|Female/i.test(cur)) return 'ALREADY';
      var i=row.querySelector('.app-icon')||row.querySelector('.app-icon-wrapper');
      if(i){i.click(); return 'clicked';}
      return 'NOICON';
    }""")
    log.info(f"[gender] {r}")
    if r == "ALREADY":
        return True
    human_delay(1.2, 2)
    ok = page.evaluate("""() => {
      var i=document.querySelector("input[name='gender'][value='woman']");
      if(!i) return 'NOFIELD';
      var l=i.closest('label');
      if(l) l.click(); else i.click();
      return 'picked';
    }""")
    log.info(f"[gender] {ok}")
    human_delay(1, 1.6)
    # 保存
    try:
        rows = page.locator("div.editable-setting").filter(has_text=re.compile("Gender|性别")).first
        saved = False
        for nm in ("保存", "Save"):
            try:
                b = rows.get_by_role("button", name=nm)
                if b.count() and b.first.is_visible():
                    human_click(page, b.first)
                    saved = True
                    break
            except Exception:
                continue
        if not saved:
            b = page.get_by_role("button", name=re.compile("保存|Save"))
            if b.count():
                human_click(page, b.first)
    except Exception as e:
        log.warning(f"[gender] 保存异常: {e}")
    human_delay(1.5, 2.5)
    # 回读
    cur = page.evaluate("""() => {
      var rows=[...document.querySelectorAll('div.editable-setting')];
      var row=rows.find(x=>/Gender|性别/.test(x.textContent||''));
      return row?(row.textContent||'').replace(/\\s+/g,' ').trim().slice(0,30):'?';
    }""")
    log.info(f"[gender] 现在: {cur}")
    return bool(re.search("女|Woman|Female", cur or "", re.I))

@step("隐私设置")
def set_privacy(page, set_profile_visibility=True):
    goto_retry(page, "https://www.strava.com/settings/privacy")
    human_delay(1.5, 2.5)
    ok = True
    # 个人资料页面 -> 关注者(ADS版不设)
    if not set_profile_visibility:
        log.info("[privacy] 跳过 个人资料页面设置")
    try:
        if not set_profile_visibility:
            raise StopIteration
        cur = page.evaluate("""() => {
          var i=document.querySelector("input[name='profile_visibility'][value='followers_only']");
          return i? i.checked : null;
        }""")
        if cur is False:
            for v in ("everyone", "followers_only"):
                page.evaluate(f"""() => {{
                  var i=document.querySelector("input[name='profile_visibility'][value='{v}']");
                  if(i){{ var l=i.closest('label'); if(l) l.click(); else i.click(); }}
                }}""")
                human_delay(0.6, 1)
            # 点"好的"确认
            try:
                b = page.get_by_role("button", name=re.compile("^(好的|OK|Done|确定)$"))
                if b.count() and b.first.is_visible():
                    human_click(page, b.first)
                    human_delay(1, 1.6)
            except Exception:
                pass
            cur2 = page.evaluate("""() => {
              var i=document.querySelector("input[name='profile_visibility'][value='followers_only']");
              return i? i.checked : null;
            }""")
            log.info(f"[privacy] 个人资料页面 关注者 {cur}->{cur2}")
        else:
            log.info("[privacy] 个人资料页面已是关注者")
    except StopIteration:
        pass
    except Exception as e:
        log.warning(f"个人资料页面设置失败: {e}")

    # 小组活动 -> 任何人都不能
    try:
        checked = page.evaluate("() => { var i=document.querySelector(\"input[name='group_activity_visibility'][value='no_one']\"); return i? i.checked : null; }")
        if checked is False:
            for v in ("everyone", "no_one"):
                page.evaluate(f"""() => {{
                  var i=document.querySelector("input[name='group_activity_visibility'][value='{v}']");
                  if(i){{ var l=i.closest('label'); if(l) l.click(); else i.click(); }}
                }}""")
                human_delay(0.6, 1)
            okbtn = page.locator("button").filter(has_text=re.compile("^(OK|好的|Done|确定)$")).first
            human_click(page, okbtn)
            human_delay(1, 2)
        elif checked is True:
            log.info("[privacy] 小组活动已是'任何人不可见', 直接跳过")
        else:
            log.warning("[privacy] 找不到 小组活动 控件(页面可能没加载完), 本次未确认")
    except Exception as e:
        log.warning(f"小组活动失败: {e}"); ok = False
    # 隐私地图 -> 全隐藏(用户口径里的"隐私地图"; 控件 id = default-activity-map-visibility)
    try:
        checked = page.evaluate("() => { var i=document.querySelector('#default-activity-map-visibility'); return i? i.checked : null; }")
        if checked is False:
            page.evaluate("""() => {
              var i=document.querySelector('#default-activity-map-visibility');
              if(!i) return;
              var w=i.closest('span[role=checkbox]')||i.closest('label')||i.parentElement;
              if(w) w.click(); else i.click();
            }""")
            human_delay(0.8, 1.5)
            checked2 = page.evaluate("() => { var i=document.querySelector('#default-activity-map-visibility'); return i? i.checked : null; }")
            log.info(f"[privacy] 隐私地图(地图全隐藏) {checked}->{checked2}")
        elif checked is True:
            log.info("[privacy] 隐私地图已是'全隐藏', 直接跳过")
        else:
            log.warning("[privacy] 找不到 隐私地图 控件(页面可能没加载完), 本次未确认")
    except Exception as e:
        log.warning(f"地图开关失败: {e}"); ok = False
    # 开始时间打勾
    try:
        chk = page.evaluate("() => { var i=document.querySelector('#start_time'); return i? i.checked : null; }")
        if chk is False:
            page.evaluate("""() => {
              var l=document.querySelector('label[for=start_time]');
              if(l) l.click();
              else { var i=document.querySelector('#start_time'); if(i) i.click(); }
            }""")
            human_delay(0.6, 1.2)
            chk2 = page.evaluate("() => { var i=document.querySelector('#start_time'); return i? i.checked : null; }")
            log.info(f"[privacy] 开始时间 {chk}->{chk2}")
        elif chk is True:
            log.info("[privacy] 开始时间已隐藏, 直接跳过")
        else:
            log.warning("[privacy] 找不到 开始时间 控件(页面可能没加载完), 本次未确认")
    except Exception as e:
        log.warning(f"开始时间失败: {e}"); ok = False
    return ok

@step("单位设置")
def set_units(page):
    goto_retry(page, "https://www.strava.com/settings/display")
    human_delay(1.2, 2)
    row = page.locator("div.editable-setting").filter(has_text=re.compile("Units|单位")).first
    try:
        if re.search("Miles|英里", row.inner_text()):
            return True
        human_click(page, row.locator(".app-icon").first)
        human_delay(0.5, 1)
        sel = page.locator("#default-measurement-js")
        sel.select_option("feet")
        human_delay(0.4, 0.8)
        save = row.locator("button").filter(has_text=re.compile("^(Save|保存)$")).first
        if save.count():
            human_click(page, save)
        human_delay(0.8, 1.5)
        return True
    except Exception as e:
        log.warning(f"单位设置失败: {e}")
        return False

# ---------------------------------------------------------------- 上传标题
# ★ 用户 2026-09-21 要求: 上传的每一份活动标题都得是「早晨跑步」(图里是 Morning Run)。
#   ★★ 在真页面上探过之后才知道的关键点 ★★
#     上传页【每个文件一张卡片】, 卡片上自带两个可填项:
#         <input name="name">                                <- Strava 已自动填好
#         <div class="... sport-type"><div class="selection">Workout</div>
#     Strava 自动填的是「时间段 + 活动类型」, 默认类型是 Workout; 而那个
#     "时间段"是按【账号所在时区】算的 —— 同一份素材在不同号上能算出
#     Morning/Afternoon 不同结果(实测: 本地早上 07:38 的素材被填成
#     "Afternoon Workout")。所以【去改素材里的时间根本管不住标题】。
#     唯一可靠的办法: 就在这个输入框里把标题写死, 顺手把类型选成 Run。
ACT_TITLE = "Morning Run"
ACT_SPORT = "Run"
# ★ 2026-09-24 用户要"洛杉矶骑行轨迹": 素材是什么运动, 标题/类型就跟着走。
#   以前这里写死 Run, 上传 Sport="Biking" 的 TCX 会被强行改成跑步。
_SPORT_MAP = {
    "biking": ("Morning Ride", "Ride"),
    "cycling": ("Morning Ride", "Ride"),
    "ride": ("Morning Ride", "Ride"),
    "running": ("Morning Run", "Run"),
    "run": ("Morning Run", "Run"),
}


def sport_of(files):
    """从素材认出运动类型 -> (标题, Strava 类型)。认不出退回跑步(老行为)。

    只看前 3 个文件, 只读开头 4000 字符 —— TCX 的 Sport 属性就在 <Activity> 上。
    """
    for p in list(files or [])[:3]:
        try:
            head = Path(p).read_text(encoding="utf-8", errors="ignore")[:4000]
        except Exception:
            continue
        m = re.search(r'Sport="([^"]+)"', head)
        if m:
            hit = _SPORT_MAP.get(m.group(1).strip().lower())
            if hit:
                return hit
    return ACT_TITLE, ACT_SPORT


def set_act_title(page, want=0, title=None, sport=None):
    """把上传页每张就绪卡片的标题写成 title、类型选成 sport。返回改了几张。

    ★ 必须【一张一张】改: 一批 15 个文件就是 15 张卡片、15 个标题输入框。
    ★ 必须按【可见】来等, 不能只数个数 —— 解析没完成时表单是 display:none,
      输入框 count 得到、fill 却会一张一张等到超时(实测 30 秒 × 每张)。
      另外 form.good 永远带着 hidden 类(靠内联 display:block 显示),
      所以只能用 :visible, 不能用 :not(.hidden)。
    ★ 必须用 playwright 的 fill()/click(), 不能用 JS 直接赋 value ——
      那是 Strava 自己的组件, 直接改 value 不触发事件, 提交时会被盖回去。
    ★ 必须在点"保存并查看"【之前】做完 —— 一提交这页就没了。
    """
    forms = page.locator("form.good:visible")
    want = max(1, int(want or 0))
    title = title or ACT_TITLE          # 不传就还是老行为(早晨跑步)
    sport = sport or ACT_SPORT
    last, still, t0 = -1, 0, time.time()
    while time.time() - t0 < 30:
        try:
            cur = forms.count()
        except Exception:
            cur = 0
        if cur >= want:
            break                    # 该出来的都出来了
        if cur and cur == last:
            still += 1
            if still >= 8:           # 有卡片了、4 秒没再变 -> 剩下的是传过的/解析失败的
                break
        else:
            still = 0
        last = cur
        time.sleep(0.5)

    n, cnt = 0, forms.count()
    for i in range(cnt):
        f = forms.nth(i)
        try:
            f.locator("input[name=name]").first.fill(title)
            n += 1
        except Exception as e:
            log.warning(f"[upload] 第{i+1}条标题没填上: {str(e)[:50]}")
        try:
            f.locator(".drop-down-menu.sport-type .selection").first.click(timeout=3000)
            f.locator(f"li[data-value='{sport}']").first.click(timeout=3000)
        except Exception as e:
            log.warning(f"[upload] 第{i+1}条类型没选上: {str(e)[:50]}")
        try:
            # ★ 2026-09-24: 选完不关菜单, 下一张的 .selection 会被挡住 ->
            #   实测每批第2~9条全超时3秒(结果不错, 但白等24秒/批)。
            page.keyboard.press("Escape")
        except Exception:
            pass
    if n:
        log.info(f"[upload] 已设 {n}/{cnt} 条: 标题「{title}」 类型 {sport}")
    else:
        log.warning(f"[upload] 没有就绪的卡片 —— 这批标题没改成「{title}」")
    return n


@step("上传轨迹")
def upload_gpx(page, files, tag="", per_batch=None, daily_cap=None):
    # ★ 2.6: 界面把这两个值当字符串传进来("15"/"38"), 以前直接拿去算
    #   `daily_cap - used` 会 TypeError -> 上传 100% 失败。这里统一转 int。
    try:
        per_batch = int(str(per_batch).strip())
    except Exception:
        per_batch = 0
    if per_batch <= 0:
        per_batch = int(CFG.get("per_batch") or 15) or 15
    try:
        daily_cap = int(str(daily_cap).strip())
    except Exception:
        daily_cap = 0
    if daily_cap <= 0:
        daily_cap = int(CFG.get("daily_cap") or 38) or 38
    st = load_state().get(str(tag), {})
    done = set(st.get("uploaded", []))
    todo = [p for p in files if str(p) not in done]
    if not todo:
        log.info("轨迹都已传过,跳过")
        return True
    log.info(f"待传{len(todo)}个(按日期顺序)")
    counter = _data_path(f"upload_counter_{str(tag).lstrip('_')}.txt")
    today = datetime.now().strftime("%Y-%m-%d")
    used = 0
    if counter.exists():
        try:
            d, n = counter.read_text().strip().split(",")
            if d == today:
                used = int(n)
        except Exception:
            pass
    remain = daily_cap - used
    if remain <= 0:
        log.info(f"今日已达上限{daily_cap},明天继续")
        return True
    todo = todo[:remain]
    log.info(f"待传{len(todo)}个,每批{per_batch}")
    for i in range(0, len(todo), per_batch):
        check_stop()
        batch = todo[i:i + per_batch]
        goto_retry(page, "https://www.strava.com/upload/select")
        human_delay(1.2, 2)
        fb = page.locator("input[name='files[]']").first
        fb.set_input_files([str(p) for p in batch])
        log.info(f"第{i//per_batch+1}批 {len(batch)}个,提交...")
        set_act_title(page, len(batch), *sport_of(batch))   # ★ 必须在点"保存并查看"之前: 标题+类型
        # 边提交边查红:红色警告一出现立即停止(不再多批重试)
        t0 = time.time()
        clicked = False
        hit_red = False
        while time.time() - t0 < 25:
            err = upload_errors(page)
            if err and err.get("count", 0) > 0:
                dups = err.get("dup_dates", [])
                done_files = []
                for f in batch:
                    fn = str(f)
                    for d in dups:
                        if d in Path(fn).name:
                            done_files.append(fn)
                            break
                st = load_state()
                up = set(st.get(str(tag), {}).get("uploaded", []))
                up.update(done_files)
                st.setdefault(str(tag), {})["uploaded"] = sorted(up)
                st.setdefault(str(tag), {})["upload_errors"] = err.get("sample", "")
                save_state(st)
                log.warning(f"[upload] 红色警告({err.get('count')}处,重复{len(dups)}个),立即停止上传,进入下一步")
                hit_red = True
                break
            try:
                if "upload/select" not in (page.url or ""):
                    clicked = True
                    break
            except Exception:
                pass
            for nm in ("保存并查看", "Save & View", "Save and View"):
                try:
                    b = page.get_by_role("button", name=re.compile(re.escape(nm)))
                    if b.count() and b.first.is_visible():
                        b.first.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break
            time.sleep(0.4)
        if hit_red:
            return False
        if clicked:
            time.sleep(3)
            err2 = upload_errors(page)
            if err2 and err2.get("count", 0) > 0:
                st = load_state()
                up = set(st.get(str(tag), {}).get("uploaded", []))
                up.update(str(p) for p in batch)
                st.setdefault(str(tag), {})["uploaded"] = sorted(up)
                st.setdefault(str(tag), {})["upload_errors"] = err2.get("sample", "")
                save_state(st)
                log.warning("[upload] 提交后出现红色警告,立即停止上传,进入下一步")
                return False
        log.info(f"第{i//per_batch+1}批 已提交 用时{int(time.time()-t0)}s")
        used += len(batch)
        counter.write_text(f"{today},{used}")
        st = load_state()
        up = set(st.get(str(tag), {}).get("uploaded", []))
        up.update(str(p) for p in batch)
        st.setdefault(str(tag), {})["uploaded"] = sorted(up)
        save_state(st)
        human_delay(1, 2)
    # 上传后核对活动数:不够就把本批从state撤掉,下次可补传
    try:
        time.sleep(8)
        got = count_activities(page)
        want = len(todo)
        if isinstance(got, int) and got >= 0 and got < want:
            log.warning(f"[upload] 活动数 {got} < 本次上传 {want},撤掉本批记录以便补传")
            st = load_state()
            up = set(st.get(str(tag), {}).get("uploaded", []))
            up.difference_update(str(p) for p in todo)
            st.setdefault(str(tag), {})["uploaded"] = sorted(up)
            save_state(st)
    except Exception as e:
        log.warning(f"[upload] 活动数核对失败: {str(e)[:80]}")
    return True

def upload_errors(page):
    """检测上传页的真实错误:只认带 .gpx 的重复/失败行(避免健康提示红图标误判)"""
    js = r"""
    () => {
      var txt = document.body.innerText || '';
      var lines = txt.split('\n').filter(function(l){
        return /\.gpx/i.test(l) && /duplicate|error|invalid|\u5931\u8d25|\u91cd\u590d|\u9519\u8bef/i.test(l);
      });
      var dups = [];
      var re = /(\d{1,2})\.(\d{1,2})\.gpx/g;
      for (var i = 0; i < lines.length; i++) {
        var m;
        while ((m = re.exec(lines[i])) !== null) { dups.push(m[1] + '.' + m[2]); }
      }
      // 红色元素里也只看含 .gpx 的
      var reds = 0;
      var nodes = document.querySelectorAll('div,li,tr,span,p');
      for (var k = 0; k < nodes.length; k++) {
        var e = nodes[k];
        if (e.children.length) continue;
        var t = (e.textContent || '').trim();
        if (!/\.gpx/i.test(t)) continue;
        var s = getComputedStyle(e);
        var bg = (s.backgroundColor || '').replace(/\\s/g, '');
        if (/^rgb\(2[0-9]{2},([0-9]{1,2}),([0-9]{1,2})\)$/.test(bg)) reds++;
      }
      var uniq = [];
      for (var q = 0; q < dups.length; q++) { if (uniq.indexOf(dups[q]) < 0) uniq.push(dups[q]); }
      return {count: lines.length + reds, lines: lines.length, red_elems: reds,
              dup_dates: uniq, sample: (lines[0] || '').slice(0, 90)};
    }
    """
    try:
        return page.evaluate(js)
    except Exception as e:
        return {"count": 0, "dup_dates": [], "err": str(e)[:60]}

def count_activities(page):
    """读我的活动数(去重链接数)"""
    try:
        page.goto("https://www.strava.com/dashboard?feed_type=my_activity", timeout=30000, wait_until="domcontentloaded")
        accept_cookies(page, timeout=3)
        time.sleep(4)
        for _ in range(8):
            try:
                scroll_to_bottom(page)
            except Exception:
                pass
            time.sleep(1)
        return page.evaluate("""() => new Set([...document.querySelectorAll('a[href*="/activities/"]')].map(a=>a.href)).size""")
    except Exception:
        return -1



# ---------------------------------------------------------------- 用户采集
def _cdp_grab(page, quality=80):
    """用 CDP 直接抓一张截图(不等字体/动画)。

    ★★ 2026-09-18 真机实测(这是"采集 0 人"的第二个真凶):
      同一时刻、同一个热力图页面, 逐级放大 8 级各测一次:
        放大级  | 1 | 2 | 3 | 4 | 5    | 6    | 7
        PW截图  |OK |OK |OK |OK |超时45s|超时45s|OK(18.5s)
        CDP抓图 |.5s|.6s|.2s|.1s| 2.3s | 1.3s | 1.8s   ← 从不失败
      Playwright 的 page.screenshot() 会等"字体加载/页面稳定", 这个 canvas 热力图
      页面偶尔会卡住几十秒, 于是 3×12 秒全超时、白等 48 秒还拿不到图
      (实跑日志: "[region] New York 第1..4级 截图失败(未知)")。
      CDP 的 Page.captureScreenshot 直接向渲染进程要一帧, 实测 0.1~2.3 秒, 从不失败。
      所以: 优先 CDP, 失败再退回 Playwright。
    """
    import base64 as _b64
    sess = getattr(page, "_dsh_cdp", None)
    for _attempt in range(2):
        try:
            if sess is None:
                sess = page.context.new_cdp_session(page)
                try:
                    setattr(page, "_dsh_cdp", sess)
                except Exception:
                    pass
            # ★★ 绝对不要用线程池包 sess.send() ★★ (2026-09-19 实测反证后回退)
            #   理由(代理 D 在同一套 Playwright 同步 API 上实测):
            #     同线程调 sess.send  -> SAME-THREAD OK, 拿到 9296 字节
            #     工作线程调 sess.send -> error: Cannot switch to a different thread
            #   即 Playwright 同步 API 的连接是【线程绑定】的, 换线程调会让 CDP 截图
            #   【100% 失败】—— 反而把这条"从不失败"的兜底路径废掉了。
            #   而且 `with ThreadPoolExecutor` 在 result() 超时后, __exit__ 仍会 join
            #   那个卡住的线程, 所谓"硬超时"根本不生效。
            res = sess.send("Page.captureScreenshot",
                            {"format": "jpeg", "quality": int(quality or 80),
                             "fromSurface": True})
            data = _b64.b64decode(res["data"])
            if data:
                return data
        except Exception as e:
            log.warning(f"[markers] CDP 截图失败({_attempt + 1}/2): {str(e)[:50]}")
            try:
                setattr(page, "_dsh_cdp", None)     # 会话坏了就重建
            except Exception:
                pass
            sess = None
    return None


def find_markers(page, min_area=60, max_area=900):
    """截图找地图上的橙色圆形路段标记,返回截图坐标

    ★ 截图会偶发超时(地图瓦片还没加载完 / 页面正忙)。以前只截一次,
      一超时就抛到外层的州循环, 整个州直接 0 产出 —— 实跑出现过。
      现在重试 2 轮(每轮 Playwright 超时后还会走 CDP 兜底), 全失败才放弃这一级。
      ★ 注意: 旧注释写的"重试 3 次"与代码不符 —— 代码在本次改造【之前】
        就已经是 range(2) 了, 是注释一直没跟着改。以 range(2) 为准。

    ★★ 返回值三态(2026-09 真机缺陷修复):
        正常     -> list[(x, y)]   截到了, 列表可能就是 [] = 这一级确实没有标记
        截图失败 -> None           ★ 关键: 绝不是 [] !
      真机实测热力图页面 Page.screenshot 经常 20 秒超时(用 45 秒也超时过)。
      以前失败 return []，上层 `len(mk)` 看到 0 就当成"这个级别没有标记",
      自适应缩放会继续往更高级别放大 -> 放大过头 -> 一个路段都选不出来 -> 采集 0 人。
      所以失败必须返回 None, 让调用点能区分"截到了但没标记"和"根本没截到(未知)"。
      超时 20000 -> 8000(旧注释写的 12000 同样已经过时): 页面常常卡住, 等 20 秒太久
      (#实测 20000/45000 都超时过); 而且紧接着就有 CDP 兜底, 所以单轮最坏等待
      从 20 秒降到 8 秒。真机 0918 有 1198 次 20 秒超时, 这一项本身就是最大的浪费来源。
    """
    raw = None
    for _try in range(2):
        check_stop()
        # ★★ 顺序很重要(真机 00:02 实测): CDP 的 send() 没有超时参数, 页面渲染
        #    卡住时它会【永久阻塞】——那一轮日志停在"第10级", 后面 11 分钟没有任何
        #    输出, 整个采集死在那里(连"停止"都点不动, 因为主线程被卡在调用里)。
        #    Playwright 的 page.screenshot(timeout=) 是【有界】的: 最长等 timeout 就抛。
        try:
            raw = page.screenshot(timeout=8000)
        except Exception as e:
            log.warning(f"[markers] Playwright 截图失败({_try + 1}/2): {str(e)[:60]}")
            raw = _cdp_grab(page)                # 兜底: 快, 且已有 5 秒硬上限
        if raw:
            break
        sleep_or_stop(2.0 + _try * 2)
    if not raw:
        log.warning("[markers] Playwright + CDP 都截不到, 本步跳过")
        return None          # ★ None=截图失败(未知), []=截到了但没有标记
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    arr = np.array(im)
    rch, gch, bch = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (rch > 200) & (gch > 40) & (gch < 140) & (bch < 70)
    mask[:160, :] = False
    mask[:, :200] = False
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.where(mask)
    for (x0, y0) in zip(xs.tolist(), ys.tolist()):
        if visited[y0, x0]:
            continue
        stack = [(x0, y0)]; visited[y0, x0] = True; comp = []
        while stack:
            x, y = stack.pop(); comp.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True; stack.append((nx, ny))
        area = len(comp)
        if not (min_area <= area <= max_area):
            continue
        cxs = [q[0] for q in comp]; cys = [q[1] for q in comp]
        bw = max(cxs) - min(cxs) + 1; bh = max(cys) - min(cys) + 1
        if bw == 0 or bh == 0:
            continue
        if 0.5 <= bw / bh <= 2.0 and area / (bw * bh) >= 0.35:
            out.append((int(sum(cxs) / area), int(sum(cys) / area)))
    return out


def segment_from_popup(page):
    """读地图弹窗里的路段ID"""
    try:
        return page.evaluate(r"""() => {
          const a=[...document.querySelectorAll('a[href*="/segments/"]')]
                    .map(x=>x.getAttribute('href')).find(h=>h&&/\/segments\/\d+/.test(h));
          if(!a) return '';
          const m=a.match(/\/segments\/(\d+)/);
          return m?m[1]:'';
        }""")
    except Exception:
        return ""


def fetch_age_leaderboard(page, seg_id, age="65_69", max_pages=4):
    """调排行榜接口取指定年龄组用户"""
    js = r"""async (args) => {
      const [seg, age, pg] = args;
      const url = 'https://www.strava.com/frontend/segments/' + seg +
                  '/leaderboard?filter_type=age_group&filter_value=' + age +
                  '&gender=overall&page=' + pg;
      const r = await fetch(url, {headers: {'accept':'application/json','x-requested-with':'XMLHttpRequest'}});
      const t = await r.text();
      let j=null; try { j = JSON.parse(t); } catch(e) {}
      if (!j) return {ok:false, status:r.status};
      return {ok:true, total: j.totalCount||0,
              rows: (j.leaderboard||[]).map(x=>({rank:x.rank, name:x.displayName||'',
                                                 aid:x.athleteIdStr||String(x.athleteId||'')}))};
    }"""
    rows, total = [], 0
    for pg in range(1, max_pages + 1):
        try:
            _t_lb = net_ready()
            res = page.evaluate(js, [seg_id, age, pg])
            net_elapsed(_t_lb, "api")
        except Exception as e:
            log.info(f"    [collect] api err: {str(e)[:60]}")
            break
        if not res or not res.get("ok"):
            break
        total = res.get("total") or total
        part = res.get("rows") or []
        rows += part
        if not part or len(rows) >= total:
            break
        time.sleep(random.uniform(0.8, 1.6))
    return total, rows


def collect_users(page, city, age="65_69", max_segments=20, task=None):
    """在已登录页面采集:地图搜城市 -> 点标记取路段 -> 取年龄组用户 -> 存链接"""
    # ★ 任务上下文(桌面版硬需求): 没传就自己建一个, 让本函数单独调用时也有
    #   独立带时间戳的成果文件; 传了就跟随界面那一次任务(共享 tid)。
    _auto_task = task is None
    if _auto_task:
        task = new_task_ctx(mode="cli-collect")
    # ★ 明细必须带后缀: 传 ""(空) 会让明细文件占掉 collected_users_<tid>.txt
    #   这个名字, 把任务成品挤成 _2。这条 CLI 通道没有"号"的概念, 就用 cli 当后缀。
    _sub = new_account_ctx(task, "cli")
    seen = {}
    if COLLECT_SEEN.exists():
        try:
            seen = json.loads(COLLECT_SEEN.read_text(encoding="utf-8"))
        except Exception as e:
            # ★ 2.13: 坏文件不许静默当空 —— 静默等于"全部重采"
            log.error(f"[seen] 去重记录损坏/读取失败(本次按空记录继续): {str(e)[:60]}")
            seen = {}
    collected = []
    try:
        page.goto("https://www.strava.com/maps", timeout=60000, wait_until="domcontentloaded")
        accept_cookies(page, timeout=3)
        time.sleep(6)
        # 首次进入会显示 "The Global Heatmap" 介绍页,需要点 "See the heat"
        for _try in range(3):
            try:
                hit = False
                for nm in ("See the heat", "See the Heat", "查看热力图", "查看热图"):
                    try:
                        b = page.get_by_role("button", name=re.compile(re.escape(nm), re.I))
                        if b.count() and b.first.is_visible():
                            b.first.click()
                            log.info("[collect] 已点 See the heat")
                            hit = True
                            break
                    except Exception:
                        continue
                if not hit:
                    try:
                        b = page.locator("button:has-text('See the heat'), a:has-text('See the heat')").first
                        if b.count() and b.is_visible():
                            b.click()
                            log.info("[collect] 已点 See the heat(兜底)")
                            hit = True
                    except Exception:
                        pass
                if hit:
                    time.sleep(6)
                    break
                time.sleep(2)
            except Exception:
                time.sleep(2)
        # 等地图加载
        time.sleep(4)
        try:
            box = page.locator("input[placeholder*='Search for a location']").first
            box.click(); time.sleep(1)
            for ch in city:
                page.keyboard.type(ch, delay=90)
            time.sleep(4)
            hit = False
            for t in (city, city.split(",")[0]):
                try:
                    loc = page.get_by_text(t, exact=True).first
                    if loc.count() and loc.is_visible():
                        loc.click(); hit = True; break
                except Exception:
                    continue
            log.info(f"[collect] city {city}: {'ok' if hit else 'suggest-miss'}")
            time.sleep(10)
        except Exception as e:
            log.info(f"[collect] search err: {str(e)[:80]}")

        dpr = page.evaluate("() => window.devicePixelRatio") or 1
        # 打开 Segments 图层(不点就不显示路段)
        seg_on = False
        for _try in range(3):
            try:
                b = page.get_by_role("button", name=re.compile(r"^Segments$", re.I))
                if b.count() and b.first.is_visible():
                    b.first.click()
                    log.info("[collect] 已点 Segments 图层")
                    time.sleep(4)
                    # 弹出筛选面板 -> 点 Done
                    d = page.get_by_role("button", name=re.compile(r"^Done$", re.I))
                    if d.count() and d.first.is_visible():
                        d.first.click()
                        log.info("[collect] 已点 Done")
                        time.sleep(3)
                    seg_on = True
                    break
                b2 = page.locator("button:has-text('Segments')").first
                if b2.count() and b2.is_visible():
                    b2.click()
                    log.info("[collect] 已点 Segments(兜底)")
                    time.sleep(4)
                    d = page.get_by_role("button", name=re.compile(r"^Done$", re.I))
                    if d.count() and d.first.is_visible():
                        d.first.click()
                        time.sleep(3)
                    seg_on = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not seg_on:
            log.warning("[collect] 没点到 Segments 按钮")
        # 打开热力图图层
        try:
            h = page.get_by_role("button", name=re.compile(r"^Heatmaps?", re.I))
            if h.count() and h.first.is_visible():
                h.first.click()
                log.info("[collect] 已点 Heatmaps")
                time.sleep(3)
        except Exception:
            pass
        # 放大到能看见路段标记
        try:
            page.mouse.move(700, 400)
            for _ in range(6):
                page.mouse.wheel(0, -500)
                time.sleep(1.5)
        except Exception:
            pass
        time.sleep(6)

        seg_ids, tried = [], set()
        for rnd in range(10):
            mk = find_markers(page)
            # ★ find_markers 改为三态返回后: None=截图失败(未知), []=截到了但没标记。
            #   以前直接 len(mk), None 会 TypeError; 更糟的是把"未知"当成"0 个标记"。
            if mk is None:
                log.warning(f"[collect] round{rnd+1}: 截图失败(未知), 本轮跳过")
                mk = []
            else:
                log.info(f"[collect] round{rnd+1}: markers={len(mk)}")
            new_hit = 0
            for (sx, sy) in mk:
                if len(seg_ids) >= max_segments:
                    break
                key = (sx // 20, sy // 20)
                if key in tried:
                    continue
                tried.add(key)
                try:
                    page.mouse.click(sx / dpr, sy / dpr)
                    time.sleep(2)
                    sid = segment_from_popup(page)
                    if sid and sid not in seg_ids:
                        seg_ids.append(sid); new_hit += 1
                        log.info(f"[collect]   segment {sid} ({len(seg_ids)})")
                except Exception:
                    continue
            if len(seg_ids) >= max_segments:
                break
            # 换方向平移,探索新区域
            moves = grid_pan_targets(PAN_ROUNDS)   # ★ 方案A: 蛇形网格扫描
            try:
                dx, dy = moves[rnd % len(moves)]
                page.mouse.move(700, 400)
                page.mouse.down(); page.mouse.move(dx, dy, steps=10); page.mouse.up()
                time.sleep(3)
            except Exception:
                pass
            if new_hit == 0 and rnd >= 5:
                break

        log.info(f"[collect] {len(seg_ids)} segments, age={age}")
        for i, sid in enumerate(seg_ids, 1):
            # ★ 整段以前没有任何停止检查点, 一个账号要跑好几分钟,
            #   用户点"停止"后毫无反应。每个路段开始前查一次。
            check_stop()
            total, rows = fetch_age_leaderboard(page, sid, age)
            log.info(f"[collect] [{i}/{len(seg_ids)}] seg{sid}: total={total} got={len(rows)}")
            for r2 in rows:
                aid = r2.get("aid")
                if not aid or aid in seen:
                    continue
                seen[aid] = "pass"
                collected.append({"aid": aid, "name": r2.get("name", ""),
                                  "url": f"https://www.strava.com/athletes/{aid}"})
            time.sleep(random.uniform(1, 2))
    except Exception as e:
        log.info(f"[collect] err: {str(e)[:100]}")

    if collected:
        for c in collected:
            append_task_url(_sub, c["url"])      # ★ 只保存链接(判重+落明细文件)
        # ★ 改用 save_seen: 临时文件 + os.replace 原子写。
        #   以前直接 write_text, 和 collect_regions 并发写同一个文件会互相
        #   覆盖, 写失败还被 pass 吞掉 -> 下次全量重采。
        save_seen(seen)
        log.info(f"[collect] +{len(collected)} users -> "
                 f"{_sub.get('path').name if _sub.get('path') else COLLECT_OUT.name}")
    else:
        log.info("[collect] no new users")
    # ★ 自动建的任务必须自己收尾: 否则新增链接只会留在明细文件里, 永远不进
    #   历史总表 —— 而 _从中心捞回.py / _真机实跑.py / _验收_200.py 读的正是总表。
    if _auto_task:
        try:
            finalize_task(task)
        except Exception as _e:
            log.warning(f"[task] 任务汇总失败: {str(_e)[:60]}")
    return collected


def profile_activity_count(page):
    """读控制面板的 Activities 数量(以该页面为准)"""
    js = r"""() => {
        var els = [...document.querySelectorAll('*')].filter(e => e.children.length === 0 && /^Activities$/.test((e.textContent||'').trim()));
        for (var i = 0; i < els.length; i++) {
            var box = els[i].closest('li,div');
            if (!box) continue;
            var m = (box.textContent||'').match(/([\d,]+)/);
            if (m) return parseInt(m[1].replace(/,/g,''));
        }
        var t = document.body.innerText || '';
        var m2 = t.match(/Activities\s*\|?\s*([\d,]+)/);
        return m2 ? parseInt(m2[1].replace(/,/g,'')) : -1;
    }"""
    for _ in range(2):
        try:
            goto_retry(page, "https://www.strava.com/dashboard")
            accept_cookies(page, timeout=3)
            wait_text(page,
                      "/Activities\\s*\\|?\\s*([\\d,]+)/.test(document.body.innerText || '')",
                      timeout=4.0, key="activities")
            n = page.evaluate(js)
            if isinstance(n, int) and n >= 0:
                return n
        except UserStopped:
            raise            # ★ 2.7: 停止信号必须继续往上抛, 不能被当成"读不到活动数"
        except Exception as e:
            log.warning(f"[activities] count err: {str(e)[:60]}")
            time.sleep(2)
    return -1


def has_custom_avatar(page):
    """是否已有自定义头像(非谷歌默认)"""
    for _ in range(3):
        try:
            goto_retry(page, "https://www.strava.com/settings/profile")
            accept_cookies(page, timeout=3)
            n = wait_text(page,
                          "[...document.querySelectorAll('img')].map(i=>i.src||'')"
                          ".filter(s=>/pictures\\/athletes/.test(s)).length",
                          timeout=3.0, key="avatar") or 0
            return bool(n)
        except UserStopped:
            raise            # ★ 2.7: 同上 —— 停止不能变成"没有头像"
        except Exception as e:
            log.warning(f"[avatar] check err: {str(e)[:60]}")
            time.sleep(3)
    return False


# 会员标记的判定表达式(单表达式, 给 wait_text 包成 () => (...) 用)
#   ① img alt="Subscriber" —— 探针实证: 只有 /settings/profile 上有这个徽章,
#      /dashboard 上没有。所以判会员【必须停在设置页】, 别在别处查。
#   ② "Subscriber since <日期>" —— 探针在同一页读到的会员专属文案, 作为副判据
_PREMIUM_JS = (
    "[...document.querySelectorAll('img')].some(i => i.alt === 'Subscriber')"
    " || /Subscriber\\s+since/i.test(document.body.innerText || '')"
)


def is_premium(page):
    """是否 Strava 会员。返回 True / False / None(读不到)

    ★★ 2026-09-19 改成三态 —— 用户实测: 3 号明明是会员却显示"否" ★★
      现场: 十几个号【全部】判成"非会员", 连活动数读得好好的号也是"否";
            而日志里一条 [premium] check err 都没有。
      探针实证(_探针_会员.py 附在项目里):
            /settings/profile 上 img[alt='Subscriber'] 确实存在,
            "Subscriber since 9/15/26", 同一个函数单独跑返回 True。
      所以判据没错, 错的是【语义】——
            旧实现只有 True/False 两个出口:
              "等到了徽章"        -> True
              "等了9秒没等到"     -> False   ← 这里把
              "3次导航全抛异常"   -> False      【慢加载 / 页面被并发挤住 /
                                                 导航被打断】也写成了"非会员"
            上级一看"非会员"就"跳过采集" -> 这个号一个都不采, 而且是【静默】的。
            (代码里那句"44% 的 prem 列是假的"说的就是这个坑。)
      现在: 先确认【真的站在设置页上、而且页面还活着】, 才敢下"非会员"的结论;
            站不到就返回 None, 上级据此不下结论、不覆盖、不跳过。

    ★ 另一个坑(探针实证, 千万别踩): class 里带 premium 的
      <li class="premium opt-group"> 是【侧边导航的会员功能分组】,
      所有账号(含免费号)都有, 那是推销入口。用它判会员必然全判成"是"。
      真正只有会员才有的标记是:
        ① <img alt="Subscriber" src="badges_subscription_...">  ← 主判据
        ② 正文 "Subscriber since <日期>"                        ← 副判据
    """
    for attempt in range(3):
        try:
            goto_retry(page, "https://www.strava.com/settings/profile")
            accept_cookies(page, timeout=3)
            # 轮询等会员标记(最多9秒):不做整页序列化,直接在 DOM 里查。
            # 主判据(徽章图片) + 副判据("Subscriber since")一起等, 命中任一即可。
            if wait_text(page, _PREMIUM_JS, timeout=9.0,
                         key="premium", on_poll=check_stop):
                return True

            # ---- 没等到: 先证明"我们确实站在设置页上"再下结论 ----
            # 否则就只是"没读到", 绝不能写成"非会员"。
            if not page_alive(page):
                log.warning("[premium] 页面/浏览器已关闭 -> 会员状态【未知】"
                            "(不是非会员)")
                return None
            try:
                _cur = page.url or ""
            except Exception:
                _cur = ""
            if "/settings/profile" not in _cur:
                log.warning(f"[premium] 没停在设置页(现在 {_cur[:70]}) -> 本次不算数, 重试")
                time.sleep(2)
                continue
            # 站对了位置、页面活着、等满 9 秒仍无任何会员标记 -> 这才敢说"不是会员"
            log.info("[premium] 设置页已就绪且无任何会员标记 -> 判定非会员")
            return False
        except UserStopped:
            # ★ 2.7: 现状是"点一次停止就把在飞的号判成非会员并永久写进结果",
            #   44% 的 prem 列是假的 —— 停止必须继续往上抛
            raise
        except Exception as e:
            log.warning(f"[premium] check err: {str(e)[:60]}")
            time.sleep(3)
    # ★ 三次都没能站到设置页 -> 未知。绝不谎报"非会员"。
    log.warning("[premium] 3 次都没能判定 -> 会员状态【未知】(不是非会员)")
    return None


def page_alive(page):
    """页面/浏览器还活着吗?

    ★ 真机教训(2026-09-18 23:52 实测): 浏览器被关掉之后, is_premium() 会一路
      抛异常、3 次重试后**返回 False** —— 于是【连接断开】被误判成【非会员】:
      日志写 "[skip] 3 非会员,跳过采集", 表格显示"非会员", 实际采集一个都没跑,
      而且看不出真正原因(那次是上一个进程刚好把这个环境关掉了)。
      所以凡是要下"非会员"结论的地方, 必须再确认一次页面还活着。
    """
    try:
        if page is None or page.is_closed():
            return False
        page.evaluate("() => 1")
        return True
    except Exception:
        return False


# 绝不是人名的字符串(页面标题/导航文字/表单标签) —— 读名字时用来兜底过滤
# 绝不是人名的字符串(页面标题/导航文字/表单标签) —— 读名字时用来兜底过滤
_BAD_NAME = {
    "", "my profile", "profile", "settings", "strava", "dashboard",
    "you", "athlete", "edit", "home", "log out", "logout", "account",
    "my account", "feed", "training", "maps", "challenges", "upload",
    # 设置页上的表单标签 —— 名字恰好跟在 "Name" 后面, 必须把标签本身挡掉
    "name", "first name", "last name", "full name", "birthday", "gender",
    "weight", "location", "email", "current photo", "upload a photo",
    "remove", "units", "date format", "preferred units", "my gear",
    "privacy controls", "display preferences", "email notifications",
    "data permissions", "my performance", "partner integrations",
    "my badges", "give a gift", "primary club", "vanity url", "profile bio",
}


def read_settings_info(page, timeout=6.0):
    """读 /settings/profile 上的**真实姓名 + 真实所在地**

    ★ 为什么要它: 表格里"名字/城市"这两列以前是拿"本次要设置的目标值"填的。
      但账号如果是"已有头像跳过", set_profile 根本没执行, 填进去的就不是
      账号上真正的值。实测(2026-09-18):
        3 号  目标 'Olivia Huang'/Chicago -> 真实 'Ruby Koo' / North Chicago, Illinois
        38 号 目标 'Daisy Zhao'/Chicago   -> 真实 'Daisy Zhao' / Los Angeles, California
      城市那列原来一律填 Chicago, 而 38 号其实是洛杉矶 —— 也是假的。
      is_premium() 结束时页面正好停在 /settings/profile,
      所以这里读一次不用额外跳转, 只多一条 JS, 换来的是真实值。

    ★ 三个坑(都实测踩过):
      ① 会员账号: is_premium() 看到 Subscriber 徽章就立刻返回, 这时设置页
         的表单还没渲染完 -> 输入框读不到 -> 会填成 'My Profile'(页面标题)。
         所以这里要轮询等输入框出现(最多 timeout 秒)。
      ② 绝不能把页面标题/导航文字/表单标签当名字: 用 _BAD_NAME 黑名单挡掉。
      ③ 有两种版式: 多数账号有 <input id="athlete_first_name">, 但有些账号
         (实测 3 号)整页没有姓名输入框, 名字是纯文本跟在 "Name" 后面;
         所在地同理跟在 "Location" 后面一行(再下一行是时区, 要跳过)。
    """
    js = r"""() => {
        var g = function(sels) {
            for (var i = 0; i < sels.length; i++) {
                var e = document.querySelector(sels[i]);
                if (e && typeof e.value === 'string' && e.value.trim())
                    return e.value.trim();
            }
            return '';
        };
        var t = (document.body.innerText || '').split('\n')
                 .map(function(s) { return s.trim(); });
        // 所在地: 跟在 "Location"/"所在地" 后面一行; 时区行(America/Chicago)
        // 不是地名要跳过; 末尾国名去掉, 只留 "城市, 州"
        var loc = '';
        for (var i = 0; i < t.length - 1; i++) {
            if (!/^(Location|所在地)$/i.test(t[i])) continue;
            for (var j = i + 1; j < Math.min(i + 3, t.length); j++) {
                if (!t[j]) continue;
                if (/^[A-Za-z]+\/[A-Za-z_]+$/.test(t[j])) continue;
                loc = t[j];
                break;
            }
            if (loc) break;
        }
        loc = loc.replace(/\s+(United States|United Kingdom|USA|US|Canada|Australia)\s*$/i, '').trim();
        // 姓名版式一: 输入框(最权威)
        var f = g(['#athlete_first_name', 'input[name="first_name"]',
                   'input[id*="first_name"]', 'input[data-testid*="first"]']);
        var l = g(['#athlete_last_name', 'input[name="last_name"]',
                   'input[id*="last_name"]', 'input[data-testid*="last"]']);
        var n = (f + ' ' + l).replace(/\s+/g, ' ').trim();
        if (n) return {n: n, src: 'input', last: l, loc: loc};
        // 姓名版式二: 纯文本, 紧跟在 "Name"/"First Name" 后面
        for (var k = 0; k < t.length - 1; k++) {
            if (t[k] === 'Name' || t[k] === 'First Name') {
                for (var m = k + 1; m < Math.min(k + 3, t.length); m++) {
                    if (t[m]) return {n: t[m], src: 'label', last: '', loc: loc};
                }
            }
        }
        // 姓名版式三: 头像 alt
        var img = document.querySelector('img[alt][src*="pictures/athletes"]');
        if (img && img.alt && img.alt.trim())
            return {n: img.alt.trim(), src: 'alt', last: '', loc: loc};
        return {n: '', src: 'none', last: '', loc: loc};
    }"""
    t0 = time.time()
    name, loc, seen = "", "", None
    # ★ "名"和"姓"两个输入框渲染有先后: 读太早只会拿到名(实测 38 号先读到
    #   'Daisy', 其实人家叫 'Daisy Zhao')。所以只有名、没姓时再多等 GRACE 秒,
    #   等姓出现; 名+姓都齐了立刻返回。
    GRACE = 1.5
    while True:
        r = {}
        try:
            _r = page.evaluate(js)
            if isinstance(_r, dict):
                r = _r
        except Exception:
            r = {}
        nm = str(r.get("n") or "").strip()[:80]
        src = str(r.get("src") or "none")
        last = str(r.get("last") or "").strip()
        lc = str(r.get("loc") or "").strip()[:80]
        # 输入框读到的无条件可信; 文本/头像读到的要过黑名单, 免得把
        # "My Profile"/"Birthday"/"Weight" 这些标签当成名字
        ok = bool(nm) and (src == "input" or (
            2 <= len(nm) <= 60 and nm.lower() not in _BAD_NAME
            and any(c.isalpha() for c in nm)))
        if ok and not name:
            name, seen = nm, time.time()
            if lc:
                loc = lc
        elif lc and not loc:
            loc = lc                      # 名字已定, 补上后到的所在地
        if name and src == "input" and last:
            break                         # 名+姓都齐了, 权威值
        if seen is not None and time.time() - seen >= GRACE:
            break
        if time.time() - t0 >= timeout:
            break
        time.sleep(0.3)
    return {"name": name, "location": loc}


def read_settings_name(page, timeout=6.0):
    """只要名字(兼容包装, 内部走 read_settings_info)"""
    return read_settings_info(page, timeout).get("name", "")


def run_one(win, email=None, password=None, name=None, location=None, avatar=None,
            gpx_dir=None, check_only=False, recheck=False, try_google=True,
            manual_wait=300, auto_close=None,
            per_batch=None, daily_cap=None, task=None):
    # ADS 的状态键加前缀,避免和比特派同名窗口冲突(win 本身保持不变)
    # O4: 加机器前缀 —— 20 台机器各跑各的, 不互相覆盖进度
    # 前缀优先取环境变量 STRAVA_WORKER(每台设成不同值, 如 PC01..PC20)
    state_key = task_state_key(win)
    _t0 = time.time()   # 仅用于日志里报单账号耗时
    files = sort_gpx(gpx_dir) if gpx_dir else []
    if not check_only and not recheck:
        todo = pending_todo(state_key, name, location, avatar, files,
                            daily_cap=daily_cap)
        if not todo:
            log.info(f"[skip] {win} 已全部完成")
            return "skipped"
        log.info(f"[todo] {win} 待做: {','.join(todo)}")
    prof = ads_find(profile_no=str(win).lstrip("_"))
    if not prof:
        log.warning(f"[ads] 找不到环境 {win}")
        return {"win": win, "login": False, "steps": [], "error": "no profile"}
    uid = prof.get("user_id")
    ws = ads_open(uid)
    reset_goto_guard(win)   # 每个账号重置去重记忆
    info = {"ws": ws, "name": prof.get("name"), "seq": prof.get("serial_number")}
    result = {"win": win, "login": False, "steps": []}
    _real_name = ""     # ★ 从 /settings/profile 读到的真实姓名(见 read_settings_info)
    _real_loc = ""      # ★ 同上, 真实所在地
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(info["ws"])
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # stealth 基础(比特本身已处理指纹,这里补webdriver)
        try:
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        except Exception:
            pass
        # 页面整理:优先保留非控制台页;若只有控制台页就复用它(绝不关最后一页)
        page = None
        for _ in range(10):
            try:
                pages = list(ctx.pages)
            except Exception:
                pages = []
            if not pages:
                time.sleep(1)
                continue
            work = []
            for pg in pages:
                try:
                    u = pg.url or ""
                except Exception:
                    continue
                if "console.bitbrowser" not in u:
                    work.append(pg)
            if work:
                page = work[0]
                # 关掉多余的控制台页
                for pg in pages:
                    try:
                        if "console.bitbrowser" in (pg.url or "") and pg is not page:
                            pg.close()
                    except Exception:
                        pass
                break
            # 只有控制台页:复用它,不关
            page = pages[0]
            try:
                page.goto("https://www.strava.com/", timeout=30000, wait_until="domcontentloaded")
                accept_cookies(page, timeout=4)
            except Exception:
                pass
            break
        if page is None:
            try:
                page = ctx.new_page()
            except Exception as e:
                log.warning(f"[page] 无法创建页面: {str(e)[:80]}")
                return result
        try:
            page.set_default_timeout(8000)
        except Exception:
            pass
        # 确认page可用,不行就重新拿
        def ensure_page():
            nonlocal page
            try:
                _ = page.url
                return page
            except Exception:
                try:
                    for pg in list(ctx.pages):
                        u = pg.url or ""
                        if "console.bitbrowser" not in u:
                            page = pg
                            return page
                except Exception:
                    pass
                try:
                    page = ctx.new_page()
                except Exception:
                    pass
                return page
        def repair():
            nonlocal page
            try:
                _ = page.url
                return page
            except Exception:
                log.warning("[repair] 页面失效,重新获取")
                try:
                    for pg in list(ctx.pages):
                        try:
                            u = pg.url or ""
                        except Exception:
                            continue
                        if "console.bitbrowser" not in u:
                            page = pg
                            return page
                except Exception:
                    pass
                try:
                    page = ctx.new_page()
                except Exception:
                    pass
                return page

        logged = False
        page = ensure_page()
        try:
            logged = is_logged_in(page)
        except Exception as e:
            log.warning(f"登录检测异常: {str(e)[:100]}")
            page = ensure_page()
        log.info(f"[status] {win} 登录={logged}")
        result["login"] = logged
        if check_only:
            return result
        if not logged:
            # ★ 以前没判断 try_google, 于是 --no-google 和 config 里的
            #   try_google_auto 完全失效, 关不掉自动谷歌登录。
            if try_google and email and password:
                try:
                    if google_login(page, email, password):
                        logged = True
                except Exception:
                    logged = False
            if not logged and manual_wait:
                logged = wait_manual_login(page, timeout=manual_wait)
            if not logged:
                log.warning(f"{win} 未登录,跳过")
                result["steps"].append("未登录")
                return result
            # ★ 自动谷歌登录 / 手动登录成功之后必须回写 result。
            #   以前这里只改了局部变量 logged, result["login"] 还停在上面
            #   写的 False —— 于是"靠自动登录进来的账号"在表格里一律显示
            #   「登录=否」。实测 52 号: 谷歌登录返回 True、后面的资料/采集
            result["login"] = True
            log.info(f"[status] {win} 登录=True (自动登录成功)")
        # ★ 必须用 state_key, 不能再用 str(win) —— 上面 mark_step 全写进
        #   state_key(ads_N), 这里却读 N, 导致"已完成"判断永远读不到,
        #   每次重跑都重设隐私/单位, 而 pending_todo 那边又说已完成。
        st = {} if recheck else load_state().get(state_key, {})
        # onboarding(新号会填名字/生日/性别)
        is_new_account = False
        if "onboarding" in (page.url or ""):
            is_new_account = bool(do_onboarding(page, name or "Emily Chen"))
            if is_new_account:
                mark_step(state_key, "is_new", True)
            result["steps"].append(f"onboarding({'新号' if is_new_account else '已过'})")
        # 之前判定过新号(弹窗填过)也算新号
        if not is_new_account and st.get("is_new") is True:
            is_new_account = True
        # 头像检测:已有头像且不是新号 -> 跳过设置类任务
        page = repair()
        skip_setup = has_custom_avatar(page) and not is_new_account
        if skip_setup:
            log.info(f"[skip] {win} 已有头像(非新号),跳过 资料/性别/隐私/单位/上传")
            result["steps"].append("已有头像跳过")
        elif is_new_account:
            log.info(f"[new] {win} 判定为新号,照常做资料+上传")
        # 资料
        nm = None if (name and st.get("name") == name) else name
        lc = None if (location and st.get("location") == location) else location
        av = None if (avatar and st.get("avatar") == str(avatar)) else avatar
        # 位置判断:已是芝加哥/洛杉矶 -> 资料判定成功,不再改
        # ★★ 2026-09-24: 位置【不再受 skip_setup 管】★★
        #   skip_setup = 已有头像 且 非新号。老号只要传过一次头像, 这一段就
        #   整段跳过 —— 于是"位置写错了也永远修不回来"(实测 8 个号卡在
        #   墨西哥 Bahía de los Ángeles / Lake Los Angeles, 重跑几次都不动)。
        #   和下面 隐私 / 单位 是同一个坑, 那两处早解开了, 位置漏了。
        if lc:
            page = repair()
            try:
                cur_loc = current_location(page)
                if location_ok(cur_loc):
                    log.info(f"[skip] {win} 位置已是目标城市,资料判定成功: {cur_loc[:50]}")
                    mark_step(state_key, "location", lc)
                    lc = None
            except Exception as e:
                log.warning(f"[location] 判断异常: {str(e)[:60]}")
        check_stop()
        # 名字/头像仍然尊重 skip_setup(别覆盖老号已有的), 位置不受它管
        if lc or (not skip_setup and (nm or av)):
            page = repair()
            if set_profile(page, nm, lc, av):
                if nm: mark_step(state_key, "name", nm)
                if lc: mark_step(state_key, "location", lc)
                if av: mark_step(state_key, "avatar", str(av))
                result["steps"].append("资料")
        check_stop()
        if not skip_setup and st.get("gender") != "woman":
            page = repair()
            try:
                if set_gender(page, "woman"):
                    mark_step(state_key, "gender", "woman")
                    result["steps"].append("性别")
            except Exception as e:
                log.warning(f"性别步骤异常: {str(e)[:100]}")
        check_stop()
        page = repair()
        # ★ 2026-09-19 用户要求: 老号(已有头像)也要补做隐私 —— 所以这一步
        #   【不再受 skip_setup 管】。以前老号整段隐私被跳过, 结果"隐私地图"
        #   (default-activity-map-visibility, 地图全隐藏)从来没补上过。
        #   set_privacy 内部本来就是"已是目标状态就跳过"(只多一次页面读取),
        if st.get("privacy") is not True:
            if set_privacy(page, set_profile_visibility=False):
                result["priv"] = "已设置"           # ★ 回填给界面
                mark_step(state_key, "privacy", True)
                result["steps"].append("隐私")
        check_stop()
        page = repair()
        if not skip_setup and st.get("units") != "feet":
            if set_units(page):
                mark_step(state_key, "units", "feet")
                result["steps"].append("单位")
        # 活动数为0 -> 也要上传
        upload_needed = is_new_account
        if not upload_needed and files:
            page = repair()
            try:
                cnt = profile_activity_count(page)
                result["acts"] = str(cnt)          # ★ 回填给界面
                if cnt == 0:
                    upload_needed = True
                    log.info(f"[upload] {win} 活动数为0,需要上传轨迹")
                elif cnt > 0:
                    log.info(f"[upload] {win} 活动数={cnt},跳过上传")
            except Exception as e:
                log.warning(f"[upload] 活动数检查异常: {str(e)[:60]}")
        check_stop()
        page = repair()
        # ★★ 2026-09-22: 这一步【不再受 skip_setup 管】(和上面隐私那步同一个坑) ★★
        #   原来那个判断条件里还串着 skip_setup, 而 skip_setup = 有头像 且
        #   不是新号 —— 也就是【凡是已经设过的老号, 整段上传都被跳过】,
        #   界面上选「仅上传轨迹」照样什么都不传。
        #   要不要传, upload_needed 上面已经判得清清楚楚(新号 / 活动数为0),
        #   这里只需要照做。
        if files and upload_needed:
            if not upload_gpx(page, files, tag=state_key,
                              per_batch=per_batch, daily_cap=daily_cap):
                log.warning(f"[upload] {win} 轨迹未全部上传成功(见上方日志)")
            result["steps"].append("轨迹")

        # ★★ 2026-09-22 用户要求: 「▶ 开始任务」只做 注册/改资料/传轨迹, 【不采集】★★
        #   采集只归「◎ 只采集」那个按钮 —— 它走 collect_one(), 跟这里没关系。
        #   这一段原来在 collect_enabled 打开时会顺手采一轮, 于是点"开始任务"
        #   也会采, 和用户预期不符(make_claim_client / collect_regions 整段删了)。
        #   ★ 但【会员状态】和【真实姓名/所在地】必须留着:
        #     表格里"会员 / 姓名 / 城市"三列靠它回填, 而且 is_premium() 结束时
        #     页面正停在 /settings/profile, 顺手 read_settings_info 是零额外跳转。
        check_stop()
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

    # 任务完成自动关闭浏览器(用户停止时也关)
    # ★ auto_close 由调用方(界面)传进来。以前这里只读 config.json 的
    #   CFG["auto_close"], 界面上的「完成关浏览器」勾选框根本传不到,
    #   于是勾了也不关。传 None 时回退 CFG, 命令行行为和以前一致。
    try:
        _st2 = dict(st or {})
        try:
            _st2.update(load_state().get(state_key, {}) or {})
        except Exception:
            pass
        _nm = (str(_real_name or "").strip()
               or str(_st2.get("name") or "").strip())
        if not _nm and not skip_setup:
            _nm = str(nm or "").strip()      # 本次确实跑过资料步骤才算数
        if _nm:
            result["name"] = _nm
        _c = (str(_real_loc or "").strip()
              or str(_st2.get("location") or "").strip()
              or str(lc or location or "").strip())
        if _c:
            result["city"] = _c
        result.setdefault("acts", "")
        result.setdefault("prem", "")
        result.setdefault("priv", "")
    except Exception:
        pass

    _ac = CFG.get("auto_close", True) if auto_close is None else bool(auto_close)
    if _ac or STOP_EVENT.is_set():
        ads_close(uid)
    log.info(f"[done] {win} {result} 耗时{time.time() - _t0:.0f}秒")
    return result

args_global = None

def main():
    global args_global
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="")
    ap.add_argument("--batch", action="store_true", help="按config.json的windows列表批量")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--no-google", action="store_true", help="不尝试自动谷歌登录")
    ap.add_argument("--manual-wait", type=int, default=None)
    ap.add_argument("--foreground", action="store_true", help="前台运行")
    ap.add_argument("--collect", action="store_true", help="只跑用户采集")
    ap.add_argument("--city", default="Los Angeles, CA", help="采集城市")
    ap.add_argument("--age", default="65_69", help="年龄组 65_69/55_64/70_74/75_plus")
    ap.add_argument("--max-segments", type=int, default=20, help="最多采集多少个路段")
    ap.add_argument("--profile-no", default="", help="AdsPower 环境编号,如 3")
    ap.add_argument("--from", dest="seq_from", type=int, default=0, help="起始编号,如 1")
    ap.add_argument("--to", dest="seq_to", type=int, default=0, help="结束编号,如 50")
    args = ap.parse_args()

    if getattr(args, "collect", False):
        prof = None
        act = ads_active()
        if act:
            prof = act[0]
        if not prof:
            prof = ads_find(profile_no=args.profile_no or None)
        if not prof:
            log.warning("没有可用 AdsPower 环境")
            return
        uid = prof.get("user_id")
        ws = (prof.get("ws") or {}).get("puppeteer") or ads_open(uid)
        with sync_playwright() as _p:
            _b = _p.chromium.connect_over_cdp(ws)
            _ctx = _b.contexts[0]
            _pg = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
            collect_users(_pg, args.city, args.age, args.max_segments)
        if CFG.get("auto_close", True):
            ads_close(uid)
        return

    windows = [args.window] if args.window else (CFG.get("windows") or [])
    # 编号范围:--from 1 --to 50 (或用config的windows)
    if args.seq_from or args.seq_to:
        a = args.seq_from or 1
        b = args.seq_to or 9999
        if b < a:
            a, b = b, a
        windows = [f"_{i}" for i in range(a, b + 1)]
        log.info(f"[range] 编号 {a}~{b} 共{len(windows)}个")
    if not windows:
        print("请用 --from 1 --to 50 指定编号范围,或在config.json的windows里填窗口名")
        return
    # 账号来源:accounts.json(GUI里每行手填) > windows.csv > 账号TXT(兼容)
    acc_json = {}
    p_acc = ROOT / "accounts.json"
    if not p_acc.exists() and (ROOT.parent / "配置" / "accounts.json").exists():
        p_acc = ROOT.parent / "配置" / "accounts.json"
    if p_acc.exists():
        try:
            acc_json = json.loads(p_acc.read_text(encoding="utf-8"))
            log.info(f"[accounts] accounts.json 载入 {len(acc_json)} 个窗口账号")
        except Exception as e:
            log.warning(f"accounts.json 解析失败: {e}")
    creds = {}
    if CFG.get("accounts_file"):
        try:
            for a in parse_accounts_txt(CFG["accounts_file"]):
                creds[a["email"].lower()] = (a["email"], a["password"])
            log.info(f"[accounts] TXT文档{len(creds)}个账号(备用)")
        except Exception as e:
            log.warning(f"账号文档解析失败: {e}")
    rows = {}
    if CFG.get("windows_csv") and not Path(CFG["windows_csv"]).exists():
        _alt = ROOT / "配置" / Path(CFG["windows_csv"]).name
        if _alt.exists():
            CFG["windows_csv"] = str(_alt)
    if CFG.get("windows_csv") and Path(CFG["windows_csv"]).exists():
        for r in csv.DictReader(open(CFG["windows_csv"], encoding="utf-8-sig")):
            rows[r["window"]] = r
    manual_wait = args.manual_wait if args.manual_wait is not None else CFG.get("manual_wait", 300)
    args_global = args
    for w in windows:
        r = rows.get(w, {})
        email = (r.get("email") or "").strip() or None
        pwd = (r.get("password") or "").strip() or None
        # 优先 accounts.json 里该窗口手填的账号密码
        aj = acc_json.get(w) or acc_json.get(str(w)) or {}
        if aj.get("email"):
            email = aj["email"].strip() or email
        if aj.get("password"):
            pwd = aj["password"].strip() or pwd
        # 再按备注匹配(TXT优先,其次备注自带密码)
        if not (email and pwd):
            try:
                _pr = ads_find(profile_no=str(w).lstrip("_"))
                remark = (_pr or {}).get("remark", "") or (_pr or {}).get("name", "")
                rem_email, rem_pwd = parse_remark(remark)
                if rem_email and rem_email.lower() in creds:
                    email, pwd = creds[rem_email.lower()]
                else:
                    if not email and rem_email:
                        email = rem_email
                    if not pwd and rem_pwd:
                        pwd = rem_pwd
            except Exception as e:
                log.warning(f"[accounts] 备注解析失败 {w}: {str(e)[:80]}")
        # 只打开填了账号密码的窗口
        if not (email and pwd):
            log.info(f"[skip] {w} 没填账号密码,不打开")
            continue
        name = r.get("name") or ""
        loc = r.get("location") or CFG.get("location")
        av = r.get("avatar") or pick_avatar(w, CFG.get("avatar_dir", ""), windows)
        gpx = r.get("gpx_dir") or CFG.get("gpx_dir")
        try:
            run_one(w, email, pwd, name, loc, av, gpx,
                    check_only=args.check_only, recheck=args.recheck,
                    try_google=(not args.no_google) and CFG.get("try_google_auto", True),
                    manual_wait=manual_wait)
        except Exception as e:
            log.error(f"[{w}] 整体失败: {e}")
            log.error(traceback.format_exc(limit=3))
        human_delay(1, 2)


# ---------- 高级采集: 多区域 + 多条件筛选 ----------
# ★ 用户第2条(地区): 距离环带 100~1000km, 圆心 = **该号自己的所在地**
#   (不再写死芝加哥/洛杉矶)。纽约州是必扫目标, 且纽约来源的人
#   【豁免 1000km 上限】, 但仍然要 >100km(太近的不要)。
GEO_BAND_MIN_KM = 100.0
GEO_BAND_MAX_KM = 1000.0
# ★★ 2026-09-23 用户要求: 取消环带距离, 只要美国境内就采 ★★
#   做法【不是删代码】, 而是把环带放成 0 ~ BAND_OFF_KM:
#     · in_target_band 除了"太近/太远"不会因别的原因淘汰 ——
#       认不出位置、只认到州, 它都返回"不确定=保留"(见 geo_cities 里那个函数);
#       所以上限一放大, 距离这一关就【永远通过】, 只剩"美国境内"那一道。
#     · states_in_band(0, 很大) 自然返回【全美所有州】, 采集州扩展不用改。
#   美国本土跨度不到 5000km, 任何圆心到任何州都 <20000km, 所以等于不判。
#   ★ 想恢复环带: 把 config 的 geo_band_min_km/max_km 填回 100/1000 就行。
BAND_OFF_KM = 20000.0
# ★ 用户第3条(地图): 每段路段必须 >=5000 用户(原 200/10000 口径作废)。
#   界面/旧配置可能还传来 200 这类旧值 —— 引擎里必须兜底抬到硬性要求。
MIN_ATHLETES_FLOOR = 5000
def resolve_min_athletes(v):
    """每段人数门槛的最终值: 低于地板就抬到地板, 0 表示不设门槛。

    ★★ 2026-09-19 用户要求「每段」做成下拉框之后, 地板也改成可配 ★★
      原来死钉 MIN_ATHLETES_FLOOR = 5000: 界面选 2000 -> 这里【悄悄抬回 5000】,
      只留一行 warning, 表现就是"选了没用" ——
      和以前"12 州 / 每段门槛"那类半截生效是同一个坑。
      现在地板读 config 的 min_athletes_floor:
        · 没配置        -> 仍是 5000(行为与改造前逐字一致)
        · 配了 2000     -> 就按 2000 用(界面下拉框会把两个键设成同一个值)
        · 0             -> 不设门槛, 采样到的路段全部参与排名
    """
    try:
        v = int(v)
    except Exception:
        v = MIN_ATHLETES_FLOOR
    try:
        _f = CFG.get("min_athletes_floor")
        floor = MIN_ATHLETES_FLOOR if _f is None else int(_f)
    except Exception:
        floor = MIN_ATHLETES_FLOOR
    if floor < 0:
        floor = 0
    # ★ 0 是"明确要求不设门槛", 不能被地板抬走 ——
    #   否则 config 里 min_athletes=0 而地板还是 2000 时, 它会悄悄变成 2000,
    #   下拉框里那个"0 (不设门槛)"又白选了。
    if v == 0:
        log.info("[quota] 每段人数门槛 = 0(不设门槛), 采样到的路段全部参与排名")
        return 0
    if v < floor:
        log.warning(f"[quota] 每段人数门槛 {v} 低于地板 {floor}, 已抬到 {floor}"
                    f"(想再低请把 config 的 min_athletes_floor 一起调低)")
        v = floor
    return v


# ★ 用户第4条(硬性指标): 每个号必须采到 200 个合格用户, 不够就继续扫, 达标即停。
TARGET_FLOOR = 200
# 内部安全上限(只防跑飞, 不再决定采集量): 每个地区最多找多少个路段
SEGS_PER_REGION_CAP = 40
# ★ 每次向中心服务领取的批量 —— 这【不是】采集量上限: 每个候选人都会被查,
#   只是分批领取。为什么分批: claim_store 的租约是 3600 秒, 一次领几百人却
#   查不完的话, 那些人会被白白占住一小时。
# ★ 2.16: 由 60 改成 15 —— 一次领 60 人却只查得完 20 人, 剩下的会被租约白占
CLAIM_CHUNK = 15
# ★ 2.12: 并发号数(进程内全局)。并发时网速样本被互相污染, _net_scale 会把
#   所有 timeout 放大到 48000ms。多个号并发时取最大值(见 collect_one/run_one_seq)。
CONCURRENCY_HINT = 1

# ============================================================
# 任务上下文: 每次任务一个文本文档 + 任务开始时间(用户硬需求)
# 命名: collected_users_<YYYYMMDD>_<HHMMSS>[_<号>].txt
#   * 只含 [0-9A-Za-z_] 和 .  -> Windows 合法(避开 < > : " / \ | ? *)
TASK_FILE_PREFIX = "collected_users_"
# ★★ 2026-09-19 用户要求:「名字改成固定的。文档名字改成（链接-日期）」★★
#   当天成果文件就叫  链接-20260920.txt   —— 前缀「链接-」固定, 后面跟日期。
#   ★ TASK_FILE_PREFIX 保留: 它标识【历史遗留】的 collected_users_*.txt
#     (老任务文件还在盘上, 跨天去重必须继续扫它们)。
DAILY_FILE_PREFIX = "链接-"
_TASK_LOCK = threading.Lock()

_OUT_LOCK = threading.RLock()                # ★ 必须是 RLock, 不能是 Lock!
#   为什么: append_task_url() 是 `with _OUT_LOCK:` 之后又调 _out_index(),
#   而 _out_index() 自己也 `with _OUT_LOCK:` —— 同一线程重入。用普通 Lock
#   会当场自锁死(实测: 第一个合格用户落盘就永久卡住, 8 秒/无限期不返回),
#   整轮采集直接挂在那里。后人"顺手改成 Lock"= 让采集永远采不出第一条。
_OUT_HAVE = {"built": False, "set": set()}   # 历史成果里出现过的 URL(进程内)


def _task_dir():
    """任务文件与总表同目录: 分层包=数据/, 扁平包=包根(跟随 COLLECT_OUT)"""
    return COLLECT_OUT.parent


def _safe_name(s):
    """把地区名变成能当文件名的样子。

    ★ 2026-09-24: 用户要求"选了哪个地区, 成果文件名就是地区+日期"。
      地区名里带括号/斜杠/冒号("Lakefront Trail (Chicago)")在 Windows 上
      直接建不出文件 —— 非法字符一律换成下划线。
    """
    t = re.sub(r'[\\/:*?"<>|]', "_", str(s or "")).strip().strip(".")
    return re.sub(r"\s+", " ", t)[:40] or "未命名地区"


def _daily_path(when=None, region=None):
    """当天成果文件 —— 一天一个, 当天链接全在里面。

    ★★ 2026-09-19 用户要求:「时间戳分文档取消一下。每一天采集的链接只存一个
       带时间的文档。集中一下。」★★
       旧行为是【每次任务一个文件 + 每个号一个明细文件】:
           collected_users_20260919_084252.txt        (任务成品)
           collected_users_20260919_084252_50.txt     (号级明细)
       跑一天 数据/ 里堆几十个文件, 找一个链接要在几十个文件里翻。
       现在: 一天一个文件, 文件名带日期, 当天所有链接按采集顺序追加。

    ★★ 2026-09-24 用户要求:「选择什么地区, 采集下来的链接保存文件名就是
       地区加日期」★★
       传了 region 就是  <地区>_<日期>.txt   例如  洛杉矶-骑行_20260924.txt
       没传还是老样子    链接-<日期>.txt
       (多个地区混着采的那种, 调用方不传 region, 保持一天一个文件)

    ★ collected_users.txt(历史总表)【保留】—— 它是累计去重的底账,
      不是"当天成果", 和用户要取消的那种"时间戳分文档"不是一回事。
    """
    d = when or datetime.now()
    if region:
        return _task_dir() / f"{_safe_name(region)}_{d:%Y%m%d}.txt"
    # ★ 文件名 = 固定前缀「链接-」+ 日期, 例如   链接-20260920.txt
    return _task_dir() / f"{DAILY_FILE_PREFIX}{d:%Y%m%d}.txt"



def new_task_ctx(target=None, mode="gui", worker=""):
    """一次任务 = 界面点一次开始(或 CLI 一次运行)。t_start 只在这里取一次。

    ★ 2026-09-19 起: 不再为每次任务单独建文件(用户要求"一天一个")。
      tid 只用于日志和"本次采了多少条"的统计; day 是当天成果文件的日期。
    """
    t = datetime.now()
    return {"t_start": t, "tid": t.strftime("%Y%m%d_%H%M%S"),
            "day": t.strftime("%Y%m%d"),
            "target": target, "mode": mode, "worker": worker,
            "subs": [], "done": False, "final": None, "lock": threading.Lock()}


def new_account_ctx(task, seq):
    """号级明细上下文: 共享任务的 tid/开始时间, 自己一个文件。"""
    sub = {"t_start": task["t_start"], "tid": task["tid"], "seq": str(seq or ""),
           "target": task.get("target"), "mode": task.get("mode"),
           "worker": task.get("worker"), "path": None, "urls": {}, "task": task}
    with task["lock"]:
        task["subs"].append(sub)
    return sub


def _open_task_file(ctx, kind="acct"):
    """返回【当天成果文件】链接-YYYYMMDD.txt(一天一个)。

    ★★ 2026-09-19 用户要求"集中成一个当天文档"之后:
       · 不再区分"号级明细 / 任务成品", 所有链接都进同一个当天文件
       · kind 形参保留只为兼容旧调用方, 现在【内容上没区别】
       · ctx["path"] 缓存当天文件, 多号并发共用
    文件不存在时先建出来并写一行日期头; 已存在就直接追加。
    ★ 并发安全: 调用方(append_task_url)持 _OUT_LOCK, 且用 'x' 独占新建,
      两个号同时第一次写也只会有一个写出文件头, 另一个拿到 FileExistsError
      被正常吞掉 —— 不会出现两个文件头, 也不会互相覆盖。

    ★★ 2026-09-20 修(跨零点写错文件) ★★
      原来第一句是 `if ctx.get("path"): return ctx["path"]` —— 把【任务开始
      那天】的文件路径缓存死了。任务只要跑过 00:00, 之后采到的链接就会继续
      写进【昨天】那个文件:
          · 今天该有的新文件一直是空的
          · 界面上的"今日 N 条"读的是今天的新文件 -> 一直显示 0
      看着就像"采了没记上"。现在每次都按【当天】重新算: 日期没变就沿用
      缓存(省掉重复的 stat 和建文件), 日期变了就换当天的文件。
    """
    try:
        p = _daily_path(region=ctx.get("region"))   # ★ 号上带了地区就按地区命名
        cur = ctx.get("path")
        if cur and Path(cur).name == p.name:
            return cur                       # 还是同一天 -> 用缓存
        ctx["path"] = None                   # 日期变了, 旧缓存作废
        if not p.exists():
            try:
                with open(p, "x", encoding="utf-8") as f:   # x: 已存在则抛错
                    # ★ 用户要求"只保留链接即可, 其他信息不需要"。
                    #   头部只留一行日期(文件名里也有, 这里是为了文件自己也看得懂)。
                    f.write(f"# 采集日期 {datetime.now():%Y-%m-%d}\n")
            except FileExistsError:
                pass                    # 已被别的线程/上一次运行建好了, 正常
        ctx["path"] = p
        return p
    except Exception as e:
        log.warning(f"[task] 当天成果文件创建失败, 退回历史总表: {str(e)[:60]}")
        ctx["path"] = COLLECT_OUT       # 兜底: 绝不因为新功能丢成果
        return ctx["path"]


def _out_index():
    """历史成果里出现过的 URL 集合。只在第一次调用时扫盘, 之后常驻内存。

    ★ 必须同时扫【历史总表本身】: 总表名 collected_users.txt 不匹配
      TASK_FILE_PREFIX("collected_users_") + "*.txt" 这个 glob, 漏掉它就等于
      对已有的 2586 行(其中 959 行重复)视而不见, 重复行照样会继续产生。
    """
    with _OUT_LOCK:
        if _OUT_HAVE["built"]:
            return _OUT_HAVE["set"]
        s = set()
        cands = []
        if COLLECT_OUT.exists():
            cands.append(COLLECT_OUT)                     # ★ 历史总表自己
        for d in (_task_dir(), _task_dir() / "归档"):
            if not d.is_dir():
                continue
            # ★★ 必须扫【三种】文件名 ★★
            #   新的: 链接-20260920.txt          (一天一个, 2026-09-19 起)
            #   新的: <地区>_20260920.txt         (按号选了地区, 2026-09-24 起)
            #   旧的: collected_users_<tid>*.txt  (历史遗留, 老机器上还有一堆)
            #   只扫一种 -> 另一种里的链接会被当成"没见过" -> 重复写第二遍。
            cands.extend(sorted(d.glob(DAILY_FILE_PREFIX + "*.txt")))
            cands.extend(sorted(d.glob("*_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].txt")))
            cands.extend(sorted(d.glob(TASK_FILE_PREFIX + "*.txt")))
        for p in cands:
            try:
                for line in p.read_text(encoding="utf-8",
                                        errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):   # 跳过任务头/注释
                        continue
                    s.add(line.split("\t")[0])             # 第一列恒为 URL
            except Exception:
                continue
        _OUT_HAVE["set"] = s
        _OUT_HAVE["built"] = True
        return s


def append_task_url(ctx, url, extra=""):
    """写一条成果。返回 True=新写入, False=历史文件里已有(跳过, 不计数)。

    ★ 2026-09-19 用户要求:"只保留链接即可, 其他信息不需要"。
      所以文件里【只写 URL 一行】, 不再追加 制表符 + aid/region/segment/age。
      extra 形参保留只为兼容旧调用方(界面/老脚本), 内容一律忽略。
    """
    u = (url or "").strip()
    if not u:
        return False
    if ctx is None:                     # 没传上下文: 退回老行为, 绝不丢成果
        try:
            with open(COLLECT_OUT, "a", encoding="utf-8") as f:
                f.write(u + "\n")
            return True
        except Exception as e:
            log.warning(f"[task] 落盘失败: {str(e)[:60]}")
            return False
    with _OUT_LOCK:
        have = _out_index()
        if u in have:
            return False                    # ★ 极致去重: 交付过的绝不再写第二遍
        p = _open_task_file(ctx)
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(u + "\n")           # ★ 只写链接
        except Exception as e:
            # ★ 这里的 False 与上面"历史已有"的 False【语义不同】, 必须让调用方能
            #   区分开: 一个是我主动去重(数据本来就在), 一个是根本没写进去(磁盘满/
            #   文件被占)。上层若混为一谈, 就会给中心发 finish(pass) —— 于是又造出
            #   一条"中心认为采到了、本地却没有"的缝。
            log.warning(f"[task] 落盘失败: {str(e)[:60]}")
            if isinstance(ctx, dict):
                ctx["write_err"] = str(e)[:80]
            return False
        # ★★ 2026-09-20 用户要求:「链接实时更新至文档」★★
        #   当天成果文件本来就是逐条落盘的; 但【累计总表 collected_users.txt】
        #   以前只在 finalize_task 里合并一次 —— 任务还没结束(或者被强杀)时去
        #   看总表, 会发现一条都没多, 看起来就像"没在采"。
        #   现在两边都实时写。finalize 的合并保持不动: 它再读的时候这些行已经
        #   在了, 等于空操作, 不会写出重复。
        #   ★ p 可能就是 COLLECT_OUT(创建失败时的兜底), 那就别写第二遍。
        try:
            if Path(p).resolve() != Path(COLLECT_OUT).resolve():
                with open(COLLECT_OUT, "a", encoding="utf-8") as f2:
                    f2.write(u + "\n")
        except Exception as e:
            # 总表写不进去不影响成果(当天文件已经写成功了), 只记一行
            log.warning(f"[task] 总表实时追加失败(成果文件不受影响): {str(e)[:50]}")
        have.add(u)
        # ★★ 2026-09-20 修(实测复现): 这里原来是 ctx["urls"][u] = True。
        #   只有 new_account_ctx() 的【号级 ctx】有 urls 键, new_task_ctx() 的
        #   【任务级 ctx】没有。调用方一旦误传任务级 ctx, 就当场 KeyError ——
        #   而这一行在【写文件之后】, 于是现象是: 链接其实已经落盘, 采集却抛异常
        #   中断, 上层看到的是"这次没保存"。跟"采集了没文档"长得几乎一样, 极难排查。
        #   setdefault 一行堵死: 任务级 ctx 也能安全记账。
        ctx.setdefault("urls", {})[u] = True   # 保序(dict), 供 finalize 汇总
        return True


def finalize_task(task):
    """把号级明细汇总成【任务成品文件】, 并把新增 URL 合并进历史总表。幂等。"""
    if not task:
        return None
    with _TASK_LOCK:
        if task.get("done"):
            return task.get("final")
        task["done"] = True
    t_end = datetime.now()
    urls, rows = {}, []
    for sub in list(task.get("subs") or []):
        for u in (sub.get("urls") or {}):
            urls.setdefault(u, sub.get("seq") or "-")
        rows.append((sub.get("seq") or "-", len(sub.get("urls") or {}),
                     sub.get("path").name if sub.get("path") else "-"))
    # ★★ 2026-09-19 用户要求"一天一个文档"之后 ★★
    #   这里【不再另建任务成品文件】—— 链接在 append_task_url() 写的时候就
    #   已经进了当天的 collected_users_YYYYMMDD.txt。再建一个 <tid>.txt
    #   正是用户要取消的"时间戳分文档", 而且会让同一个链接出现两份。
    task["final"] = _daily_path()
    # 历史总表: 锁内"读->合并->原子替换"(与 _state_write 同款), 不再逐条追加
    if urls:
        with _OUT_LOCK:
            try:
                disk = []
                if COLLECT_OUT.exists():
                    disk = [x for x in COLLECT_OUT.read_text(
                        encoding="utf-8", errors="replace").splitlines()
                        if x.strip() and not x.startswith("#")]
                known = {x.split("\t")[0] for x in disk}
                disk = list(dict.fromkeys(disk))          # ★ 顺手把历史重复行也收敛掉
                add = [u for u in urls if u not in known]
                if add or len(disk) != len(known):
                    tmp = COLLECT_OUT.with_name(
                        COLLECT_OUT.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
                    tmp.write_text("\n".join(disk + add) + "\n", encoding="utf-8")
                    os.replace(tmp, COLLECT_OUT)
            except Exception as e:
                log.warning(f"[task] 总表合并失败(成果文件不受影响): {str(e)[:60]}")
    # ★ 2026-09-19: 耗时/合计这些"其他信息"用户说文件里不要, 但日志里留着有用
    #   (顺带让 t_end 不再是未使用变量)。
    log.info(f"[task] 本次任务 {len(urls)} 条, 耗时 "
             f"{(t_end - task['t_start']).total_seconds() / 60:.1f} 分钟, "
             f"{len(rows)} 个号 -> "
             f"{task['final'].name if task.get('final') else '(成品写入失败, 明细仍在)'}")
    return task.get("final")
# ★ 地图放大(用户第3条): 必须放大到能看清热力图分布才选路段。
#   ★★ 2026-09 真机缺陷修复: 老逻辑"只滚 8 次、看到 3 个标记就停"恰好落在
#      4~8 级的甜点区; 后来的"最多 14 级 + 见到标记后再多放 4 级"会一路放大到
#      标记彻底消失(真机测: 4~8 级 38~56 个, 9 级 21 个, 10 级 1 个, 11 级后 0 个)
ZOOM_MAX_STEPS = 8          # ★ 真机实测: 甜点区在 4~8 级; 再深放大(10级+)页面会卡死
                            #   (第10级后整轮 11 分钟无输出), 所以上限从 12 收到 8
ZOOM_MIN_STEPS = 6          # ★ 至少要放到 6 级才允许"标记变少就停": 真机对比过,
                            #   第 4 级点 8 个标记只捞出 1 个大路段, 第 6 级能捞出 4 个
# ★ 2026-09-19 用户要求"精准找每个州人数最多的路段": 这个常量【改了语义】。
#   以前 = "采用到这么多就停止平移"(先到先得, 4 个就走)。
#   现在 = "采样到这么多就停止平移, 然后【按运动达人数排名】取最大的几个"。
ENOUGH_SEGMENTS = 48        # 采样够这么多个路段就停止平移(可配 enough_segments)
PAN_ROUNDS = 24             # 选路段时地图平移轮数(可配 pan_rounds)
# ★★ 2026-09-22 用户实测: 点完地图标记【立刻】读"运动达人"数 ——
#   弹窗还没渲染出来, 读到 -1, 上层记 0, 看着就像"这个路段没人"。
#   原来只等了"弹窗里的路段链接"(wait_text key=segpop), 而链接比人数先出现。
#   现在点完标记【再等一次人数本身】, 上限这么多秒(可配 seg_ath_wait;
#   等到了立刻就走, 只有真点到空标记才会耗满)。
SEG_ATH_WAIT = 2.5
# 判定"弹窗里的运动达人数字渲染出来了没有"(wait_text 用; 测试也直接引它,
# 免得两边各写一份正则、改一处漏一处)。
SEG_ATH_READY_JS = ("/([0-9][0-9,.\u00a0 ]*)\\s*(?:位\\s*)?"
                    "(?:运动达人|運動達人|athletes|athlete|"
                    "atletas?|Athleten|アスリート|спортсмен)/i"
                    ".test(document.body.innerText||'')")

# ★★ 2026-09-19 用户实测:「采集效率太慢, 芝加哥几百上千万用户,
#    是你选点只选择几个重复的」★★
#    查清了, 瓶颈是【两个数字】, 不是网格算法:
#      · PAN_ROUNDS = 8        —— 一个地区只平移 8 轮
GRID_PAN_STEP_X = 420        # 网格横向步长(约 1/3 视口宽)
GRID_PAN_STEP_Y = 260        # 网格纵向步长
GRID_PAN_COLS = 4            # 蛇形网格每行走几列(3 次横向推进后换行)


def grid_pan_targets(rounds, cx=700, cy=400):
    """蛇形网格平移: 返回 rounds 个【拖拽终点】(每次都是从 (cx,cy) 拖到该点)。

    ★★ 2026-09-19 重写(用户: "你选点只选择几个重复的") ★★
      旧实现 `(cx + px*STEP_X, cy + py*STEP_Y)` + 6 步固定 pattern, 实际位移是:
          +420 → +420 → ↓260 → -420 → -420 → ↓260 → +420 → +420
      向右两次、再向左两次 —— 【走回头路】, 8 轮里真正新覆盖的面积很小,
      所以每个地区只能摸到那么几个路段, 而且反复是同一片。
      现在改成【单调蛇形】:
          行内一直朝同一方向推进, 到行尾才下移一行并把方向反过来。
          视野走位(以起点为原点, 4 列):
            (0,0)(1,0)(2,0)(3,0) → 换行 ↓ → (3,1)(2,1)(1,1)(0,1) → 换行 ↓ → …
          每一轮都是新地面, 不再回头。
      ★ 每次拖拽都从中心 (cx,cy) 出发, 每轮位移不超过一格, 终点恒在视口内。
    """
    try:
        n = max(0, int(rounds))
    except Exception:
        n = 0
    try:
        cols = max(2, int(GRID_PAN_COLS))
    except Exception:
        cols = 4
    out = []
    col = 0
    dir_x = 1
    for _i in range(n):
        nxt = col + dir_x
        if nxt < 0 or nxt >= cols:
            # 到行尾 -> 下移一行, 方向反转(仍在同一列, 所以下一轮往内走)
            out.append((cx, cy + GRID_PAN_STEP_Y))
            dir_x = -dir_x
        else:
            col = nxt
            out.append((cx + dir_x * GRID_PAN_STEP_X, cy))
    return out


# ★ 无配置时的基础地区清单: 只有纽约(必扫), 其余由"环带内的州"自动补
COLLECT_BASE_REGIONS = ["New York"]
# ★ 12 州默认值改成"纽约为首"(保留旧清单兜底, 但纽约一定排第一)
REGIONS_DEFAULT = ["New York", "Indiana", "Michigan", "Wisconsin", "Iowa", "Missouri",
                   "Ohio", "Kentucky", "Minnesota", "Tennessee", "West Virginia",
                   "Pennsylvania"]

# geo_cities 不可用/HUBS 缺失时的兜底圆心(与 geo_cities.HUBS 一致)
_HUBS_FALLBACK = {"Chicago": (41.8781, -87.6298), "LosAngeles": (34.0522, -118.2437)}


# ==================== ★ 地区环带接口(geo_cities 冻结接口的薄适配) ====================
# 说明: geo_cities 的新接口(resolve_center/states_in_band/state_center/is_new_york,
#       in_target_band 带 center/exempt_max)由另一个子代理同步实现。
#       这里全部走惰性 import + 缺函数降级, 保证"新接口还没就位时"引擎不会崩,
def _geo_cities():
    """惰性拿 geo_cities 模块(拿不到返回 None)"""
    try:
        import geo_cities
        return geo_cities
    except Exception as e:
        log.warning(f"[geo] geo_cities 不可用({str(e)[:60]}) —— 位置筛选降级处理")
        return None


def _hubs():
    """HUBS 表: 优先用 geo_cities.HUBS, 缺失时用内置兜底"""
    g = _geo_cities()
    h = getattr(g, "HUBS", None) if g is not None else None
    if isinstance(h, dict) and h:
        return h
    return dict(_HUBS_FALLBACK)


def geo_band_limits(min_km=None, max_km=None):
    """环带上下限: 参数 > geo_cities.BAND_* > 内置默认"""
    g = _geo_cities()
    if min_km is None:
        min_km = getattr(g, "BAND_MIN_KM", None) if g is not None else None
    if max_km is None:
        max_km = getattr(g, "BAND_MAX_KM", None) if g is not None else None
    try:
        mn = float(min_km) if min_km is not None else GEO_BAND_MIN_KM
    except Exception:
        mn = GEO_BAND_MIN_KM
    try:
        mx = float(max_km) if max_km is not None else GEO_BAND_MAX_KM
    except Exception:
        mx = GEO_BAND_MAX_KM
    return mn, mx


def geo_resolve_center(loc_text, state_hint=""):
    """★ 圆心解析: geo_cities.resolve_center(loc_text, state_hint) -> (lat, lon, label, conf)

    旧版 geo_cities 还没这个函数时退回 lookup(), conf 语义一致(city/state/none)。
    """
    g = _geo_cities()
    if g is None:
        return None, None, "", "none"
    f = getattr(g, "resolve_center", None)
    try:
        if f is not None:
            lat, lon, label, conf = f(loc_text or "", state_hint or "")
            return lat, lon, (label or ""), (conf or "none")
        log.warning("[geo] geo_cities 缺 resolve_center -> 退回 lookup()(旧口径)")
        lat, lon, conf, matched = g.lookup(loc_text or "", state_hint or "")
        return lat, lon, (matched or loc_text or ""), (conf or "none")
    except Exception as e:
        log.warning(f"[geo] resolve_center 异常: {str(e)[:60]}")
        return None, None, "", "none"


def geo_in_band(loc_text, state_hint="", min_km=None, max_km=None,
                center=None, exempt_max=False):
    """★ 环带判定: geo_cities.in_target_band(..., center=, exempt_max=)

    返回 (ok, why, conf, dist_km, center_label); ok=True 保留 / False 淘汰 / None 不确定。
    exempt_max=True 时只判"太近", 不判"太远"(纽约豁免上限)。
    """
    mn, mx = geo_band_limits(min_km, max_km)
    g = _geo_cities()
    if g is None:
        return None, "geo_cities 不可用", "none", None, ""
    f = getattr(g, "in_target_band", None)
    if f is None:
        log.warning("[geo] geo_cities 缺 in_target_band -> 本次不做位置淘汰")
        return None, "geo_cities 缺 in_target_band", "none", None, ""
    try:
        return f(loc_text, state_hint, min_km=mn, max_km=mx,
                 center=center, exempt_max=bool(exempt_max))
    except TypeError:
        # 旧签名(没有 center/exempt_max): 明确告警后按旧口径判, 不静默
        log.warning("[geo] ★★ geo_cities.in_target_band 还是旧签名(无 center/exempt_max),"
                    " 本次按旧口径判定 —— 请等 geo_cities 新接口就位")
        try:
            return f(loc_text, state_hint, mn, mx)
        except Exception as e:
            log.warning(f"[geo] in_target_band 旧签名也失败: {str(e)[:60]}")
            return None, "位置判定异常", "none", None, ""
    except Exception as e:
        log.warning(f"[geo] in_target_band 异常(保留): {str(e)[:60]}")
        return None, "位置判定异常", "none", None, ""


def geo_states_in_band(lat, lon, min_km=None, max_km=None):
    """环带内的州(按距离升序)。老接口没有该函数时返回空表并告警"""
    mn, mx = geo_band_limits(min_km, max_km)
    g = _geo_cities()
    f = getattr(g, "states_in_band", None) if g is not None else None
    if f is None:
        log.warning("[geo] geo_cities 缺 states_in_band -> 本次不自动补环带内的州"
                    "(只扫配置里的地区)")
        return []
    try:
        return list(f(lat, lon, mn, mx) or [])
    except Exception as e:
        log.warning(f"[geo] states_in_band 异常: {str(e)[:60]}")
        return []


def geo_is_new_york(text):
    """★ 纽约判定(必扫州)。优先用 geo_cities.is_new_york"""
    t = str(text or "").strip()
    if not t:
        return False
    g = _geo_cities()
    f = getattr(g, "is_new_york", None) if g is not None else None
    if f is not None:
        try:
            return bool(f(t))
        except Exception:
            pass
    tl = t.lower()
    if "new york" in tl:
        return True
    return bool(re.search(r"(^|[\s,])ny([\s,]|$)", tl))


def _hub_pick(text="", near=None):
    """★ 圆心兜底: 优先"离已知坐标最近的 hub"; 否则文本里点到 hub 名;
    再否则用配置 location 最近的 hub; 最后用 HUBS 里的第一个(芝加哥)。
    返回 (名字, (lat, lon))"""
    hubs = _hubs()
    if near and near[0] is not None and near[1] is not None:
        g = _geo_cities()
        hk = getattr(g, "haversine_km", None) if g is not None else None
        if callable(hk):
            try:
                name = min(hubs, key=lambda k: hk(near[0], near[1],
                                                  hubs[k][0], hubs[k][1]))
                return name, hubs[name]
            except Exception:
                pass
    t = str(text or "").lower().replace(" ", "")
    for name in hubs:
        if t and str(name).lower().replace(" ", "") in t:
            return name, hubs[name]
    _la, _lo, _lb, _cf = geo_resolve_center(str(CFG.get("location") or ""))
    if _cf != "none" and _la is not None:
        g = _geo_cities()
        hk = getattr(g, "haversine_km", None) if g is not None else None
        if callable(hk):
            try:
                name = min(hubs, key=lambda k: hk(_la, _lo, hubs[k][0], hubs[k][1]))
                return name, hubs[name]
            except Exception:
                pass
    name = next(iter(hubs))
    return name, hubs[name]


def detect_home_loc(page, seq=None, cached=""):
    """★ 用户第2条: 自动识别"该号自己的所在地"(圆心不再写死)

    优先级:
      ① cached        —— 调用方刚在 /settings/profile 上用 read_settings_info()
                         读到的真实 location(不重复读页面, 省一次 6 秒轮询)
      ② 页面现读       —— read_settings_info(page).location
      ③ state         —— load_state()[task_state_key(seq)]["location"]
      ④ CFG["location"] —— 配置兜底
    只读页面, 任何异常都不向上抛(认不出返回 ""), 由 collect_regions 决定怎么兜底。
    """
    loc = str(cached or "").strip()
    if not loc and page is not None:
        try:
            loc = str((read_settings_info(page) or {}).get("location") or "").strip()
        except UserStopped:
            raise
        except Exception as e:
            log.warning(f"[geo] 读本号所在地失败: {str(e)[:60]}")
    if not loc and seq is not None:
        try:
            loc = str((load_state().get(task_state_key(seq), {}) or {}).get("location")
                      or "").strip()
        except Exception:
            pass
    if not loc:
        loc = str(CFG.get("location") or "").strip()
    log.info(f"[geo] 本号所在地识别: {loc or '(空)'}")
    return loc


def popup_athletes(page):
    """读地图弹窗里的"运动达人"数(★ 多语言, 中文界面也算)。

    ★★ 2026-09-19 重大修复(用户截图实证: 「179,318 位运动达人」):
      老正则只认英文 —— `/([\\d,]+)\\s*athletes/i`。
      只要界面上是中文, 弹窗写的是「179,318 位运动达人」, 那个正则
      【永远匹配不到】-> 每个路段都返回 -1 -> 上层判定"读不到人数" ->
      【所有路段被跳过】-> 采集 0 人。这不是产量低, 是直接归零。
      现在按多语言匹配(中/繁/英/法/西/德/日/俄/意/波), 两种语序都试:
          「179,318 位运动达人」 和 「运动达人 179,318」
      数字允许千分位(逗号/点/空格/不换行空格)。

    ★ 真机小坑(_真机探针.log): 点到空标记(热力图色块)时整页没有达人字样,
      读数是 -1; 有时还会读到上一次弹窗的残留。读数 <= 0 一律归一成 -1。
    """
    try:
        n = page.evaluate(r"""() => {
            var t = document.body.innerText || '';
            // ① 数字在前: 「179,318 位运动达人」/「165,075 athletes」
            var a = t.match(/([0-9][0-9,.\u00a0 ]*)\s*(?:位\s*)?(?:运动达人|運動達人|athletes|athlete|athl[eè]tes?|atletas?|Athleten|アスリート|스포츠맨|спортсмен|sportivi|sportowcy)/i);
            if (a) {
                var n1 = parseInt(String(a[1]).replace(/[^0-9]/g, ''), 10);
                if (!isNaN(n1) && n1 > 0) return n1;
            }
            // ② 关键词在前: 「运动达人 179,318」
            var b = t.match(/(?:运动达人|運動達人|athletes|athlete|atletas?|Athleten|アスリート|спортсмен)\s*[:：]?\s*([0-9][0-9,.\u00a0 ]*)/i);
            if (b) {
                var n2 = parseInt(String(b[1]).replace(/[^0-9]/g, ''), 10);
                if (!isNaN(n2) && n2 > 0) return n2;
            }
            return -1;
        }""")
        if not isinstance(n, int):
            log.warning(f"[popup] 达人读数类型异常({n!r}) -> 按读不到处理")
            return -1
        if n <= 0:
            # ★ 区分"读不到"(-1: 整页没有达人字样, 多半点到了空标记)
            #   和"读到 0/负数"(页面里真有这个数, 但显然不可用/是残留)
            if n < 0:
                log.info("[popup] 读不到达人数(整页没有该字样, 可能点到空标记) -> -1")
            else:
                log.warning(f"[popup] 读到达人数={n}(<=0, 疑似空标记或上次弹窗残留) -> -1")
            return -1
        return n
    except Exception as e:
        log.warning(f"[popup] 读达人数异常: {str(e)[:60]} -> -1")
        return -1


# ---- is_us_location() 用到的现成件(都来自 geo_cities, 不重复实现) ----
_re = re
try:
    from geo_cities import STATE_XY as _STATE_XY
    from geo_cities import STATE_NAME2ABBR as _STATE_NAME2ABBR
except Exception:                        # geo_cities 不可用时不拦人(降级为认不出)
    _STATE_XY, _STATE_NAME2ABBR = {}, {}


def geo_lookup(loc_text, state_hint=""):
    """包一层 geo_cities.lookup; 拿不到就返回认不出(绝不抛)"""
    try:
        return _geo_cities().lookup(loc_text, state_hint)
    except Exception:
        return None, None, "none", ""


# 美国别称 —— 位置文本的地区段里出现这些, 说明"这儿是美国", 不能当境外判
_US_WORDS = {"united states", "united states of america", "usa", "us",
             "u.s.", "u.s.a.", "america"}

# ★★ 2026-09-25 用户报"采集的怎么还有德国的账号" ★★
#   实测漏网两条路(跑 is_us_location 逐条验出来的):
#     ① 只写城市名 -> 撞上【美国同名小镇】被判成"确定美国":
#          Berlin(NH/CT) Hamburg(PA/NY) Munich(ND) Stuttgart(AR) Cologne(NJ)
#        —— CITY_XY 是纯美国城市表, 同名就命中, 它不知道柏林更有名的是德国那个。
#     ② 认不出(None) -> us_only_strict 没开时一律保留:
#          "Germany" 单独一个词、"Frankfurt" 美国没这个镇
#   这两张表就是给它们兜底的: 命中就是【确定境外】, 不看城市表了。
#   ★ 只放"几乎不可能是美国地名"的: 不放 Chicago/Denver 这种美国城市,
#     否则会把正常的美国人误杀。
_FOREIGN_CITY = {
    "berlin", "hamburg", "munich", "munchen", "stuttgart", "cologne", "koln",
    "frankfurt", "dusseldorf", "dortmund", "essen", "leipzig", "dresden",
    "bonn", "bremen", "hannover", "nurnberg", "nuremberg", "heidelberg",
    "paris", "london", "manchester", "birmingham", "dublin", "rome", "milan",
    "madrid", "barcelona", "lisbon", "amsterdam", "rotterdam", "brussels",
    "vienna", "wien", "zurich", "geneva", "stockholm", "oslo", "copenhagen",
    "helsinki", "warsaw", "prague", "budapest", "athens", "istanbul", "moscow",
    "tokyo", "osaka", "seoul", "beijing", "shanghai", "hong kong", "singapore",
    "sydney", "melbourne", "brisbane", "auckland", "toronto", "vancouver",
    "montreal", "calgary", "ottawa", "mexico city", "guadalajara",
    "sao paulo", "rio de janeiro", "buenos aires", "lima", "bogota",
    "santiago", "cape town", "johannesburg", "cairo", "dubai", "tel aviv",
    "mumbai", "delhi", "bangkok", "jakarta", "manila", "kuala lumpur",
}
_FOREIGN_COUNTRY = {
    "germany", "deutschland", "france", "italy", "spain", "portugal",
    "netherlands", "belgium", "austria", "switzerland", "sweden", "norway",
    "denmark", "finland", "poland", "czechia", "czech republic", "hungary",
    "greece", "turkey", "russia", "ukraine", "ireland", "united kingdom",
    "uk", "england", "scotland", "wales", "canada", "mexico", "brazil",
    "argentina", "chile", "peru", "colombia", "china", "japan", "korea",
    "south korea", "india", "thailand", "vietnam", "indonesia", "malaysia",
    "philippines", "australia", "new zealand", "south africa", "egypt",
    "israel", "united arab emirates", "saudi arabia",
}


def is_us_location(loc_text, state_hint=""):
    """这个人的所在地是不是在美国境内。返回 True / False / None(认不出)

    ★★ 2026-09-19 用户要求:「设置只要美国境内的用户」★★

    ★ 不能只看 geo_cities.lookup() 的置信度 —— 它按【城市名】严格匹配,
      不看国家部分, 而 CITY_XY 是纯美国城市表, 于是:
          'Paris, France'     -> city/paris    ← 美国阿肯色州的 Paris
          'Toronto, Ontario'  -> city/toronto  ← 美国俄亥俄州的 Toronto
          'Moscow'            -> city/moscow   ← 美国宾州的 Moscow
      直接信它会把法国/加拿大人都判成"美国人"。
      所以【先看地区部分】:
        ① 地区段里出现美国州(IL / Illinois ...)          -> 美国
        ② 地区段里出现"既不是美国州、也不是美国别称"的地名 -> 境外
        ③ 没有地区段 -> 再看坐标能不能落进美国城市表
    三个出口的含义:
      True  = 确定在美国
      False = 确定不在美国(地区段点名了别的国家/省份)
      None  = 认不出(只有城市名、且不在美国城市表里 —— 可能是境外,
              也可能是美国小镇没收录)。★ 这一档交给上层决定, 绝不在这里误杀。
    """
    t = str(loc_text or "").strip()
    if not t:
        return None
    try:
        parts = [p.strip() for p in _re.split(r"[,，]", t) if p.strip()]
    except Exception:
        parts = [t]
    if not parts:
        return None

    # ★★ 2026-09-25: 先过两张"确定境外"的表 —— 见 _FOREIGN_CITY 的说明 ★★
    #   ① 任何一段点名了外国 -> 确定境外
    #   ② 只有城市名(没有地区段) 且它在 _FOREIGN_CITY 里 -> 确定境外
    #      (否则会被美国同名小镇骗成"确定美国")
    for p in parts:
        if p.lower().replace(".", "").strip() in _FOREIGN_COUNTRY:
            return False
    if len(parts) == 1 and parts[0].lower().strip() in _FOREIGN_CITY:
        return False

    def _is_us_state(p):
        p = p.lower().replace(".", "").strip()
        return p in _STATE_XY or p in _STATE_NAME2ABBR

    # ★★ 安全阀: 州表不可用(geo_cities 缺失/损坏)时一律"认不出" ★★
    #   绝不能返回 False —— 那会让【所有带地区名的位置】被判成境外,
    #   把整个采集采空。一个辅助库坏掉不该升级成"主流程失效"。
    if not _STATE_XY and not _STATE_NAME2ABBR:
        log.warning("[us] geo_cities 州表不可用 -> 国别一律按【认不出】处理"
                    "(不淘汰任何人)")
        return None

    # ①② 地区段(第 2 段往后)
    for p in parts[1:]:
        lp = p.lower().replace(".", "").strip()
        if not lp or lp in _US_WORDS:
            continue                     # 美国别称 / 空 -> 跳过, 不算证据
        if _is_us_state(lp):
            return True                  # 点名了美国州 -> 确定是美国
        return False                     # 冒出别的国家/省份 -> 确定是境外

    # ③ 没有可判别的地区段 -> 看坐标
    try:
        la, lo, conf, matched = geo_lookup(t, state_hint)
    except Exception:
        return None
    if conf in ("city", "state") and la is not None:
        return True                      # 落在美国城市表/州表里
    if parts and _is_us_state(parts[0]):
        return True                      # 只有一段, 而且它本身就是州名
    return None


def check_athlete(page, aid, max_followers=200, geo_filter=False,
                  center=None, exempt_max=False,
                  us_only=None, us_only_strict=None, recent_days=0):
    """检查运动员: 非私密 且 粉丝<200 且 关注<200 (+ 可选位置环带)

    ★ 用户第2条新增两个参数:
        center     = (lat, lon, label) —— 圆心 = 本号自己的所在地
        exempt_max = True 时只判"太近"(>100km), 不判"太远" —— 仅当这个人
                     来自【纽约州路段】时才传(geo_cities 不会自己猜来源)
      日志里必须能看见 圆心 / 距离 / 是否豁免, 否则出了问题没法复盘。
    """
    # ---- ★ 国别口径: 只要美国境内(2026-09-19 用户要求) ----
    #   入参优先, 其次 config.json 的 us_only / us_only_strict。
    #   us_only_strict: "认不出国别"时是否也淘汰。
    #     默认【关】—— 不误杀: 美国小镇没收录、或资料只写了城市名时会落进
    # ★★ 2026-09-25 用户要求:「所有采集地区锁死美国地区。别的国家一律不要。」★★
    #   这里【不再读 config】—— 硬锁。
    #   以前这两行是 `CFG.get("us_only", True)` / `CFG.get("us_only_strict", False)`:
    #   严格模式默认【关】, 关着的时候"认不出国别"的一律放行,
    #   实测 Germany / Berlin / Hamburg / Frankfurt 就是这么被采进来的。
    #   形参保留只为让验证脚本能单独传值; 不传就是锁死的 True。
    #   (调用点 check_athlete(page, aid, ...) 不传这两个, 所以锁在这里一定生效。)
    if us_only is None:
        us_only = True
    if us_only_strict is None:
        us_only_strict = True
    _us_on = bool(us_only)
    _us_strict = bool(us_only_strict)

    js = r"""() => {
        var t = document.body.innerText || '';
        if (/private|\u79c1\u5bc6|This profile/i.test(t.slice(0, 900))) return {private: true};
        // ★ 2026-09-19: 粉丝/关注 的标签也做多语言归一化。
        //   老写法只认英文 /^(Following|Followers)$/ —— 界面一旦是中文
        //   ("关注者/正在关注"), 两个数都读不到, check_athlete 会对【每一个人】
        //   都返回"读不到数据", 采集直接归零。
        //   这里统一归一成 'followers' / 'following' 两个键, 上层不用改。
        var _lab = function(s){
            s = (s||'').trim();
            if (/^(Followers?|关注者|關注者|粉丝|粉絲|フォロワー|Abonn[eé]s|Seguidores|Follower|Подписчики|Obserwujący|Sledzacy)$/i.test(s)) return 'followers';
            if (/^(Following|正在关注|正在關注|關注中|正在追踪|フォロー中|Abonnements|Siguiendo|Folge ich|Подписки|Obserwowani|Sledzeni)$/i.test(s)) return 'following';
            // 宽松兜底: 带"粉丝/關注者/フォロワー"字样的算 followers
            if (/粉丝|粉絲|关注者|關注者|フォロワー/.test(s)) return 'followers';
            if (/正在关注|正在關注|關注中|フォロー中/.test(s)) return 'following';
            return '';
        };
        var out = {};
        var els = [...document.querySelectorAll('li,div,span')].filter(function(e){
            return e.children.length === 0 && !!_lab(e.textContent);
        });
        for (var i = 0; i < els.length; i++) {
            var e = els[i];
            var box = e.closest('li,div');
            var m = box ? (box.textContent||'').match(/([\d,]+)/) : null;
            if (m) { var k = _lab(e.textContent); if (k) out[k] = parseInt(m[1].replace(/,/g, '')); }
        }
        // ---- ★ 2026-09-22 用户要求: 只采"近期还有活动"的人 ----
        //   Strava 把活动时间放在 <time class="timeago" datetime="ISO"> 上,
        //   读 datetime 属性即可 —— 不用管界面语言, 也不用解析 "7 hours ago"。
        var ds = [];
        var tns = document.querySelectorAll('time[datetime]');
        for (var q = 0; q < tns.length; q++) {
            var dv = tns[q].getAttribute('datetime');
            if (dv) ds.push(dv);
        }
        out.recent_dates = ds.slice(0, 40);
        // 兜底: "Last 4 Weeks 12 Total Activities"
        var m4 = t.match(/Last\s+4\s+Weeks[\s\S]{0,60}?([\d,]+)\s+Total\s+Activit/i)
              || t.match(/\u6700\u8fd1\s*4\s*\u5468[\s\S]{0,30}?([\d,]+)\s*(?:\u6b21)?\u6d3b\u52a8/);
        out.four_week = m4 ? parseInt(m4[1].replace(/,/g, '')) : -1;
        return out;
    }"""
    for _try in range(2):
        check_stop()
        try:
            rate_gate("nav")      # ★ 风控闸门: 资料页导航 <=10 次/分钟
            goto_retry(page, f"https://www.strava.com/athletes/{aid}")
            # 原来固定等 2.5 秒;改成有界轮询:数字一渲染出来就走
            # ★ 2026-09-19: 等待条件也补上中文标签, 否则中文界面上永远等不到、
            #   只能干等满 2.5 秒(不会出错, 但白等)。
            wait_text(page,
                      "!!(/\\d/.test(document.body.innerText) "
                      "&& /Following|Followers|关注者|關注者|粉丝|粉絲|正在关注|正在關注/i"
                      ".test(document.body.innerText))",
                      timeout=2.5, key="athlete")
            r = page.evaluate(js) or {}
            if r.get("private"):
                return False, "私密"
            followers = r.get("followers", -1)
            following = r.get("following", -1)
            if followers < 0 or following < 0:
                time.sleep(backoff(_try))  # O2: 指数退避
                continue
            # ---- 位置筛选(可选, 由 geo_filter 控制; 不影响上面的粉丝判定) ----
            if geo_filter:
                # 语义(按用户要求):
                #   没填所在地   -> 保留(他们本来就是从筛选条件里找出来的)
                #   在环带内     -> 保留
                #   太近/太远    -> 淘汰
                try:
                    lr = page.evaluate(JS_READ_LOC) or {}
                    loc = (lr.get("loc") or "").strip()
                    _clabel = (center[2] if center and len(center) > 2 else "") or "?"
                    # ★ 2026-09-23: 这里以前写死 "环带100-1000km" ——
                    #   配置改成 0~20000(取消环带)之后, 日志还印着旧数字,
                    #   看日志的人会以为环带还在。现在按真实值显示。
                    _blo0, _bhi0 = geo_band_limits(CFG.get("geo_band_min_km"),
                                                   CFG.get("geo_band_max_km"))
                    if _bhi0 >= BAND_OFF_KM:
                        _ex_tag = "环带已取消(只判美国境内)"
                    elif exempt_max:
                        _ex_tag = f"豁免上限(仅判>{_blo0:.0f}km)"
                    else:
                        _ex_tag = f"环带{_blo0:.0f}-{_bhi0:.0f}km"
                    if not loc:
                        # ★ 2026-09-19: 未填所在地 —— 用户要求"只要美国境内",
                        #   这种属于【认不出国别】。默认保留(不误杀), 想看多严可以
                        #   把 config 的 us_only_strict 设成 true 一并淘汰。
                        if _us_on and _us_strict:
                            log.info(f"[check] {aid} 未填所在地 -> 国别认不出, "
                                     f"严格模式淘汰")
                            return False, "未填所在地(严格美国模式)"
                        log.info(f"[check] {aid} 未填所在地 -> 保留(圆心={_clabel})")
                    else:
                        # ★★ 先判国别: 只要美国境内 ★★
                        #   True=确定美国 / False=确定境外 / None=认不出
                        _us = is_us_location(loc) if _us_on else True
                        if _us is False:
                            log.info(f"[check] {aid} 位置={loc!r} -> 不在美国境内(淘汰)")
                            return False, "不在美国境内"
                        if _us is None and _us_strict:
                            log.info(f"[check] {aid} 位置={loc!r} -> 国别认不出, "
                                     f"严格模式淘汰")
                            return False, "国别认不出(严格美国模式)"
                        if _us is None:
                            log.info(f"[check] {aid} 位置={loc!r} -> 国别认不出, "
                                     f"按保留处理(要更严就把 us_only_strict 设 true)")
                        # ★★ 2026-09-23: 环带上下限改成【从 config 读】★★
                        #   以前这里写死 GEO_BAND_MIN_KM/MAX_KM, 界面上改了
                        #   geo_band_max_km 也到不了这一步(改了没用)。
                        _blo, _bhi = geo_band_limits(CFG.get("geo_band_min_km"),
                                                     CFG.get("geo_band_max_km"))
                        ok_g, why_g, conf, d, hub = geo_in_band(
                            loc, min_km=_blo, max_km=_bhi,
                            center=center, exempt_max=exempt_max)
                        _d = f"{d:.0f}km" if isinstance(d, (int, float)) else "?"
                        _src = f"圆心={_clabel} 距离={_d} {_ex_tag}"
                        if ok_g is False:
                            log.info(f"[check] {aid} 位置={loc!r} {_src} -> {why_g}(淘汰)")
                            return False, why_g
                        log.info(f"[check] {aid} 位置={loc!r} {_src} -> {why_g}(保留)")
                except UserStopped:
                    raise
                except Exception as e:
                    log.warning(f"[check] {aid} 位置判定异常(保留): {str(e)[:60]}")

            # ---- ★ 近期活动筛选(用户 2026-09-22: 只采近两个月还有活动的) ----
            #   recent_days<=0 = 不启用(老行为)。判定优先级:
            #     ① 页面上 <time datetime> 里最新的一条 —— 精确到秒, 首选
            #     ② 页面不给具体日期时看 "Last 4 Weeks N Total Activities"
            #        (4 周=28 天, 只要 >0 就必然落在 60 天窗口里)
            #   两个都拿不到 = 资料页上看不到任何近期活动 -> 淘汰。
            if recent_days and recent_days > 0:
                _newest, _age = None, None
                for _s in (r.get("recent_dates") or []):
                    try:
                        _d = datetime.fromisoformat(str(_s).replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if _newest is None or _d > _newest:
                        _newest = _d
                if _newest is not None:
                    try:
                        _age = (datetime.now(timezone.utc) - _newest).days
                    except Exception:
                        _age = None
                _fw = r.get("four_week", -1)
                if _age is not None and _age <= recent_days:
                    log.info(f"[recent] {aid} 最近活动 {_age} 天前"
                             f"(4周内 {_fw} 次) -> 保留")
                elif _age is None and isinstance(_fw, int) and _fw > 0 \
                        and recent_days >= 28:
                    log.info(f"[recent] {aid} 页面没给具体日期, "
                             f"但 4 周内有 {_fw} 次活动 -> 保留")
                else:
                    log.info(f"[recent] {aid} 最近活动 "
                             + (f"{_age} 天前" if _age is not None else "读不到")
                             + f"(4周内 {_fw} 次) -> 淘汰(超过 {recent_days} 天)")
                    return False, f"近{recent_days}天没活动"
            if followers < max_followers and following < max_followers:
                return True, f"粉丝{followers}/关注{following}"
            if followers >= max_followers:
                return False, f"粉丝{followers}超标"
            return False, f"关注{following}超标"
        except UserStopped:
            raise
        except Exception as e:
            log.warning(f"[check] {aid} err: {str(e)[:50]}")
            time.sleep(backoff(_try))      # O2: 指数退避
    return False, "读不到数据"


# ------------------------------------------------------- 榜单筛选: 合法取值
# ★★ 2026-09-19 用户要求"男性/本月/年纪 都做成框框供我选择" ★★
#   以前这三项是【写死】在榜单 URL 里的(gender=male&date_range=this_month),
#   年龄组也是硬编码。做成下拉框之前必须先钉死合法取值, 否则选到一个不存在的
AGE_GROUPS_VALID = ("0_19", "20_24", "25_34", "35_44", "45_54",
                    "55_64", "65_69", "70_74", "75_plus")
GENDERS_VALID = ("male", "female", "overall")
DATE_RANGES_VALID = ("this_month", "this_week", "this_year", "all")
# 用户口径的默认(和以前写死的完全一致, 不改任何现有行为)
# ★★ 2026-09-19 用户要求: 「45-54 岁及以下的选项取消, 保留 55 以上」★★
AGE_GROUPS_MIN_ALLOWED = 55        # 低于这个数的年龄桶一律不采
AGE_GROUPS_DEFAULT = ("55_64", "65_69")


def age_bucket_low(code):
    """年龄桶 -> 它的下界。'55_64'->55  '75_plus'->75  '0_19'->0, 认不出给 999"""
    try:
        return int(str(code or "").split("_")[0])
    except Exception:
        return 999


def _lb_filters(gender=None, date_range=None):
    """榜单筛选参数: 入参 > config.json > 老默认(男性/本月)。

    ★ 取值非法就【退回默认并告警】, 不把非法值发给 Strava ——
      发过去是 400, 上层看到的是"这个路段 0 人", 会被误当成"路段太小"。
    """
    g = str(gender or CFG.get("collect_gender") or "male").strip().lower()
    if g not in GENDERS_VALID:
        log.warning(f"[lb] 性别取值非法 {g!r}(合法: {GENDERS_VALID}) -> 退回 male")
        g = "male"
    d = str(date_range or CFG.get("collect_date_range")
            or "this_month").strip().lower()
    if d not in DATE_RANGES_VALID:
        log.warning(f"[lb] 时间范围取值非法 {d!r}(合法: {DATE_RANGES_VALID}) "
                    f"-> 退回 this_month")
        d = "this_month"
    return g, d


def _age_groups_of(age_groups=None):
    """年龄组清单: 入参 > config.json > 默认三段。逐项校验, 非法项剔除。"""
    src = age_groups
    if not src:
        src = CFG.get("collect_age_groups")
    if not src:
        return list(AGE_GROUPS_DEFAULT)
    if isinstance(src, str):
        src = [x.strip() for x in src.split(",") if x.strip()]
    out = []
    dropped = []
    for a in src:
        a = str(a).strip()
        if a not in AGE_GROUPS_VALID:
            log.warning(f"[lb] 年龄组取值非法 {a!r}(合法: {AGE_GROUPS_VALID}) -> 已剔除")
            continue
        if age_bucket_low(a) < AGE_GROUPS_MIN_ALLOWED:
            dropped.append(a)
            continue
        if a not in out:
            out.append(a)
    if dropped:
        # ★ 这里必须打日志: 否则"配置里写着 45_54, 实际没采"就成了静默行为,
        #   排查时会对不上账(界面/配置显示的和实际跑的不是一回事)。
        log.warning(f"[lb] 用户口径: {AGE_GROUPS_MIN_ALLOWED} 岁以下不采 -> "
                    f"已剔除 {dropped}; 剩下的 {out or list(AGE_GROUPS_DEFAULT)}")
    if not out:
        log.warning("[lb] 年龄组一个都没剩下 -> 退回默认 %s"
                    % (list(AGE_GROUPS_DEFAULT),))
        out = list(AGE_GROUPS_DEFAULT)
    return out


def region_search_key(region):
    """地区名 -> 真正打进 Strava 搜索框的关键词。

    ★★ 2026-09-19 用户给了 7 个"想采集的地方", 但它们其实是【地点/路段】,
       不是州: Central Park (New York) / Lakefront Trail (Chicago) /
       The 606 (Chicago) / Griffith Observatory (Los Angeles) / ...
       引擎原来是把整串原样打进去, 再用 get_by_text(全名, exact=True) 精确点击。
       括号里那串城市名【不在】Strava 的建议文本里, 于是必然 miss。
       所以搜索词去掉括号部分; 点击匹配再加三级兜底(见 collect_regions)。
    """
    r = str(region or "").strip()
    if " (" in r and r.endswith(")"):
        return r.split(" (")[0].strip()
    return r


def region_is_ny(region):
    """这个地区名算不算"纽约来源"(决定要不要豁免 1000km 上限)。

    ★ 除了 geo_cities 的州判定, 还要认 "Central Park (New York)" 这种写法 ——
      用户下拉里就有这一项, 光靠 geo_is_new_york 认不出来, 会白丢豁免。
    """
    try:
        if geo_is_new_york(region):
            return True
    except Exception:
        pass
    return "new york" in str(region or "").lower()


def fetch_lb_filtered(page, seg_id, age, max_pages=None, gender=None,
                      date_range=None):
    """排行榜: 性别 + 时间范围 + 指定年龄组(默认 男性/本月, 与改造前一致)

    ★ 2026-09-19: gender / date_range 从【写死】改成从 config.json 读
      (collect_gender / collect_date_range), 供界面上的框框选择。
      不传参时行为与改造前【逐字一致】(male + this_month)。

    ★ 默认翻页数改成从配置读(lb_max_pages, 默认 8)。原来写死 2 页 ——
      5000 人的路段只翻 2 页会严重漏人, 和"每号必须 200 人"的硬性指标冲突。
      停止条件保持不变: 翻到没有数据 / 已够 total 就停(现有 net_ready 限流
      与退避逻辑一律不动)。
    """
    _g, _dr = _lb_filters(gender, date_range)
    if max_pages is None:
        try:
            max_pages = int(CFG.get("lb_max_pages") or 8)
        except Exception:
            max_pages = 8
    try:
        max_pages = max(1, int(max_pages))
    except Exception:
        max_pages = 8
    js = r"""async (args) => {
      const [seg, age, pg, gender, dr] = args;
      const url = 'https://www.strava.com/frontend/segments/' + seg + '/leaderboard'
                + '?filter_type=age_group&filter_value=' + age
                + '&gender=' + gender + '&date_range=' + dr + '&page=' + pg;
      const r = await fetch(url, {headers: {'accept':'application/json','x-requested-with':'XMLHttpRequest'}});
      const t = await r.text();
      let j=null; try { j = JSON.parse(t); } catch(e) {}
      if (!j) return {ok:false, status:r.status};
      return {ok:true, total: j.totalCount||0,
              rows: (j.leaderboard||[]).map(x=>({name:x.displayName||'',
                                                 aid:x.athleteIdStr||String(x.athleteId||'')}))};
    }"""
    rows, total = [], 0
    for pg in range(1, max_pages + 1):
        try:
            rate_gate("api")      # ★ 风控闸门: 榜单接口 >=1.5s/次
            _t_lb2 = net_ready()
            res = page.evaluate(js, [seg_id, age, pg, _g, _dr])
            net_elapsed(_t_lb2, "api")
        except UserStopped:
            raise
        except Exception:
            break
        if not res or not res.get("ok"):
            break
        total = res.get("total") or total
        part = res.get("rows") or []
        rows += part
        if not part or len(rows) >= total:
            break
        time.sleep(random.uniform(1, 2))
    return total, rows


def backoff(attempt, base=1.0, cap=16.0):
    """指数退避: 1,2,4,8,16 秒(带随机抖动, 避免多个进程同时重试)

    为什么需要: 原来固定 sleep(2)/sleep(4) 对付不了网络抖动 ——
    你日志里出现过 AggregateError、Target page/browser has been closed,
    这类瞬时故障等固定时间往往不够, 而重试次数又只有 2~3 次。
    """
    try:
        d = min(cap, base * (2 ** max(0, attempt)))
        return d * random.uniform(0.8, 1.2)
    except Exception:
        return 2.0


# 读所在地的 JS —— 依据实测: <H1> 内是 "名字 / [所在地] / Follow / [简介]"
# 注意: 不能用页面内嵌 JSON 的 city/state, 实测 8 个用户全是默认值 Los Angeles
JS_READ_LOC = r"""() => {
    var pick = function(arr) {
        for (var i = 0; i < arr.length; i++) {
            var s = (arr[i] || '').trim();
            if (!s || s === 'Follow' || s === 'Unfollow') continue;
            if (/^(Dashboard|Training|Maps|Challenges|Upload|Give a Gift)$/i.test(s)) continue;
            // 形如 "City, ST" / "City, State" / "City US"
            if (/^[A-Za-z\u00C0-\u024F\.\-\' ]{2,42},\s*(?:[A-Za-z]{2,30}|[A-Z]{2})\s*$/.test(s))
                return {loc: s, kind: 'city'};
        }
        return null;
    };
    var h1 = document.querySelector('h1');
    if (h1) {
        var txt = (h1.innerText || '');
        var parts = txt.split('\n').map(function(x){return x.trim()}).filter(Boolean);
        // 跳过第一行(名字), 其余里找像地名的
        var r = pick(parts.slice(1));
        if (r) return r;
    }
    // 退路: 整个正文前 30 行里找
    var t = (document.body.innerText || '').split('\n').map(function(x){return x.trim()}).filter(Boolean);
    var r2 = pick(t.slice(0, 30));
    if (r2) return r2;
    return {loc: '', kind: 'none'};
}"""


def _reload_claim_client():
    """补救: 进程启动时 claim_client.py 恰好不在, 之后即使文件回来了也要能用。

    ★★ 2026-09-19 用户实测踩到 ★★
      现象: 界面跑任务, 30 个号全部
              [claim] 缺 claim_client.py -> 退回本地去重
              [collect] 领取服务不可用 —— 为防多机重复, 本次采集取消
            而文件当时明明就在项目根目录、import 也完全正常。
      根因: 界面在【启动时】一次性 exec 引擎(界面/ADS自动化.py 里那三行
            spec_from_file_location / exec_module), 那一刻如果 claim_client.py
            不在, 模块级 import 就永久失败, ClaimClient 被钉死成 None ——
            之后文件回来了, 这个进程也【永远不会再试】。
            日志里那句"缺 claim_client.py"其实是在说【进程启动时缺】,
            但它读起来像"文件现在缺", 排查时会一直往错的方向找。
      所以: 真正要用的时候再试一次 import(importlib 走 sys.path, 上面已经补好),
            成功就把模块级 ClaimClient 补上 —— 不用重启界面。

    失败不影响正确性: 上层 make_claim_client 返回 None 时,
    collect 那条路是 fail-closed 的(领取服务不可用就取消采集), 不会重复采。
    """
    global ClaimClient
    if ClaimClient is not None:
        return ClaimClient
    try:
        import importlib
        import claim_client as _cc
        importlib.reload(_cc)                 # 防上次导入失败留下的半成品
        ClaimClient = _cc.ClaimClient
        log.info("[claim] claim_client.py 现在导进来了(进程启动时它不在, "
                 "已自动补上, 不用重启界面)")
    except Exception as _e:
        log.warning(f"[claim] 重新导入 claim_client 仍失败: {str(_e)[:70]}")
    return ClaimClient


def make_claim_client(hint=""):
    """连上领取服务。未配置则返回 None(退回本地去重, 单机可用)"""
    server = (CFG.get("claim_server") or DEFAULT_CLAIM_SERVER or "").strip()
    if not server:
        log.info("[claim] 未配置 claim_server -> 本地去重(多机共享时请配置)")
        return None
    if _reload_claim_client() is None:
        log.warning("[claim] 配置了 claim_server 但【进程启动时】就没导到 "
                    "claim_client.py, 现在重试仍然失败 -> 退回本地去重")
        return None
    worker = auto_worker_id("ads") or resolve_worker_id(hint)
    cache = ROOT / f"claim_cache_{worker}.json"
    c = ClaimClient(server, worker,
                    CFG.get("claim_key") or DEFAULT_CLAIM_KEY or "",
                    cache_file=str(cache))
    h = c.ping()
    if not h:
        log.error(f"[claim] 服务端不可达: {server}")
        return None
    log.info(f"[claim] 已连接 {server}  worker={worker}  服务端已记录 {h.get('athletes')} 人")
    try:                                  # ★ 回收逾期 pending(服务端会把 older_than 钳到租约时长)
        _r = c._post("/reset_stale", {"older_than": 3600})
        if _r.get("n"):
            log.info(f"[claim] 回收逾期领取 {_r['n']} 条")
    except Exception as _e:
        log.warning(f"[claim] 逾期回收失败(不影响采集): {str(_e)[:50]}")
    return c


def claim_pick(cli, seen, aids):
    """从候选人里挑出"该我处理的"。

    返回 (mine, skipped)
      mine    : 归我处理, 去打开资料页
      skipped : 已被别人/本机处理过, 直接跳过(零流量)
    服务端不可达时抛 ServerDown, 由上层中止采集 —— 绝不退回本地模式。
    """
    aids = [str(a) for a in aids if a]
    if not aids:
        return [], 0
    if cli is None:
        return [a for a in aids if a not in seen], 0
    r = cli.claim_batch(aids)          # 本地缓存预筛 + 向服务端领取
    mine = list(r.get("mine") or [])
    taken = r.get("taken") or []
    # 把"别人已处理完"的写进本地记录, 以后连问都不用问
    # ★ 2.14: pass/done 也是终态 —— 只记 reject 会让这些人在本机每轮都重问一遍
    for t in taken:
        _st = t.get("status")
        if _st == "reject":
            seen[str(t["aid"])] = "reject"
        elif _st in ("pass", "done"):
            seen[str(t["aid"])] = "pass"
    return mine, len(taken)


_SEEN_LOCK = threading.Lock()


def save_seen(seen):
    """锁内 read-merge-write: 不许整份覆盖别人的记录, 不许静默把坏文件当空。"""
    tmp = COLLECT_SEEN.with_name(
        COLLECT_SEEN.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    with _SEEN_LOCK:
        disk = {}
        try:
            if COLLECT_SEEN.exists():
                disk = json.loads(COLLECT_SEEN.read_text(encoding="utf-8")) or {}
        except Exception:
            log.error("[seen] 去重记录损坏, 已改名保留(.bad), 本次按空记录合并")
            try:
                COLLECT_SEEN.replace(COLLECT_SEEN.with_name(COLLECT_SEEN.name + ".bad"))
            except Exception:
                pass
        disk.update(seen or {})            # ★ 合并, 不是覆盖
        tmp.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, COLLECT_SEEN)


def collect_regions(page, regions=None, age_groups=None,
                    min_athletes=None, max_followers=200, target_per_account=None,
                    max_segments_per_region=None, cli=None, geo_filter=None,
                    home_loc=None, auto_regions=None, task=None, seq=None,
        only_regions=False,
                    lb_gender=None, lb_date_range=None, **_compat):
    """区域采集(用户新口径 2026-09):

      ① 圆心 = **本号自己的所在地**(home_loc), 环带 100~1000km
      ② 纽约州必扫(排第一), 纽约来源的人豁免 1000km 上限(仍要 >100km)
      ③ 地图必须放大到能看清热力图分布才选路段; 每段路段 >=5000 用户
      ④ 每号硬性采到 200 个合格用户(不够就换路段/换地区继续, 达标即停)

    合格 = 男性 + 年龄组 45_54/55_64/65_69 + 排行榜时间=本月 + 非私密
           + 关注<200 且 粉丝<200 + 中心服务去重(不重复)

    ★ 小上限(max_segments_per_region)只当安全上限, 不再决定采集量。
    """
    # ---- ★ 平移轮数 / 采样目标: 都能在 config.json 里调 ----
    #      是你选点只选择几个重复的」★★
    #   三个上限原来叠在一起: 只平移 8 轮 + 网格会走回头路 + 采样够 12 个就收手,
    #   而 SEGS_PER_REGION_CAP=40 那个"每地区最多 40 个"根本轮不到生效。
    try:
        _pan_rounds = int(CFG.get("pan_rounds") or PAN_ROUNDS)
    except Exception:
        _pan_rounds = PAN_ROUNDS
    try:
        _enough = int(CFG.get("enough_segments") or ENOUGH_SEGMENTS)
    except Exception:
        _enough = ENOUGH_SEGMENTS
    if _pan_rounds < 1:
        _pan_rounds = PAN_ROUNDS
    if _enough < 1:
        _enough = ENOUGH_SEGMENTS
    log.info(f"[region] 平移轮数={_pan_rounds} 采样目标={_enough} 个路段"
             f"(config: pan_rounds / enough_segments)")
    # ★ 点完标记后等"运动达人"数渲染出来的上限(秒)。见 SEG_ATH_WAIT 注释。
    try:
        _ath_wait = float(CFG.get("seg_ath_wait") or SEG_ATH_WAIT)
    except Exception:
        _ath_wait = SEG_ATH_WAIT
    if _ath_wait <= 0:
        _ath_wait = SEG_ATH_WAIT
    # ---------------- ★ 自己解析一遍 config ----------------
    # 为什么: 「▶ 开始任务」和「◎ 只采集」两条入口都会传参, 但只要有一边漏传
    #         (或界面传的是旧值), 口径就会不一致。引擎内部统一兜一遍最稳。
    if _compat:
        log.warning(f"[region] 忽略已废弃参数: {sorted(_compat)}"
                    f"(采集量由 {TARGET_FLOOR} 人目标驱动)")
    _segs_arg, min_athletes_arg = max_segments_per_region, min_athletes

    # ---- ★ 年龄组 / 性别 / 时间范围: 界面上三个框框选什么就用什么 ----
    #   ★★ 取值优先级: 调用方传进来的(界面 _cfg() 的运行时字典) > config.json。
    #      为什么必须优先用传进来的: 界面的 _cfg() 只是【返回】一个字典交给
    #      引擎, 并不写 config.json; 而 CFG 是引擎【导入时】读的一次性快照。
    age_groups = _age_groups_of(age_groups)
    _lb_g, _lb_d = _lb_filters(lb_gender, lb_date_range)
    log.info(f"[lb] 榜单口径: 性别={_lb_g} 时间={_lb_d} 年龄组={list(age_groups)}")

    # ---- 每段人数门槛(用户第3条硬性 5000) ----
    # ★★ 这里不能写 `arg or CFG.get(..) or FLOOR` ★★
    #   0 表示"不设门槛", 而 0 是 falsy —— 老写法会把 0 一路推成 5000,
    #   界面上那个"0 (不设门槛)"选项从来没生效过。
    _mv = min_athletes_arg
    if _mv is None or _mv == "":
        _mv = CFG.get("min_athletes")
    try:
        min_athletes = (int(_mv) if _mv is not None and _mv != ""
                        else MIN_ATHLETES_FLOOR)
    except Exception:
        min_athletes = MIN_ATHLETES_FLOOR
    # ★ 每段人数门槛: 走 resolve_min_athletes() —— 地板可配(见函数注释)
    min_athletes = resolve_min_athletes(min_athletes)
    # ---- 每号合格人数目标(用户第4条硬性 200) ----
    try:
        target_per_account = int(target_per_account
                                 or CFG.get("collect_target_per_account")
                                 or TARGET_FLOOR)
    except Exception:
        target_per_account = TARGET_FLOOR
    # ★ 2026-09-19: 地板值改成【可配置】—— 界面上的「每号目标人数」本来就是 1~2000,
    #   但引擎以前无条件抬到 200, 于是填 10 也被悄悄改成 200(实测踩过)。
    #   现在默认仍是 200; 想跑小样本(比如试跑 10 个)就加 "target_floor": 10。
    try:
        _tfloor = int(CFG.get("target_floor") or TARGET_FLOOR)
    except Exception:
        _tfloor = TARGET_FLOOR
    if _tfloor < 1:
        _tfloor = 1
    if target_per_account < _tfloor:
        log.warning(f"[quota] 每号目标 {target_per_account} 低于地板 {_tfloor}, "
                    f"已抬到 {_tfloor}")
        target_per_account = _tfloor
    try:
        max_followers = int(max_followers or CFG.get("max_followers") or 200)
    except Exception:
        max_followers = 200
    # ---- 每地区路段数: 0/None/缺省 -> 内部安全上限(不是采集量) ----
    if _segs_arg is None:
        _segs_arg = CFG.get("segs_per_region")
    try:
        max_segments_per_region = int(_segs_arg or 0)
    except Exception:
        max_segments_per_region = 0
    if max_segments_per_region <= 0:
        max_segments_per_region = SEGS_PER_REGION_CAP

        log.info(f"[region] 每地区路段安全上限未配置 -> 内部默认 "
                 f"{SEGS_PER_REGION_CAP}(只防跑飞, 不决定采集量, "
                 f"采集量由 {target_per_account} 人目标驱动)")

    band_min, band_max = geo_band_limits(CFG.get("geo_band_min_km"),
                                         CFG.get("geo_band_max_km"))
    ny_exempt = bool(CFG.get("ny_exempt_max_km", True))
    # ★ 默认 True: 缺这个键时也必须按用户要求开筛选(以前 ADS 默认关、
    #   比特默认开, 同一份配置两个引擎口径不同)
    _geo = bool(CFG.get("geo_filter", True)) if geo_filter is None else bool(geo_filter)
    # ★ 2026-09-22 用户要求: 只采"近期还有活动"的人
    #   默认 60 天(两个月); config.json 里 recent_days=0 可关掉。
    try:
        _recent = int(CFG.get("recent_days", 60))
    except Exception:
        _recent = 60
    if auto_regions is None:
        auto_regions = bool(CFG.get("collect_auto_regions", True))

    # ---------------- ★ 圆心: 按【脚本配置的位置】(用户 2026-09-19 要求) ----------------
    #   旧行为: 圆心 = 该号自己的 Strava 所在地。问题是【号可以填任何地方】——
    #     实测有号填的是 "Vientiane"(老挝), 环带就围着万象 100~1000km,
    #     采回来的自然是老挝/泰国人, 和"只要美国境内"直接冲突。
    _cfg_loc = str(CFG.get("location") or "").strip()
    _mode = str(CFG.get("geo_center") or "config").strip().lower()
    if _mode == "account":
        _home = str(home_loc or "").strip() or _cfg_loc
        log.info(f"[geo] geo_center=account -> 圆心用本号所在地 {_home!r}")
    else:
        _home = _cfg_loc
        if not _home:
            _home = str(home_loc or "").strip()
            log.warning("[geo] config 的 location 为空 -> 退回用本号所在地做圆心")
        else:
            log.info(f"[geo] geo_center=config -> 圆心固定为脚本位置 {_home!r}"
                     f"(不跟本号所在地跑)")
    clat, clon, clabel, cconf = geo_resolve_center(_home)
    if cconf != "city" or clat is None:
        # ★ conf=state 只精确到州, conf=none 认不出 —— 都不能当"本号所在地"用。
        #   回退顺序(每一步都写日志, 不许静默换圆心):
        #     ① 配置 location(这些号本来就被设置成这个城市)
        #     ② HUBS 最近者(优先离已知坐标最近的 hub)
        _near = (clat, clon) if clat is not None else None
        _src = f"home_loc={_home!r}(conf={cconf})" if _home else "home_loc 为空"
        _fb = ""
        if _cfg_loc and _cfg_loc != _home:
            _la, _lo, _lb, _cf = geo_resolve_center(_cfg_loc)
            if _cf == "city" and _la is not None:
                clat, clon, clabel, cconf = _la, _lo, _lb, _cf
                _near = None
                _fb = f"回退配置 location={_cfg_loc}"
        if cconf != "city" or clat is None:
            if _near is None and _cfg_loc:
                _la2, _lo2, _lb2, _cf2 = geo_resolve_center(_cfg_loc)
                if _la2 is not None:
                    _near = (_la2, _lo2)
            _hn, (_hla, _hlo) = _hub_pick(_home, near=_near)
            clat, clon, clabel, cconf = _hla, _hlo, _hn, "hub"
            _fb = f"兜底用 HUBS 最近者={_hn}"
        log.warning(f"[geo] ★★ 本号所在地识别不精确({_src}) -> {_fb}; "
                    f"圆心={clabel}(conf={cconf}) —— 距离口径可能不准")
    # ★ in_target_band 的 center 约定是 (lat, lon, label) —— 只传 3 个元素
    center = (clat, clon, clabel)
    log.info(f"[geo] 本号所在地={_home or '(空)'} -> 圆心={clabel}(conf={cconf})")
    log.info(f"[geo] 距离环带={band_min:.0f}~{band_max:.0f}km"
             + ("(★已取消: 只要美国境内就采)" if band_max >= BAND_OFF_KM else "")
             + f" | 纽约豁免上限={'开' if ny_exempt else '关'} "
             f"| 位置筛选={'开' if _geo else '关'}")

    # ---------------- ★ 计划地区: 纽约一定排第一 + 环带内的州 ----------------
    # ★ 注意: states_in_band() 永远选不出纽约州(芝加哥->纽约州中心 1001.8km,
    #   刚好超过 1000km 上限), 所以"纽约必扫"必须【无条件】自己放进清单。
    _base = list(regions or CFG.get("collect_regions") or COLLECT_BASE_REGIONS)
    _plan, _seen_r = [], set()
    for r in _base:
        r = str(r or "").strip()
        if r and r.lower() not in _seen_r:
            _seen_r.add(r.lower())
            _plan.append((r, None))
    if not only_regions and not any(region_is_ny(r) for r, _d in _plan):
        # ★ 用户明确要求: 每个号都要扫一段纽约州的路段
        _plan.insert(0, ("New York", None))
        log.info("[geo] 配置里没有纽约 -> 必扫地区补在第一位: New York")
    elif not only_regions:
        # 纽约挪到第一位
        _ny = [x for x in _plan if region_is_ny(x[0])]
        _plan = _ny + [x for x in _plan if not region_is_ny(x[0])]
    else:
        # ★★ 2026-09-24: 界面给这个号【单独指定了地区】—— 那就只采它 ★★
        #   实测后果(用户报"还是按默认地区采集"): 给号单独选 New Jersey,
        #   计划仍是 [New York, New Jersey, 全美50州…] —— 采集从纽约开始填,
        #   目标人数(200)一满就再也轮不到 New Jersey, 看上去就是"按默认采的"。
        #   所以按号指定时必须【只采那一个】: 不塞纽约、不自动撒网。
        log.info(f"[geo] ★本号单独指定地区, 只采这 {len(_plan)} 个: "
                 + "、".join(r for r, _d in _plan[:5]))
    if auto_regions and not only_regions:
        for _st in geo_states_in_band(clat, clon, band_min, band_max):
            try:
                _abbr, _full, _d = _st[0], _st[1], _st[2]
            except Exception:
                continue
            _nm = str(_full or _abbr or "").strip()
            if not _nm or geo_is_new_york(_nm) or geo_is_new_york(_abbr):
                continue                     # 纽约已经排第一, 去重
            if _nm.lower() in _seen_r:
                continue
            _seen_r.add(_nm.lower())
            try:
                _plan.append((_nm, float(_d)))
            except Exception:
                _plan.append((_nm, None))
        log.info(f"[geo] 自动补环带内的州 {len(_plan)} 个(去重后)")
    _plan_names = [r for r, _d in _plan]
    # ★★ 2026-09-19 用户要求"按编号错开地区":
    #   3 个号并发时, 如果计划完全一样, 它们会同时扎进同一个州、挑同一批"人数最多"
    #   这里按编号把【纽约之后的地区】轮转错开: 号1 从第1个开始, 号2 从第2个开始…
    #   纽约仍然永远排第一 —— 用户硬性要求"每个号都要扫一段纽约州的路段", 不动它。
    if seq is not None and len(_plan_names) > 1:
        try:
            _rk = (int(str(seq).strip()) - 1) % (len(_plan_names) - 1)
        except Exception:
            _rk = 0
        if _rk:
            _plan_names = _plan_names[:1] + _plan_names[1 + _rk:] + _plan_names[1:1 + _rk]
            log.info(f"[geo] ★ 按编号错开地区: 号={seq} -> 纽约之后从 "
                     f"{_plan_names[1]} 开始(共 {len(_plan_names)} 个地区)")
    log.info("[geo] 计划地区(按顺序): " + " -> ".join(
        f"{r}({'?' if d is None else f'{d:.0f}km'})" for r, d in _plan))

    # ★ 第二批 §2: 单号全局时间预算 + 连续空地区计数(堵"15~45 小时/号")
    _t0 = time.time()
    _dry = 0                      # 连续空地区计数

    # ★ 任务上下文(用户硬需求): 界面传进来就跟着那一次任务, 没传(命令行/老界面)
    #   就自己建一个 —— 无论哪条路径, 成果都落进"独立带时间的 txt"。
    _auto_task = task is None
    if _auto_task:
        task = new_task_ctx(target=target_per_account, mode="auto")
    # ★ 号级明细的 seq 必须有值: 之前一律传 ""(空), 于是"号级明细"占了
    #   collected_users_<tid>.txt 这个名字, 把"任务成品"挤到 _2/_3 去了,
    #   文件名与规格 §1.2 对不上。调用方(collect_one / run_one)现在会把
    #   真实编号传下来, 明细文件就是 collected_users_<tid>_<号>.txt。
    _sub = new_account_ctx(task, seq or "")
    # ★★ 2026-09-24 用户要求: 「选择什么地区, 采集下来的链接保存文件名就是
    #   地区加日期」★★
    #   只采【一个】地区时才按地区命名 —— 那种"一次采 29 个地区"的精准采集
    #   会把成果摊到 29 个文件里, 反而更难找, 所以多个地区保持一天一个文件。
    _rs = [r for r in (regions or []) if str(r).strip()]
    _sub["region"] = str(_rs[0]) if len(_rs) == 1 else None
    # ★ 并发改造: 把本号的作用域写进线程局部 —— 之后本线程所有 rate_gate 都走
    #   这个号【自己】的令牌桶(没写作用域时退回默认桶)。每个号一个线程, 天然隔离,
    #   3 个号并发时各跑各的 6.0/1.5/0.6 秒预算, 不再抢同一份额度。
    set_rate_scope(f"seq{seq}" if seq else f"t{threading.get_ident()}")

    seen = {}
    if COLLECT_SEEN.exists():
        try:
            seen = json.loads(COLLECT_SEEN.read_text(encoding="utf-8"))
        except Exception as e:
            # ★ 2.13: 读坏不许静默当空(静默 = 把全部已采的人再采一遍)
            log.error(f"[seen] 去重记录损坏/读取失败(本次按空记录继续): {str(e)[:60]}")
            seen = {}
    collected = []
    stat = {"seg_total": 0, "seg_pass": 0, "checked": 0, "pass": 0,
            "reject": 0, "taken": 0}

    # ★ 外层: 未达标且还有地区就一直往下跑; 达标立刻停(用户第4条)
    try:
        for region in _plan_names:
            if len(collected) >= target_per_account:
                break
            # ★ 第二批 §2: 单号时间预算(到点就停, 不再耗到 15~45 小时)
            _budget = float(CFG.get("collect_max_minutes") or 240) * 60
            if time.time() - _t0 > _budget:
                log.warning(f"[quota] 已达单号时间上限 {_budget/60:.0f} 分钟, 停止采集"
                            f"(已合格 {len(collected)}/{target_per_account})")
                break
            check_stop()
            _is_ny = region_is_ny(region)
            _exempt = bool(_is_ny and ny_exempt)
            log.info(f"[region] ===== {region} ====="
                     f"{' [纽约: 豁免1000km上限, 仍须>100km]' if _exempt else ''}")
            # ★ 每进一个地区就清一次多余标签页(用户要求: 只留工作页, 省内存)
            close_extra_pages(page, tag=f" [{region}]")
            try:
                log.info(f"[net] {net_info()}")
                goto_retry(page, "https://www.strava.com/maps/global-heatmap/segments?sport=All&style=standard&terrain=false")
                accept_cookies(page, timeout=3)
                sleep_or_stop(5)
                # See the heat
                for _t in range(3):
                    try:
                        b = page.get_by_role("button", name=re.compile(r"See the heat", re.I))
                        if b.count() and b.first.is_visible():
                            b.first.click(); time.sleep(5); break
                    except Exception:
                        pass
                    time.sleep(1)
                # 搜区域
                try:
                    box = page.locator("input[placeholder*='Search for a location']").first
                    box.click(); time.sleep(1)
                    # ★★ 打进去的关键词要去掉括号里的城市名 ★★
                    #   "Central Park (New York)" 这么长一串, Strava 的建议里
                    #   不会有同名的整串, 原来的 exact=True 必然 miss。
                    #   用户下拉里就是这种写法(7 个地点全是这个格式)。
                    _key = region_search_key(region)
                    for ch in _key:
                        page.keyboard.type(ch, delay=80)
                    time.sleep(3)
                    hit = False
                    # 三级匹配: ① 原名精确 -> ② 去括号精确 -> ③ 建议里包含关键词
                    for t in (region, _key, region.split(",")[0]):
                        if not t:
                            continue
                        try:
                            loc = page.get_by_text(t, exact=True).first
                            if loc.count() and loc.is_visible():
                                loc.click(); hit = True; break
                        except Exception:
                            continue
                    if not hit and _key:
                        # ③ 模糊: 建议文本里【包含】关键词的第一项
                        #   (建议一般是 "Central Park, New York, United States"
                        #    这种带后缀的写法, 精确匹配永远等不到)
                        try:
                            loc = page.get_by_text(re.compile(re.escape(_key), re.I)).first
                            if loc.count() and loc.is_visible():
                                loc.click(); hit = True
                                log.info(f"[region] 用模糊匹配点中建议: {_key!r}")
                        except Exception:
                            pass
                    log.info(f"[region] 搜索 {region}(关键词 {_key!r}): "
                             f"{'ok' if hit else 'miss'}")
                    sleep_or_stop(8)
                except Exception as e:
                    log.warning(f"[region] 搜索失败: {str(e)[:60]}")
                # 开 Segments 图层(带验证与重试)
                seg_ok = False
                for _try in range(3):
                    try:
                        b = page.get_by_role("button", name=re.compile(r"^Segments$", re.I))
                        if b.count() and b.first.is_visible():
                            b.first.click()
                            log.info("[region] 已点 Segments 图层")
                            sleep_or_stop(3)
                            d = page.get_by_role("button", name=re.compile(r"^Done$", re.I))
                            if d.count() and d.first.is_visible():
                                d.first.click()
                                log.info("[region] 已点 Done")
                                sleep_or_stop(2)
                            seg_ok = True
                            break
                        else:
                            log.warning("[region] 没找到 Segments 按钮")
                    except Exception as e:
                        log.warning(f"[region] Segments 点击异常: {str(e)[:50]}")
                    time.sleep(2)
                if not seg_ok:
                    log.warning("[region] Segments 图层未开启")
                # 热力图图层
                try:
                    h = page.get_by_role("button", name=re.compile(r"^Heatmaps?", re.I))
                    if h.count() and h.first.is_visible():
                        h.first.click()
                        log.info("[region] 已点 Heatmaps")
                        sleep_or_stop(2)
                except Exception:
                    pass
                # ---- ★ 用户第3条: 地图必须放大到能看清热力图分布才选路段 ----
                # ★★ 2026-09 真机缺陷修复(实测证据, 纽约州热力图/环境3 会员):
                #   放大级数  | 4 | 5 | 6  | 7 | 8 | 9  | 10 | 11+
                #   引擎认到  |38 |38 | 56 |56 |56 | 21 |  1 |  0
                try:
                    page.mouse.move(700, 400)
                except Exception:
                    pass
                # ★ 真机实测: 放大过头标记会消失(11级后0个), 所以要"边放边数、停在最好的那一级,
                #   一旦变差就回退"。老逻辑(见3个标记就停)能落在4~8级甜点区, 新逻辑放14+4级会放过头。
                best_level, best_n, cur = 0, 0, 0
                for _z in range(ZOOM_MAX_STEPS):        # ZOOM_MAX_STEPS = 12
                    check_stop()
                    page.mouse.wheel(0, -500)
                    sleep_or_stop(2.5)                  # ★ 原来 1.2 秒太快: 瓦片没稳定就截图 -> 大面积超时
                    cur = _z + 1
                    try:
                        mk = find_markers(page)         # 现在可能返回 None
                        n = len(mk) if mk is not None else -1
                    except UserStopped:
                        raise                           # ★ 停止必须立刻生效
                    except Exception as e:
                        # ★ 相对原方案唯一增加的一层保护: 找标记本身出错(如半张损坏截图)
                        #   也只算"未知", 绝不能当 0(否则又往更高级别放大), 更不该整州报废。
                        log.warning(f"[region] {region} 第{cur}级 找标记异常: {str(e)[:60]}")
                        n = -1
                    if n < 0:
                        log.info(f"[region] {region} 第{cur}级 截图失败(未知), 不计入比较")
                        continue
                    if n > best_n:
                        best_n, best_level = n, cur
                    log.info(f"[region] {region} 第{cur}级 标记{n}个 (当前最佳 {best_level}级/{best_n}个)")
                    # ★ 真机对比(同一台机器、同一个纽约视野, 都是点 8 个标记):
                    #     停在第 4 级(38 个标记) -> 只捞出 1 个 ≥5000 的大路段
                    #     放到第 6 级(56 个标记) -> 捞出 4 个(49183/58383/36935/8406)
                    #   原因: 浅层标记多但大多是重叠的小路段。所以"看到标记就收手"必须
                    if cur < ZOOM_MIN_STEPS:
                        continue
                    if best_n >= 3 and n <= max(2, best_n // 2):
                        log.info(f"[region] {region} 标记开始变少({best_n}->{n}), 停止放大")
                        break
                # 回退到最佳级别
                while cur > best_level:
                    check_stop()
                    page.mouse.wheel(0, 500)
                    sleep_or_stop(1.5)
                    cur -= 1
                log.info(f"[region] {region} 自适应缩放: 最佳 {best_level} 级({best_n} 个标记), 现在停在 {cur} 级")
                # ★ 回退后必须再确认一次: 只告警, 绝不因为"标记少"就跳过这个地区
                #   (真机上宁可继续平移找, 也不要 0 产出)
                try:
                    mk = find_markers(page)
                except UserStopped:
                    raise
                except Exception as e:
                    log.warning(f"[region] 回退后找标记异常: {str(e)[:60]}")
                    mk = None
                if mk is None:
                    log.warning("[region] 回退后截图失败, 仍按当前级别继续")
                elif len(mk) < 3:
                    log.warning(f"[region] 回退后只有 {len(mk)} 个标记, 仍继续(后面还会平移找)")
                # ★ 第二批 §2: 死地区跳过 —— 零标记且最佳级别也零标记, 平移也白跑,
                #   直接跳过这个地区(实测每个零产出地区白耗约 6 分钟)。
                # ★★ 语义修正(mk is None 不能算空地区): mk is None = 截图失败 = 标记数
                #   【未知】, 绝不能当成"零标记" —— 这是本引擎自己立的铁律
                #   (find_markers 改成三态返回就是为了它)。把"未知"算进来, 会让连续
                #   4 次截图故障直接触发下面的"停止采集", 白白中止一整轮采集
                #   (真机 0918 一天就有 1198 次截图超时, 完全够触发)。
                if mk is not None and len(mk) == 0 and best_n <= 0:
                    _dry += 1
                    log.warning(f"[region] {region} 零标记零路段, 跳过平移(连续空 {_dry} 个)")
                    if _dry >= 4:
                        log.warning("[region] 连续 4 个空地区, 停止采集")
                        break
                    continue
                _dry = 0
                sleep_or_stop(4)

                dpr = page.evaluate("() => window.devicePixelRatio") or 1
                # ★★ 2026-09-19 用户要求"精准找每个州人数最多的路段":
                #   以前是"点到谁就用谁, 够 4 个就走" —— 明明旁边有 24 万人的路段,
                #   也可能先抓了 4 个 5000 人的小路段就跑了。
                #   现在分两步: ① 先【多采样】(只读达人数, 不当场定夺)
                seg_ids, tried = [], set()
                seg_cands = {}          # sid -> 该路段读到的运动达人数(多次读取最大)
                for rnd in range(_pan_rounds):
                    check_stop()
                    if len(seg_cands) >= max_segments_per_region:
                        break
                    # ★ 真机教训: 16 轮平移要磨 20+ 分钟。采样够 _enough 个
                    #   就停下排名、直接进采集, 别在地图上继续磨。
                    if len(seg_cands) >= _enough:
                        log.info(f"[region] {region} 已采样 {len(seg_cands)} 个路段(够排名了), "
                                 f"停止平移, 直接进采集")
                        break
                    try:
                        mk = find_markers(page)
                    except UserStopped:
                        raise
                    except Exception as e:
                        log.warning(f"[region] {region} 第{rnd+1}轮 找标记异常: {str(e)[:60]}")
                        mk = None
                    # ★ find_markers 三态: None=截图失败(未知)。绝不当成"0 个标记"处理,
                    #   但也【不 break】—— 这一轮照常平移, 下一轮接着找(真机上继续找比空手而归强)。
                    if mk is None:
                        log.warning(f"[region] {region} 第{rnd+1}/{_pan_rounds}轮 截图失败(未知), "
                                    f"本轮跳过, 继续下一轮")
                    else:
                        log.info(f"[region] {region} 第{rnd+1}/{_pan_rounds}轮 标记{len(mk)}个")
                    # ★ 第二批 §2: 死地区在平移阶段也最多试 3 轮(16 轮平移 = 20+ 分钟白跑)
                    if best_n <= 0 and rnd >= 2:
                        log.warning(f"[region] {region} 死地区, 最多试 3 轮")
                        break
                    for (sx, sy) in (mk or []):
                        if len(seg_cands) >= max_segments_per_region:
                            break
                        key = (sx // 20, sy // 20)
                        if key in tried:
                            continue
                        tried.add(key)
                        try:
                            # ★ 2.11: 固定 sleep(1.8) 换成有界轮询(页面快就立刻走);
                            #   sid 必须先置 None —— wait_text/点标记失败时它还是 None,
                            #   下面的 `if not sid ... continue` 才成立。
                            #   ★ 不再套一层 try: on_poll=check_stop 抛的 UserStopped
                            sid = None
                            rate_gate("act")      # ★ 风控闸门: 没有它就不允许单独上 2.11 的提速
                            page.mouse.click(sx / dpr, sy / dpr)
                            # ★ 等待条件绝不能用 /athletes|segments/ 去判 location.href:
                            #   热力图页的地址本身就是 ".../global-heatmap/segments?...",
                            #   那个正则【恒为真】, 等于一秒都不等就去读弹窗 ->
                            #   segment_from_popup 拿不到 -> 路段全被跳过 = 采集 0 人。
                            #   所以这里等的是【弹窗里的路段链接】, 与下面
                            #   segment_from_popup 找的完全是同一个东西; 上限仍 1.8 秒,
                            #   页面快就立刻走。
                            wait_text(page,
                                      "!![...document.querySelectorAll("
                                      "'a[href*=\"/segments/\"]')]"
                                      ".map(function(x){return x.getAttribute('href')||''})"
                                      ".find(function(h){return /\\/segments\\/\\d+/.test(h)})",
                                      timeout=1.8, key="segpop", on_poll=check_stop)
                            sid = segment_from_popup(page)
                            if not sid:
                                continue
                            # ★★ 2026-09-22: 再等一次"运动达人"数渲染出来再读 ★★
                            #   链接(sid)比人数先出现; 只等链接就动手, 会读到 -1,
                            #   上层记 0 —— 用户看到的就是"人数没出来显示就是0"。
                            #   wait_text 是有界轮询: 等到就走, 不白等。
                            wait_text(page, SEG_ATH_READY_JS,
                                      timeout=_ath_wait, key="segath",
                                      on_poll=check_stop)
                            n_ath = popup_athletes(page)
                            stat["seg_total"] += 1
                            # ★ 2026-09-19: 不再当场决定用不用, 只【记录人数参与排名】。
                            #   读不到人数(-1)记 0 —— 排名靠后自然会被淘汰, 但不影响
                            #   其它路段(以前是直接 continue 跳过这一条)。
                            if not isinstance(n_ath, int) or n_ath < 0:
                                log.info(f"[region]   采样路段{sid} 等了 {_ath_wait:g} 秒"
                                         f"仍读不到达人数({n_ath}) -> 记 0")
                                n_ath = 0
                            _prev = seg_cands.get(sid)
                            if _prev is None or n_ath > _prev:
                                seg_cands[sid] = n_ath
                            log.info(f"[region]   采样路段{sid} 运动达人={n_ath}"
                                     f"  (已采样 {len(seg_cands)} 个)")
                        except UserStopped:
                            raise
                        except Exception:
                            continue
                    moves = grid_pan_targets(_pan_rounds)   # ★ 方案A: 蛇形网格扫描
                    try:
                        dx, dy = moves[rnd % len(moves)]
                        rate_gate("act")      # ★ 风控闸门: 拖拽平移同样要限速
                        page.mouse.move(700, 400)
                        page.mouse.down(); page.mouse.move(dx, dy, steps=10); page.mouse.up()
                        sleep_or_stop(3)
                    except UserStopped:
                        raise
                    except Exception:
                        pass

                # ★★ 2026-09-19 用户要求: 按【运动达人数】排名取最大的, 不再先到先得。
                #   只要 >= min_athletes 的, 降序取前 max_segments_per_region 个。
                #   这样"旁边有 24 万人路段却先抓了 4 个 5000 人小段"的情况不会再发生。
                _ranked = sorted(((v, k) for k, v in seg_cands.items()
                                  if v >= min_athletes), reverse=True)
                # ★ 按编号再错开一层(同一个州里, 不同号别抢同一批路段):
                #   并发 N 个号时, 号 k 先取排名里的第 k、k+N、k+2N… 名,
                #   其余的再按原顺序接在后面(不够用的时候照样能用)。
                try:
                    _conc = max(1, int(CONCURRENCY_HINT))
                    _sk = ((int(str(seq).strip()) - 1) % _conc) if seq is not None else 0
                except Exception:
                    _conc, _sk = 1, 0
                if _conc > 1 and _sk:
                    _ranked = _ranked[_sk::_conc] + [
                        _x for _i, _x in enumerate(_ranked) if _i % _conc != _sk]
                seg_ids = [k for _v, k in _ranked[:max_segments_per_region]]
                stat["seg_pass"] = len(seg_ids)
                if _ranked:
                    log.info(f"[region] {region} 路段排名(运动达人 降序): " +
                             " | ".join(f"{k}={v}" for v, k in _ranked[:10]))
                if seg_cands and not seg_ids:
                    log.warning(f"[region] {region} 采样了 {len(seg_cands)} 个路段, 但没有一个 "
                                f">= {min_athletes}(最大 {max(seg_cands.values())}) —— "
                                f"这个地区可能太小, 或者阈值定高了")
                log.info(f"[region] {region} 采用 {len(seg_ids)} 个路段"
                         f"(共采样 {stat['seg_total']} 个 / 候选 {len(seg_cands)} 个)")
                for i, sid in enumerate(seg_ids, 1):
                    if len(collected) >= target_per_account:
                        break                      # ★ 达标即停
                    check_stop()
                    for age in age_groups:
                        if len(collected) >= target_per_account:
                            break                      # ★ 达标即停
                        check_stop()
                        total, rows = fetch_lb_filtered(page, sid, age)
                        if not rows:
                            # ★ 2026-09-19 用户报"选了三个年龄, 好像只采了一个":
                            #   这个年龄组榜单返回空时, 原来【一声不响就 continue】,
                            #   日志里那一段直接消失, 看起来就像"被跳过了"。
                            #   其实三个年龄组都问了, 只是这一次没数据。补一行日志。
                            log.info(f"[region] [{i}/{len(seg_ids)}] 路段{sid} "
                                     f"年龄{age}: 本月榜单【无人】(跳过这个年龄组, "
                                     f"继续下一个)")
                            continue
                        # ---- ★ 候选人清单: 不再用 max_check_per_segment 截断 ----
                        # (那个小上限只当"防止跑飞"的安全上限, 不决定采集量)
                        _pend, _dup = [], set()
                        for _r in rows:
                            _a = str(_r.get("aid") or "")
                            if not _a or _a in seen or _a in _dup:
                                continue
                            _dup.add(_a)
                            _pend.append({"aid": _a, "name": _r.get("name", "")})
                        log.info(f"[region] [{i}/{len(seg_ids)}] 路段{sid} 年龄{age}: "
                                 f"本月男性 {total} 人, 待查 {len(_pend)} 人 "
                                 f"(已合格 {len(collected)}/{target_per_account})")
                        _mine_set = set()
                        for _k, _c in enumerate(_pend):
                            check_stop()
                            if len(collected) >= target_per_account:
                                break                  # ★ 达标即停: 不再多查一个人
                            aid = _c["aid"]
                            if aid in seen:
                                continue
                            # ---- 先领: 问清这批人里哪些归我处理(分批, 见 CLAIM_CHUNK) ----
                            if cli is not None and aid not in _mine_set:
                                _batch = [x["aid"] for x in _pend[_k:_k + CLAIM_CHUNK]
                                          if x["aid"] not in seen and x["aid"] not in _mine_set]
                                try:
                                    _mine, _skipped = claim_pick(cli, seen, _batch)
                                except ServerDown as e:
                                    # 领不到就停 —— 绝不退化成"本地去重继续跑"
                                    log.error(f"[claim] 领取失败, 采集中止: {str(e)[:100]}")
                                    raise
                                _mine_set.update(str(x) for x in (_mine or []))
                                if _skipped:
                                    stat["taken"] = stat.get("taken", 0) + _skipped
                                    log.info(f"[claim] 本批 {len(_batch)} 人: 归我 {len(_mine)}, "
                                             f"已被处理跳过 {_skipped}")
                                if aid not in _mine_set:
                                    continue           # 没领到 -> 零流量跳过
                            stat["checked"] += 1
                            ok, why = check_athlete(page, aid, max_followers,
                                                    geo_filter=_geo, center=center,
                                                    exempt_max=_exempt,
                                                    recent_days=_recent)
                            # ★★ 真机教训(2026-09-19 01:17 实测): 浏览器被关掉之后,
                            #   check_athlete 会把【每一个人】都读成"读不到数据", 于是引擎
                            #   带着一个死页面把剩下的几百个候选人一个一个刷完, 再白跑下一个
                            #   路段、下一个地区 —— 日志一路刷 "Target page ... has been closed",
                            if (not ok) and why and "读不到数据" in why:
                                _dead = stat.get("dead_streak", 0) + 1
                                stat["dead_streak"] = _dead
                                if _dead >= 3 and not page_alive(page):
                                    log.error("[region] ★ 浏览器/页面已关闭, 采集整体中止"
                                              "(继续跑只会白刷, 不是这批人的问题)")
                                    raise BrowserGone("浏览器已关闭/连接断开")
                            else:
                                stat["dead_streak"] = 0
                            # ★ 2.2: 判重在前、记账在后 —— append_task_url 返回 False
                            #   说明历史成果里已有这个人, 不计数、不重复写、不重复上报。
                            if ok and append_task_url(
                                    _sub, f"https://www.strava.com/athletes/{aid}",
                                    extra=f"{aid}\t{region}\t{sid}\t{age}"):
                                seen[aid] = "pass"
                                stat["pass"] += 1
                                _rec = {"aid": aid, "name": _c.get("name", ""),
                                        "url": f"https://www.strava.com/athletes/{aid}",
                                        "region": region, "segment": sid, "age": age,
                                        "written": True}
                                collected.append(_rec)
                                log.info(f"[quota] 合格 {len(collected)}/{target_per_account}"
                                         f"  [{region}] {str(_c.get('name',''))[:20]} {why}")
                            elif ok:
                                if _sub.get("write_err"):
                                    # ★ 落盘失败("假 False")—— 这条成果【没写进去】,
                                    #   绝不能给中心报 pass, 否则就是"中心说采到了、
                                    #   本地没有"的新缝。留成 pending 让别人重来。
                                    log.error(f"[region] 落盘失败, 本条不上报中心: {aid}"
                                              f" ({_sub.get('write_err')})")
                                    continue
                                # 本地已有: 不计数、不重复写, 但必须 finish, 否则中心
                                # 会留下新的 pending 黑洞(下次被别人重领 = 重复采集)
                                stat["dup_local"] = stat.get("dup_local", 0) + 1
                                log.info(f"[region]   本地已有, 跳过不计数: {aid}"
                                         f" (累计 {stat['dup_local']})")
                                if cli is not None:
                                    try:
                                        cli.finish(aid, "pass", note="本地已有(回灌)",
                                                   name=_c.get("name", ""))
                                    except ServerDown as e:
                                        log.error(f"[claim] 上报失败, 采集中止: {str(e)[:80]}")
                                        raise
                                continue
                            else:
                                # O1: 淘汰也要记住 —— 否则换个人/换条路段会被反复重查
                                # (真实日志: 65.3% 的资料页访问都是淘汰, 这部分原本全白跑)
                                # 注意: "读不到数据"是临时故障, 不记, 留待下次重试
                                if why and "读不到数据" not in why:
                                    seen[aid] = "reject"
                                stat["reject"] = stat.get("reject", 0) + 1
                                log.info(f"[region]   [NO] {str(_c.get('name',''))[:20]} {why}")
                            # ---- 后报: 结果上报中心(合格/淘汰都报), 别人就不会再查 ----
                            if cli is not None:
                                try:
                                    if ok:
                                        cli.collect(aid, f"https://www.strava.com/athletes/{aid}",
                                                    name=_c.get("name", ""), region=region,
                                                    segment=sid, age=age)
                                        cli.finish(aid, "pass", note=why,
                                                   name=_c.get("name", ""))
                                    elif why and "读不到数据" not in why:
                                        cli.finish(aid, "reject", note=why,
                                                   name=_c.get("name", ""))
                                    else:
                                        cli.finish(aid, "error", note=why)   # 可重试
                                except ServerDown as e:
                                    log.error(f"[claim] 上报失败, 采集中止: {str(e)[:80]}")
                                    raise
                            time.sleep(random.uniform(1.5, 3))
                        if len(collected) >= target_per_account:
                            break                      # ★ 达标即停
                        time.sleep(random.uniform(1, 2))
            except UserStopped:
                raise            # 用户点了停止: 别当成"这个州出错"然后继续下一个州
            except ServerDown:
                # ★ 服务端挂了 = 去重不可用 -> 必须整体中止。
                #   以前它会掉进下面的 except Exception, 被当成"这个地区出错"
                #   然后继续跑下一个地区 —— 十几个地区白跑几十分钟, 日志却写着"中止"。
                raise
            except BrowserGone:
                # ★ 同上: 浏览器已经没了, 继续跑后面的地区只会一直刷失败日志
                raise
            except Exception as e:
                log.warning(f"[region] {region} 异常: {str(e)[:80]}")

    finally:
        # ★ 单条已经在采集时就写进本任务的明细文件了(见 append_task_url); 这里只补写
        #   没写成功的, 判重同样交给 append_task_url 统一做
        _rest = [c for c in collected if not c.get("written")]
        if _rest:
            try:
                for c in _rest:
                    append_task_url(_sub, c["url"],
                                    extra=f"{c.get('aid','')}\t{c.get('region','')}"
                                          f"\t{c.get('segment','')}\t{c.get('age','')}")
            except Exception as e:
                log.warning(f"[region] 补写落盘失败: {str(e)[:60]}")
        try:
            save_seen(seen)
        except Exception as e:
            log.warning(f"[region] 记录保存失败: {str(e)[:60]}")
        # ★ 用户第4条: 硬性 200 —— 达标/未达标都必须明明白白写进日志, 不许静默
        if len(collected) >= target_per_account:
            log.info(f"[quota] ★ 已达标 {len(collected)}/{target_per_account}, 停止采集")
        else:
            log.warning(f"[quota] 只采到 {len(collected)}/{target_per_account} 未达标"
                        f"(计划地区已跑完: {len(_plan_names)} 个)")
        log.info(f"[region] 完成: 看路段{stat['seg_total']} 采用{stat['seg_pass']} | "
                 f"检查{stat['checked']}人 合格{stat['pass']}人 淘汰{stat.get('reject',0)}人"
                 f" | 服务端已处理跳过{stat.get('taken',0)}人 | 累计记录{len(seen)}人")
        # ★ 2.2: 汇总只对"本函数自己建的任务"做 —— 界面传进来的任务由界面统一收尾
        if _auto_task:
            try:
                finalize_task(task)
            except Exception as _e:
                log.warning(f"[task] 任务汇总失败: {str(_e)[:60]}")
    return collected


# ==================== GUI 适配层 ====================
# ---------------------------------------------------------------- 名字库
# ★★ 2026-09-20 用户提供「美国华人女性名字1000个(带常见华人姓氏)」, 要求放进脚本 ★★
#   原来 FIRST×LAST 各 50 个、两边【同步取模】(FIRST[i%50] LAST[i%50]),
#   i=0..49 一一对应 -> 实际只产出【50 个】名字: 编号 1 和 51 是同一个。
#   现在从 name_bank.NAMES(1000 个)里取, 编号不撞名字就不撞。
#   下面这份 50 个的【保留做兜底】: name_bank 万一丢了也不会出现空名字。
_LEGACY_FIRST = ['Emily','Sophia','Olivia','Ava','Emma','Mia','Isabella','Grace','Chloe','Lily',
                 'Hannah','Sarah','Jessica','Michelle','Jennifer','Amy','Lucy','Anna','Alice','Ruby',
                 'Eva','Ivy','Zoe','Nora','Stella','Claire','Ella','Aria','Aubrey','Hazel','Violet',
                 'Aurora','Savannah','Brooklyn','Bella','Clara','Elena','Nina','Ariana','Maya','Luna',
                 'Nova','Iris','Elise','Fiona','Georgia','Holly','Irene','Julia','Karen','Laura']
_LEGACY_LAST = ['Chen','Lin','Huang','Zhang','Li','Wang','Liu','Yang','Zhao','Wu','Zhou','Xu','Sun',
                'Ma','Zhu','Hu','Guo','He','Luo','Liang','Zheng','Xie','Han','Tang','Feng','Dong',
                'Xiao','Cheng','Cao','Yuan','Deng','Fu','Shen','Zeng','Peng','Lv','Su','Lu','Jiang',
                'Cai','Jia','Ding','Wei','Xue','Ye','Yu','Pan','Du','Dai']
_LEGACY_50 = [f"{_LEGACY_FIRST[i % len(_LEGACY_FIRST)]} "
              f"{_LEGACY_LAST[i % len(_LEGACY_LAST)]}" for i in range(50)]

try:
    from name_bank import NAMES as _NAME_BANK
    NAMES = [str(x).strip() for x in _NAME_BANK if str(x).strip()]
except Exception as _nb_err:
    print(f"[names] ★ 名字库 name_bank.py 读不到({_nb_err}); 退回内置 50 个")
    NAMES = list(_LEGACY_50)


def english_names(n=None):
    """名字表。传 n 就取前 n 个(兼容老调用方), 不传返回全部。"""
    if n is None:
        return list(NAMES)
    try:
        n = int(n)
    except Exception:
        n = 50
    if n <= 0:
        n = 50
    if n <= len(NAMES):
        return list(NAMES[:n])
    out = []
    while len(out) < n and NAMES:
        out.extend(NAMES)
    return out[:n] or list(_LEGACY_50[:n])


def name_for_seq(seq):
    """按编号取名字: 在【整个名字库】里取, 不再卡在 50 个上。
    ★ 与 run_one_seq 用的是同一个函数, 预览和实跑不会再对不上。
    """
    try:
        _s = int(str(seq).strip())
    except Exception:
        _s = 1
    if not NAMES:
        return _LEGACY_50[(_s - 1) % 50]
    return NAMES[(_s - 1) % len(NAMES)]


def pick_avatars(folder, n=50):
    files = sorted([x for x in Path(folder).glob("*.jpg") if not x.name.startswith("signal-")])
    if not files:
        files = sorted(Path(folder).glob("*.jpg")) + sorted(Path(folder).glob("*.png"))
    return files[:n]


def _looks_email(s):
    """这串文字看起来像不像一个邮箱(用来判断"环境名字"到底是账号还是备注)。

    ★ 2026-09-20 用户实测: 有的环境名字写的是 "跑步26 N" 这种标签, 不是账号。
      以前直接把它当账号填进表格, 用户看到"账号"列里躺着个中文名。
    """
    t = str(s or "").strip()
    if not t or len(t) > 80 or " " in t:
        return False
    return bool(re.fullmatch(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+", t))


def list_items():
    """列出所有 ADS 环境"""
    out = []
    for u in ads_list():
        try:
            seq = int(u.get("serial_number"))
        except Exception:
            continue
        # ★★ 2026-09-20 用户要求: 账号列自动识别, 不是账号的文字放进备注 ★★
        #   实测: AdsPower 的"环境名字"栏两种都有人写 ——
        #     写了邮箱的 -> 应该当账号
        #     写了标签的(环境 376 的名字是 "跑步26 N") -> 应该当备注, 不是账号
        _nm = str(u.get("name") or "").strip()
        _rk = str(u.get("remark") or "").replace("\n", " ").strip()
        if _looks_email(_nm):
            _email, _note, _pw = _nm, _rk[:40], ""
        else:
            _e2, _p2 = parse_remark(_rk) if _rk else (None, None)
            _email = (_e2 or "").strip()
            _pw = (_p2 or "").strip()
            _note = " | ".join(x for x in (_nm, _rk) if x)[:60]
            if not _email:
                log.info(f"[list] 环境 {seq} 的名字不是邮箱({_nm!r}), "
                         f"已放进备注; 备注里也没找到邮箱 -> 账号留空")
        out.append({"seq": seq, "win": str(seq),
                    "note": _note, "email": _email, "password": _pw})
    return sorted(out, key=lambda x: x["seq"])


def scan_should_close():
    """扫描完一个号, 是否关闭它的浏览器。**默认关**。

    ★★ 2026-09-19 用户要求:「扫描完成自动关闭当前此号码的浏览器, 不然内存扛不住」★★
      原来 ADS 版这里读的是 auto_close —— 那是【任务完成时】关不关的开关
      (界面上"完成关浏览器"那个勾选框), 而 配置/config.json 里它是 false,
      于是扫描时【一个号都不关】: 扫 30 个号就开 30 个浏览器, 内存直接扛不住。

      扫描是"开一个、看完就关"的短平快动作, 和"任务整体跑完关不关"是两件事,
      【不能共用一个开关】—— 共用就会出现"我去掉了任务那个勾, 结果扫描也不关了"。

      现在: 独立配置键 scan_close, 默认 true(关)。
            真要留着窗口自己看, 把 config.json 的 scan_close 设成 false。
    """
    v = CFG.get("scan_close")
    if v is None:
        return True                 # 没配 -> 默认关(用户口径)
    try:
        return bool(v)
    except Exception:
        return True


def scan_one(seq):
    """扫描单个 ADS 环境"""
    prof = ads_find(profile_no=str(seq))
    if not prof:
        return None
    uid = prof.get("user_id")
    ws = ads_open(uid)
    reset_goto_guard(seq)   # 扫描也重置导航去重,避免复用上一次的页面记账
    r = {"login": "否", "name": "", "city": "", "acts": "", "prem": "", "priv": ""}
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # ★ 开号时先清一遍: 这个环境上一次跑完可能还留着别的标签
            close_extra_pages(page, tag=f" [{seq}]")
            logged = is_logged_in(page)
            r["login"] = "是" if logged else "否"
            if logged:
                goto_retry(page, "https://www.strava.com/settings/profile")
                time.sleep(3)
                h = page.content()
                import re as _re
                m = _re.search(r'firstname:\s*"([^"]*)"', h)
                fn = m.group(1) if m else ""
                m = _re.search(r'lastname:\s*"([^"]*)"', h)
                ln = m.group(1) if m else ""
                m = _re.search(r'city:\s*"([^"]*)"', h)
                r["name"] = f"{fn} {ln}".strip()
                r["city"] = m.group(1) if m else ""
                _p = is_premium(page)
                # ★ 三态: 读不到写 "?", 界面会保留原值 —— 绝不用一个假的"否"
                #   把表格里已知的"是"覆盖掉。
                r["prem"] = ("是" if _p is True else ("否" if _p is False else "?"))
                r["acts"] = str(profile_activity_count(page))
                try:
                    g = page.evaluate(r"""() => ({g:(document.querySelector("input[name='group_activity_visibility'][value='no_one']")||{}).checked,
                      m:(document.querySelector('#default-activity-map-visibility')||{}).checked,
                      s:(document.querySelector('#start_time')||{}).checked})""")
                    r["priv"] = f"小组{g.get('g')}/地图{g.get('m')}/时间{g.get('s')}"
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"[scan] {seq} err: {str(e)[:80]}")
    finally:
        # ★★ 2026-09-19 用户要求:「扫描完成自动关闭当前此号码的浏览器,
        #    不然内存扛不住」★★
        #   注意这里【不再看 auto_close】—— 那是"任务完成时"的开关(界面上的
        #   "完成关浏览器"勾选框), 和"扫描完这一个号要不要关"是两件事。
        if scan_should_close():
            try:
                ads_close(uid)
                log.info(f"[scan] {seq} 扫描完成, 已关闭该号浏览器")
            except Exception as _e:
                # 关不掉不影响扫描结果, 但要说一声(可能是浏览器本来就被关了)
                log.warning(f"[scan] {seq} 关闭浏览器失败(不影响本次结果): "
                            f"{str(_e)[:60]}")
        else:
            log.info(f"[scan] {seq} scan_close=false -> 保留浏览器不关"
                     f"(想让它自动关, 把 config.json 的 scan_close 设成 true)")
    return r


def run_one_seq(seq, email, pwd, cfg, task=None):
    # ★ 2.12: 并发号数写进进程内全局(只取最大值)。并发时网速样本互相污染,
    #   _net_scale 会把所有 timeout 放大到 48000ms -> 白等 10.5 分钟/号。
    global CONCURRENCY_HINT
    try:
        _jobs = int(cfg.get("jobs") or 1)
    except Exception:
        _jobs = 1
    if _jobs > CONCURRENCY_HINT:
        CONCURRENCY_HINT = _jobs
    # ★ 真机实测(2026-09-18 23:32): 外部脚本/命令行把 seq 传成字符串 "3" 时,
    #   下面 `avs[(seq - 1) % len(avs)]` 直接 TypeError: str - int, 整个采集
    #   一步都没跑就退出(界面走的是整数所以没暴露, 但引擎自己用 str(seq) 找环境,
    #   说明它本来就允许字符串)。这里统一兜成 int, 两种调用方都不会再炸。
    try:
        seq = int(str(seq).strip())
    except Exception:
        pass
    """GUI 调用:跑单个 ADS 环境

    ★ cfg["task_mode"] 决定做哪几步(和旧界面的「执行内容」一致):
        全部(资料+隐私+轨迹) / 仅资料+隐私 / 仅隐私 / 仅上传轨迹
      原理: run_one() 看 pending_todo() 排步骤, 而 pending_todo 是按
      "传进来的参数是不是 None" 判断的 —— 所以不要的步骤把参数置 None
      即可跳过。这是引擎本来就支持的用法, 没有改动采集核心逻辑。
    """
    avs = pick_avatars(cfg.get("avatar_dir") or CFG.get("avatar_dir"), 50)
    av = str(avs[(seq - 1) % len(avs)]) if avs else ""
    nm = name_for_seq(seq)      # ★ 1000 个名字里取
    loc = cfg.get("location")
    gpx = cfg.get("gpx_dir")

    _m = str(cfg.get("task_mode") or "").strip()
    if _m == "仅隐私":
        nm, av, loc, gpx = None, None, None, None
    elif _m == "仅上传轨迹":
        nm, av, loc, gpx = None, None, None, gpx
    elif _m == "仅资料+隐私":
        gpx = None
    log.info(f"[mode] {seq} 执行内容: {_m or '全部(资料+隐私+轨迹)'}")

    return run_one(str(seq), email, pwd, nm, loc, av, gpx,
                   auto_close=cfg.get("auto_close"),
                   per_batch=cfg.get("per_batch"),
                   daily_cap=cfg.get("daily_cap"), task=task)


def collect_one(seq, cfg, task=None):
    """GUI 调用:只采集(区域采集:多州/男性/本月/粉丝关注<200)

    ★ 返回值从 True/False 改成 dict:
      用户明确要求"不管开始任务还是扫描任务, 都要自动把数据填入脚本"。
      以前这里只返回真假, 「◎ 只采集」跑完表格那几列还是空的。
      现在把这次真正读到的 登录/名字/城市/活动数/会员 一并返回,
      界面拿去自动填表格(和「▶ 开始任务」走同一套回填)。

    ★ task(2.5): 界面那一次任务的任务上下文; 不传(None)则 collect_regions
      自己建一个自己的任务文件, 老界面照样能跑。
    """
    # ★ 2.12: 并发号数写进进程内全局(只取最大值)。并发时网速样本互相污染,
    #   _net_scale 会把所有 timeout 放大到 48000ms -> 白等 10.5 分钟/号。
    global CONCURRENCY_HINT
    try:
        _jobs = int(cfg.get("jobs") or 1)
    except Exception:
        _jobs = 1
    if _jobs > CONCURRENCY_HINT:
        CONCURRENCY_HINT = _jobs
    res = {"win": str(seq), "login": False, "steps": ["采集"],
           "name": "", "city": "", "acts": "", "prem": "", "priv": "",
           "ok": False, "error": ""}
    prof = ads_find(profile_no=str(seq))
    if not prof:
        log.warning(f"[collect] 找不到环境 {seq}")
        res["error"] = "找不到环境"
        return res
    # ★ fail-closed: 无条件去连中心服务, 连不上就放弃本次采集。
    #   以前这里先看 CFG 里有没有 claim_server 这个键 —— 一旦该键为空,
    #   make_claim_client 根本不会被调用, 于是"连不上就取消"整条失效,
    #   直接退化成本地去重(和比特版行为相反)。
    _hint = f"PC{int(seq):02d}" if str(seq).isdigit() else f"PC{seq}"
    _cli = make_claim_client(hint=_hint)
    if _cli is None:
        log.error("[collect] 领取服务不可用 —— 为防止多机重复, 本次采集取消")
        res["error"] = "领取服务不可用, 已取消(防重复)"
        return res
    uid = prof.get("user_id")
    ws = ads_open(uid)
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # ★ 开号时先清一遍: 这个环境上一次跑完可能还留着别的标签
            close_extra_pages(page, tag=f" [{seq}]")
            if not is_logged_in(page):
                log.warning(f"[collect] {seq} 未登录")
                res["error"] = "未登录"
                return res
            res["login"] = True
            # ★ 先判会员, 但**两种情况下页面都停在 /settings/profile**, 所以
            #   不管是不是会员都把真实资料读一遍 —— 非会员也要能把表格填上
            #   (以前非会员直接 return, 名字/城市/活动数就一直空着)。
            _prem = is_premium(page)
            # ★ 三态(2026-09-19 修): True->是 / False->否 / None(读不到)->"?"
            #   旧写法 `"是" if _prem else "否"` 会把"读不到"也写成"否",
            #   而界面把"否"当有效值 -> 直接把表格里正确的"是"冲掉。
            res["prem"] = ("是" if _prem is True
                           else ("否" if _prem is False else "?"))
            # ★ is_premium() 结束时页面正停在 /settings/profile, 顺手读真实
            #   姓名/所在地(零额外跳转), 填给界面 —— 只读, 不改页面
            try:
                _ri = read_settings_info(page)
                res["name"] = _ri.get("name") or ""
                res["city"] = _ri.get("location") or ""
            except Exception:
                pass
            # 活动数: 表格要这一列(控制面板)
            try:
                _n = profile_activity_count(page)
                if isinstance(_n, int) and _n >= 0:
                    res["acts"] = str(_n)
            except Exception:
                pass
            # 城市兜底: 页面没读到就用 state 里记过的, 再不济用配置目标城市
            if not res["city"]:
                try:
                    _stc = load_state().get(task_state_key(seq), {}) or {}
                    res["city"] = str(_stc.get("location") or "").strip()
                except Exception:
                    pass
            if not res["city"]:
                res["city"] = str(cfg.get("location") or "").strip()
            if _prem is None and not page_alive(page):
                # ★ 断线 ≠ 非会员: 绝不能让它伪装成"非会员跳过"(真机踩过)
                log.error(f"[collect] {seq} 浏览器/页面已关闭, 本次采集取消(不是非会员)")
                res["error"] = "浏览器已关闭/连接断开"
                return res
            if _prem is False:
                log.info(f"[collect] {seq} 非会员,跳过采集(表格已填)")
                res["ok"] = True        # 非会员不算失败, 只是没东西可采
                return res
            if _prem is None:
                # ★ 读不到会员状态 -> 照采, 不跳过。
                #   取舍: 白跑一轮只是浪费时间; 跳过则可能把整个会员号的
                #   采集成果静默清零 —— 后者代价大得多。
                log.warning(f"[collect] {seq} 会员状态读不到, 按会员处理继续采集(不跳过)")
            collect_regions(page,
                            regions=cfg.get("collect_regions"),
                            # ★ 2026-09-19: 年龄组/性别/时间 都从界面传进来的 cfg 取
                            #   (界面上那三个框框)。★ 必须走 cfg 而不是全局 CFG ——
                            #   界面的 _cfg() 只【返回】字典, 不写 config.json,
                            #   而 CFG 是引擎导入时的一次性快照。只读 CFG 的话,
                            age_groups=cfg.get("collect_age_groups"),
                            lb_gender=cfg.get("collect_gender"),
                            lb_date_range=cfg.get("collect_date_range"),
                            min_athletes=int(cfg.get("min_athletes")
                                             or CFG.get("min_athletes")
                                             or MIN_ATHLETES_FLOOR),
                            max_followers=int(cfg.get("max_followers")
                                              or CFG.get("max_followers") or 200),
                            target_per_account=int(
                                cfg.get("collect_target_per_account")
                                or CFG.get("collect_target_per_account")
                                or TARGET_FLOOR),
                            max_segments_per_region=int(
                                cfg.get("segs_per_region")
                                or CFG.get("segs_per_region") or 0) or SEGS_PER_REGION_CAP,
                            cli=_cli,
                            geo_filter=bool(cfg.get("geo_filter",
                                                    CFG.get("geo_filter", True))),
                            home_loc=detect_home_loc(page, seq, cached=res.get("city")),
                            auto_regions=bool(cfg.get("collect_auto_regions",
                                                      CFG.get("collect_auto_regions", True))),
                            # ★ 2026-09-24: 界面给这个号【单独指定了地区】-> 只采它。
                            #   不然"纽约必扫 + 全美自动撒网"会把指定的地区挤没,
                            #   用户看到的就是"还是按默认地区采的"。
                            only_regions=bool(cfg.get("collect_only_regions", False)),
                            task=task,       # ★ 2.5: 界面建的任务上下文透传下去
                            seq=seq)         # ★ 号级明细按编号命名(_<号>.txt)
        res["ok"] = True
    except Exception as _e:
        # ★ 以前这里没有 except: 异常冒到界面, 而界面无条件打印"采集完成",
        #   于是"一条都没采到"也会显示成功。现在把结果如实返回。
        log.warning(f"[collect] {seq} 采集异常: {str(_e)[:100]}")
        res["error"] = str(_e)[:80]
    finally:
        if cfg.get("auto_close", True) or STOP_EVENT.is_set():
            ads_close(uid)
    return res


# ★ 命令行入口必须放在文件最后: collect_regions / detect_home_loc / geo_* 等
#   都定义在 main() 之后, 若这里提前执行 main(), 走采集分支时会
#   NameError: collect_regions is not defined (命令行入口曾因此完全失效)。
if __name__ == "__main__":
    main()

