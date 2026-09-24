# -*- coding: utf-8 -*-
"""一键检查 —— 同事双击这一个就行。

把三件事一次查完:
  ① 更新到位了吗   (版本号 / 各文件在不在 / 服务端连不连得上)
  ② 成果文档在哪   (引擎认定写哪 / 全盘搜是不是写别处了)
  ③ 为什么没采到   (领取服务 / claim_client / 日志关键行)

产物: 桌面上的  检查结果_<机器名>_<时间>.txt  —— 发给管理员即可(密钥已打码)
"""
import datetime
import json
import os
import pathlib
import socket
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout,):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
NOW = datetime.datetime.now()
TODAY = NOW.strftime("%Y%m%d")
STAMP = NOW.strftime("%Y%m%d_%H%M%S")
MACHINE = os.environ.get("COMPUTERNAME") or "PC"
OUT = pathlib.Path.home() / "Desktop" / ("检查结果_%s_%s.txt" % (MACHINE, STAMP))
# ★ 同时写一个英文名: .bat 的提示必须是纯 ASCII(项目铁律), 里面写中文会乱码,
#   所以它提示 CheckResult_*.txt, 这里就跟着产出一份同内容的文件, 两边对得上。
OUT_EN = pathlib.Path.home() / "Desktop" / ("CheckResult_%s_%s.txt" % (MACHINE, STAMP))
L = []


def w(s=""):
    L.append(str(s))
    print(s)


def rule(t):
    w("")
    w("=" * 76)
    w(t)
    w("=" * 76)


def mask(v):
    s = str(v or "")
    return "(空)" if not s else (s[:6] + "..." + s[-4:] + "(长度%d)" % len(s))


# 各文件可能在哪: 平铺包全在根目录; 开发目录在 主脚本/ 界面/
PY_FILES = ("strava_ads.py", "strava_bit.py", "claim_client.py",
            "update.py", "geo_cities.py", "_gui_ads.py", "_gui_bit.py")
GUI_FILES = ("ADS自动化.py", "比特派自动化.py", "启动.bat", "Start_AdsPower.bat")
CFG_CANDS = ("config.json", "配置/config.json",
             "../配置/config.json", "../config.json")


def find_one(name):
    for c in (HERE / name, HERE / "主脚本" / name, HERE / "界面" / name):
        if c.is_file():
            return c
    return None


def find_cfg():
    for rel in CFG_CANDS:
        c = (HERE / rel).resolve()
        if c.is_file():
            return c
    return None


def data_dir_of(cfg_path):
    """照抄引擎的 _find_data_dir"""
    if (HERE / "config.json").exists():
        return HERE, "平铺(config.json 与脚本同级)"
    for d in (HERE / "数据", HERE.parent / "数据"):
        if d.is_dir():
            return d, "分层(有 数据/ 目录)"
    return HERE, "兜底(两者都没有)"


def main():
    w("检查结果 —— %s @ %s" % (MACHINE, NOW.strftime("%Y-%m-%d %H:%M:%S")))
    w("(发给管理员; 密钥已打码)")

    cfg_p = find_cfg()
    cfg = {}
    if cfg_p:
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        except Exception:
            pass

    # ================= 一、版本 =================
    rule("一、更新到位了吗")
    w("  脚本目录: %s" % HERE)
    w("  读到的配置: %s" % (cfg_p or "★ 找不到 config.json"))
    vf = HERE / "._pkg_version"
    local_v = vf.read_text(encoding="utf-8").strip() if vf.is_file() else ""
    w("  本地版本号: %s" % (local_v or "★ 没有(说明从没更新成功过)"))
    w("")
    w("  关键文件:")
    for n in PY_FILES + GUI_FILES:
        p = find_one(n)
        if p:
            w("     %-22s 在   %9d B   %s"
              % (n, p.stat().st_size, "" if p.parent == HERE else "(%s/)" % p.parent.name))
        else:
            w("     %-22s ★ 不在" % n)
    # strava_ads 里有没有新版标记 —— 一眼看出是新是老
    eng = find_one("strava_ads.py")
    if eng:
        t = eng.read_text(encoding="utf-8", errors="replace")
        MARKS = [("只要美国境内", "def is_us_location"),
                 ("年龄只留55+", "AGE_GROUPS_MIN_ALLOWED"),
                 ("一天一个文件", "def _daily_path"),
                 ("文件名链接-", 'DAILY_FILE_PREFIX = "链接-"'),
                 ("扫描关浏览器", "def scan_should_close"),
                 ("AdsPower key自愈", "def ads_headers"),
                 ("会员三态", "_prem is not False")]
        w("")
        w("  引擎里的新版功能(有=是新版):")
        for name, mark in MARKS:
            w("     %-18s %s" % (name, "有 ✓" if mark in t else "★ 没有(老版本)"))

    w("")
    srv = str(cfg.get("claim_server") or "").rstrip("/")
    key = str(cfg.get("claim_key") or "")
    w("  服务器: %s" % (srv or "★ 配置里没有"))
    if srv:
        u = urllib.parse.urlparse(srv)
        try:
            sk = socket.create_connection((u.hostname, u.port or 80), timeout=10)
            sk.close()
            w("     端口: 通 ✓")
        except Exception as e:
            w("     端口: ★ 不通 %s" % str(e)[:50])
        try:
            r = urllib.request.Request(srv + "/pkg/manifest",
                                       headers={"X-API-Key": key})
            with urllib.request.urlopen(r, timeout=25) as resp:
                m = json.loads(resp.read().decode())
            w("     服务器版本: %s (%d 个文件)" % (m.get("version"), m.get("count")))
            if local_v and m.get("version"):
                w("     %s" % ("✓ 已是最新" if local_v == m["version"]
                               else "★ 本地 %s != 服务器 %s —— 还没更新到位"
                                    % (local_v, m["version"])))
        except Exception as e:
            w("     ★ 取清单失败: %s" % str(e)[:70])

    # ================= 二、成果文档 =================
    rule("二、成果文档在哪")
    dd, why = data_dir_of(cfg_p)
    w("  引擎认定的数据目录: %s" % dd)
    w("  依据: %s" % why)
    w("  >>> 成果文档应该在这里: %s"
      % (dd / ("链接-%s.txt" % TODAY)))
    w("")
    if dd.is_dir():
        fs = sorted([p for p in dd.iterdir() if p.is_file()],
                    key=lambda p: p.stat().st_mtime, reverse=True)
        w("  该目录有 %d 个文件, 最近 8 个:" % len(fs))
        for p in fs[:8]:
            w("     %-42s %9d B" % (p.name, p.stat().st_size))
    else:
        w("  ★ 该目录不存在!")
    w("")
    w("  全盘搜成果文档(看是不是写到别处了):")
    CAND = [HERE, HERE.parent, HERE / "数据", HERE.parent / "数据",
            HERE / "主脚本", pathlib.Path.home() / "Desktop",
            pathlib.Path.home() / "Desktop" / "数据",
            pathlib.Path.home() / "Documents"]
    seen, hit_any = set(), False
    for d in CAND:
        try:
            if not d.is_dir() or d.resolve() in seen:
                continue
            seen.add(d.resolve())
        except Exception:
            continue
        hits = []
        for pat in ("链接-*.txt", "collected_users*.txt"):
            hits += list(d.glob(pat))
        if hits:
            hit_any = True
            w("     【%s】%d 个:" % (d, len(hits)))
            for p in sorted(hits, key=lambda x: x.stat().st_mtime,
                            reverse=True)[:6]:
                w("        %-38s %9d B" % (p.name, p.stat().st_size))
    if not hit_any:
        w("     ★ 一个都没找到 —— 那文档是真没生成")

    # ================= 三、为什么没采到 =================
    rule("三、为什么没采到")
    cc = find_one("claim_client.py")
    if cc is None:
        w("  claim_client.py: ★ 找不到")
        w("     -> 会导致所有号【领取服务不可用, 本次采集取消】, 一条都不采")
    else:
        w("  claim_client.py: 在 (%d B)" % cc.stat().st_size)
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_cc", cc)
            mm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mm)
            w("     能 import: ✓ ClaimClient=%s" % getattr(mm, "ClaimClient", None))
        except Exception as e:
            w("     ★ import 失败: %s" % str(e)[:90])
            w("        -> 这一条就足以让所有号采集被取消")
    w("")
    w("  关键设置:")
    for k in ("collect_enabled", "us_only", "us_only_strict", "min_athletes",
              "min_athletes_floor", "collect_regions", "collect_age_groups",
              "collect_date_range", "collect_target_per_account", "jobs"):
        w("     %-28s = %r" % (k, cfg.get(k)))
    for k in ("adspower_key", "bitbrowser_key", "claim_key"):
        w("     %-28s = %s" % (k, mask(cfg.get(k))))

    w("")
    logs = []
    for d in (HERE / "logs", HERE.parent / "logs", HERE / "主脚本" / "logs"):
        if d.is_dir():
            logs += sorted(d.glob("run_*.log"))
    if not logs:
        w("  日志: ★ 找不到 run_*.log")
    else:
        newest = max(logs, key=lambda p: p.stat().st_mtime)
        txt = newest.read_text(encoding="utf-8", errors="replace").splitlines()
        w("  日志: %s (%d 行)" % (newest.name, len(txt)))
        w("")
        w("  关键信号:")
        for mk, desc in (("领取服务不可用", "★ 采集被取消(中心服务没连上)"),
                         ("缺 claim_client", "★ claim_client 没导入成功"),
                         ("claim] 已连接", "✓ 中心服务连上了"),
                         ("落盘失败", "★ 写文件失败"),
                         ("非会员", "号被判成非会员"),
                         ("浏览器/页面已关闭", "浏览器被关了"),
                         ("本批", "✓ 有正常分批(采到了)"),
                         ("合格", "✓ 采到过合格用户"),
                         ("已采样", "✓ 跑到过选路段")):
            n = sum(1 for l in txt if mk in l)
            if n:
                w("     %-22s %4d 次  %s" % (mk, n, desc))
        # 落盘失败的原话
        fails = [l for l in txt if "落盘失败" in l or "当天成果文件创建失败" in l]
        if fails:
            w("")
            w("  落盘失败的原话(最后 5 条):")
            for l in fails[-5:]:
                w("     " + l.strip()[:120])
        w("")
        w("  日志最后 5 行:")
        for l in txt[-5:]:
            w("     " + l.strip()[:110])

    rule("怎么读这份结果")
    w("  · 一、 里出现『★ 没有(老版本)』 -> 就是没更新成功, 跑 修复更新.bat")
    w("  · 二、 里如果【别处】搜到了文档 -> 文件在, 只是位置和你以为的不一样")
    w("  · 三、 里如果是『领取服务不可用』 -> 中心服务没连上, 采集被主动取消")
    w("        如果是『import 失败』 -> claim_client.py 有问题")
    w("  · 把这份文件发给管理员。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        w("")
        w("★ 检查过程出错:")
        w(traceback.format_exc()[-600:])
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(L)
        OUT.write_text(body, encoding="utf-8")
        try:
            OUT_EN.write_text(body, encoding="utf-8")
        except Exception:
            pass
        print()
        print("=" * 76)
        print("结果文件已生成在桌面:")
        print("   " + OUT.name)
        print("   " + OUT_EN.name)
        print("   (两个内容一样, 发任意一个都行)")
        print("=" * 76)
    except Exception as e:
        print("★ 写文件失败: %s" % str(e)[:90])
    try:
        input("\n按回车退出...")
    except Exception:
        pass
