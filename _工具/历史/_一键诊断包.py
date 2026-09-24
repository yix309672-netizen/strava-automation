# -*- coding: utf-8 -*-
"""一键收集诊断包 —— 同事双击, 生成一个文件发回来。

为什么要它: 现在 SSH 不通, 没法给服务器加收日志的接口。
           最直接的办法是让同事把关键信息【打包成一个文件】发出来,
           管理员打开就能看出问题在哪。

它会收集:
  · 系统/环境(Windows 版本、Python 版本、脚本目录)
  · config.json(★ 密钥会打码, 不会泄露)
  · 目录清单(有哪些文件、成果文件多大)
  · 最新的 1~2 个日志文件(★ 只取尾部, 避免太大)
  · 中心服务连通性 + claim_client 能否 import
  · 关键设置项

产物: 桌面上的  诊断包_<机器名>_<时间>.txt
"""
import datetime
import json
import os
import pathlib
import socket
import subprocess
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
STAMP = NOW.strftime("%Y%m%d_%H%M%S")
MACHINE = os.environ.get("COMPUTERNAME") or "PC"
OUT = pathlib.Path.home() / "Desktop" / ("诊断包_%s_%s.txt" % (MACHINE, STAMP))

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
    if len(s) <= 8:
        return "(空)" if not s else "*" * len(s)
    return s[:6] + "..." + s[-4:] + "(长度%d)" % len(s)


def main():
    w("诊断包 —— %s @ %s" % (MACHINE, NOW.strftime("%Y-%m-%d %H:%M:%S")))
    w("(发给管理员即可; 里面的密钥已打码)")

    # ---------- 1 环境 ----------
    rule("1. 环境")
    w("  脚本目录  : %s" % HERE)
    w("  当前目录  : %s" % pathlib.Path.cwd())
    w("  Python    : %s" % sys.version.split()[0])
    w("  解释器    : %s" % sys.executable)
    try:
        _osv = str(sys.getwindowsversion())
    except Exception:
        _osv = "(非 Windows 或取不到)"
    w("  操作系统  : %s" % _osv)
    # 关键: 引擎和界面在不在
    # ★ 必须【同时找根目录和子目录】: 开发目录是分层的(主脚本/ 界面/),
    #   而同事的分发包是平铺的(全在根目录)。只查一种会误报"不在"。
    for rel in ("strava_ads.py", "strava_bit.py", "_gui_ads.py", "_gui_bit.py",
                "claim_client.py", "update.py", "geo_cities.py"):
        cands = [HERE / rel, HERE / "主脚本" / rel, HERE / "界面" / rel]
        p = next((c for c in cands if c.is_file()), None)
        if p is None:
            w("  %-28s ★ 不在(根目录/主脚本/界面 都找过)" % rel)
        else:
            w("  %-28s 在  %8d B   %s"
              % (rel, p.stat().st_size,
                 "" if p.parent == HERE else "(%s/)" % p.parent.name))
    for rel in ("ADS自动化.py", "比特派自动化.py"):
        p = next((c for c in (HERE / rel, HERE / "界面" / rel) if c.is_file()), None)
        w("  %-28s %s" % (rel, ("在  %d B" % p.stat().st_size) if p else "★ 不在"))
    for rel in ("config.json", "配置/config.json"):
        p = HERE / rel
        w("  %-28s %s" % (rel, ("在  %d B" % p.stat().st_size) if p.is_file() else "不在"))
    vf = HERE / "._pkg_version"
    w("  版本号(._pkg_version): %s"
      % (vf.read_text(encoding="utf-8").strip() if vf.is_file() else "★ 没有"))

    # ---------- 2 配置 ----------
    rule("2. config.json(密钥已打码)")
    cfg_p = None
    for c in (HERE / "config.json", HERE / "配置" / "config.json",
              HERE.parent / "配置" / "config.json", HERE.parent / "config.json"):
        if c.exists():
            cfg_p = c
            break
    w("  读到的配置: %s" % (cfg_p or "★ 一个都没找到"))
    cfg = {}
    if cfg_p:
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        except Exception as e:
            w("  ★ 解析失败: %s" % str(e)[:80])
    for c in (HERE / "config.json", HERE / "配置" / "config.json",
              HERE.parent / "配置" / "config.json", HERE.parent / "config.json"):
        if c.exists() and c != cfg_p:
            try:
                d = json.loads(c.read_text(encoding="utf-8"))
                w("  (另外还存在: %s  key长度=%d)"
                  % (c, len(str(d.get("adspower_key") or ""))))
            except Exception:
                pass
    SECRET = ("adspower_key", "bitbrowser_key", "claim_key")
    for k in sorted(cfg):
        v = cfg[k]
        if k in SECRET:
            v = mask(v)
        elif k == "password":
            v = mask(v)
        w("  %-28s = %r" % (k, v))

    # ---------- 3 成果文件 ----------
    rule("3. 成果文件")
    data_dir = HERE
    if not (HERE / "config.json").exists():
        for d in (HERE / "数据", HERE.parent / "数据"):
            if d.is_dir():
                data_dir = d
                break
    w("  数据目录: %s" % data_dir)
    today = NOW.strftime("%Y%m%d")
    mine = sorted(list(data_dir.glob("链接-*.txt")) +
                  list(data_dir.glob("collected_users*.txt")))
    w("  成果文件共 %d 个" % len(mine))
    for p in mine[-12:]:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            n = len([x for x in txt.splitlines()
                     if x.strip() and not x.startswith("#")])
        except Exception:
            n = -1
        w("     %-42s %8d B  %4d 条  %s"
          % (p.name, p.stat().st_size, n,
             datetime.datetime.fromtimestamp(p.stat().st_mtime)
             .strftime("%m-%d %H:%M:%S")))
    w("  今天的 链接-%s.txt : %s"
      % (today, "有" if (data_dir / ("链接-%s.txt" % today)).is_file() else "★ 没有"))
    # 别的目录里有没有(可能是写错地方了)
    for d in (HERE, HERE.parent, HERE / "数据", HERE.parent / "数据"):
        if not d.is_dir() or d == data_dir:
            continue
        hits = list(d.glob("链接-*.txt")) + list(d.glob("collected_users*.txt"))
        if hits:
            w("  ★ 但 %s 里也有成果文件 %d 个(可能写到这了)" % (d, len(hits)))

    # ---------- 4 中心服务 ----------
    rule("4. 中心服务连通性")
    srv = str(cfg.get("claim_server") or "").rstrip("/")
    key = str(cfg.get("claim_key") or "")
    w("  地址: %s   key长度: %d" % (srv or "(空)", len(key)))
    if srv:
        u = urllib.parse.urlparse(srv)
        try:
            sk = socket.create_connection((u.hostname, u.port or 80), timeout=10)
            sk.close()
            w("  TCP 端口: 通 ✓")
        except Exception as e:
            w("  ★ TCP 端口不通: %s" % str(e)[:70])
            w("    -> 会导致【领取服务不可用, 本次采集取消】(一条都不采)")
        try:
            r = urllib.request.Request(srv + "/health",
                                       headers={"X-API-Key": key})
            with urllib.request.urlopen(r, timeout=20) as resp:
                w("  /health : %s" % resp.read().decode()[:120])
        except Exception as e:
            w("  ★ /health 失败: %s" % str(e)[:80])

    # ---------- 5 claim_client ----------
    rule("5. claim_client.py(最容易出问题的一环)")
    cc = None
    for c in (HERE / "claim_client.py", HERE.parent / "claim_client.py",
              HERE / "主脚本" / "claim_client.py"):
        if c.is_file():
            cc = c
            break
    if cc is None:
        w("  ★ 找不到 -> 采集会被全部取消")
    else:
        w("  文件: %s (%d B)" % (cc, cc.stat().st_size))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_cc", cc)
            mm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mm)
            w("  import: ✓ ClaimClient=%s" % getattr(mm, "ClaimClient", None))
        except Exception as e:
            w("  ★ import 失败: %s" % str(e)[:100])
            w("    -> 这一条就足以让所有号【采集取消】, 一条都不采")

    # ---------- 6 日志 ----------
    rule("6. 日志(尾部)")
    logs = []
    for d in (HERE / "logs", HERE.parent / "logs", HERE / "主脚本" / "logs"):
        if d.is_dir():
            logs += sorted(d.glob("run_*.log"))
    if not logs:
        w("  找不到 run_*.log")
    else:
        logs.sort(key=lambda p: p.stat().st_mtime)
        # 只取最新的 2 个, 每个最多 400 行
        for lg in logs[-2:]:
            w("")
            w("  ---- %s (%d B) ----" % (lg.name, lg.stat().st_size))
            try:
                lines = lg.read_text(encoding="utf-8",
                                     errors="replace").splitlines()
            except Exception as e:
                w("     ★ 读不了: %s" % str(e)[:60])
                continue
            w("     (共 %d 行, 下面只贴最后 400 行)" % len(lines))
            for l in lines[-400:]:
                w("     " + l.rstrip()[:150])

    # ---------- 7 关键统计 ----------
    rule("7. 日志里的关键信号(计数)")
    if logs:
        txt = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                        for p in logs[-2:])
        for mark, desc in (
                ("领取服务不可用", "★ 采集被取消(中心服务没连上)"),
                ("缺 claim_client", "★ claim_client 没导入成功"),
                ("claim] 已连接", "✓ 中心服务连上了"),
                ("落盘失败", "★ 写文件失败"),
                ("非会员", "号被判成非会员"),
                ("浏览器/页面已关闭", "浏览器被关了"),
                ("本批", "✓ 正常分批(说明跑到了采集)"),
                ("采集开始", "✓ 任务启动过"),
                ("已采样", "✓ 跑到过选路段"),
                ("合格", "✓ 采到过合格用户"),
                ("采用", "路段采用情况")):
            n = txt.count(mark)
            if n:
                w("  %-22s %4d 次   %s" % (mark, n, desc))

    # ---------- 收尾 ----------
    rule("结束")
    w("  本文件: %s" % OUT)
    w("  把这个文件发给管理员。里面的密钥已经打码。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        w("")
        w("★ 收集过程出错:")
        w(traceback.format_exc()[-800:])
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(L), encoding="utf-8")
        print()
        print("=" * 76)
        print("已生成: %s" % OUT)
        print("大小: %.0f KB" % (OUT.stat().st_size / 1024))
        print("=" * 76)
        print("★ 把这个文件发给管理员(密钥已打码)。")
    except Exception as e:
        print("★ 写文件失败: %s" % str(e)[:100])
    try:
        input("\n按回车退出...")
    except Exception:
        pass
