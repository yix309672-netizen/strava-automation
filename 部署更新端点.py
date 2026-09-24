# -*- coding: utf-8 -*-
"""把新的 claim_server.py 部署到 VPS（加了脚本分发端点）

用法:
    python 部署更新端点.py                     # 交互式问密码
    python 部署更新端点.py --host 1.2.3.4 --port 33085 --user root

做的三件事:
    1. SFTP 上传 claim_server.py 到 /opt/strava/
    2. systemctl restart strava-claim
    3. 验证 /pkg/manifest 能通

★ 只上传服务端脚本, 不动数据库、不动 .env(密钥在那里面)。
"""
import argparse
import getpass
import hashlib
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent
LOCAL = WS / "claim_server.py"
REMOTE = "/opt/strava/claim_server.py"
SERVICE = "strava-claim"


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="137.175.71.171")
    ap.add_argument("--port", type=int, default=33085)
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="")
    a = ap.parse_args()

    if not LOCAL.is_file():
        log("找不到 %s" % LOCAL)
        return 1

    pwd = a.password or getpass.getpass("VPS 密码 (%s@%s): " % (a.user, a.host))

    try:
        import paramiko
    except ImportError:
        log("缺 paramiko, 先执行:  pip install paramiko")
        return 1

    # ★ claim_store.py 是去重的唯一真源, 必须一起传 —— 只传 HTTP 外壳的话,
    #   真源里的任何修复都上不了服务器, 而且新外壳依赖新真源时会在重启后崩。
    FILES = [("claim_server.py", "/opt/strava/claim_server.py"),
             ("claim_store.py", "/opt/strava/claim_store.py")]
    for _n, _r in FILES:
        if not (WS / _n).is_file():
            log("找不到 %s" % _n)
            return 1
    data = LOCAL.read_bytes()
    log("=== 部署新的服务端 ===")
    log("  将上传: %s" % ", ".join(n for n, _ in FILES))
    log("  目标   : %s@%s:%d" % (a.user, a.host, a.port))
    log("  上传   : claim_server.py  %d B  sha256=%s"
        % (len(data), hashlib.sha256(data).hexdigest()[:12]))

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # 台机器的 SSH 在 33085, 22 只是防火墙规则还在, 并没有进程监听。
    # 所以 --port 写错时不要直接退出, 换另一个端口再试一次。
    ports = [a.port] + [p for p in (33085, 22) if p != a.port]
    for _i, _p in enumerate(ports):
        try:
            cli.connect(a.host, port=_p, username=a.user, password=pwd,
                        timeout=20, banner_timeout=20, auth_timeout=20)
        except Exception as e:
            if _i + 1 < len(ports):
                log("  %d 连不上 (%s), 改试 %d ..." % (_p, type(e).__name__, ports[_i + 1]))
                continue
            log("  SSH 连不上: %s" % str(e)[:150])
            return 1
        if _p != a.port:
            log("  [提示] 实际 SSH 端口是 %d (不是 %d), 下次直接: --port %d" % (_p, a.port, _p))
        break
    log("  SSH 已连接")

    def run(cmd, quiet=False):
        _in, out, err = cli.exec_command(cmd, timeout=120)
        o = out.read().decode("utf-8", "replace").strip()
        e = err.read().decode("utf-8", "replace").strip()
        if not quiet and (o or e):
            for line in (o + "\n" + e).splitlines():
                if line.strip():
                    log("      " + line.strip()[:160])
        return o, e

    try:
        # 备份现有文件（两个都要备份）
        for _n, _r in FILES:
            run("cp -a %s %s.bak_$(date +%%Y%%m%%d_%%H%%M%%S) 2>/dev/null; true"
                % (_r, _r))
        log("  已备份原文件（claim_server.py + claim_store.py）")

        # 上传（★ 必须两个一起传。claim_store.py 是"不重复采集"的唯一真源,
        #   只传 HTTP 外壳的话, 真源里的任何修复永远上不了服务器;
        #   而且新外壳若依赖新真源, 重启后会直接崩, 20 台就全停采了。）
        sftp = cli.open_sftp()
        for _n, _r in FILES:
            _data = (WS / _n).read_bytes()
            _tmp = _r + ".new"
            with sftp.open(_tmp, "wb") as f:
                f.write(_data)
            run("mv %s %s && chmod 644 %s" % (_tmp, _r, _r))
            log("  已上传 %-18s %6d B" % (_n, len(_data)))
        sftp.close()

        # 自检：先语法, 再 import 冒烟（别把服务搞挂）
        o, e = run("cd /opt/strava && python3 -m py_compile claim_server.py "
                   "claim_store.py && echo SYNTAX_OK")
        _imp = ""
        if "SYNTAX_OK" in o:
            _imp = run("cd /opt/strava && python3 -c \"import claim_store, "
                       "importlib.util as u; "
                       "s=u.spec_from_file_location('srv','claim_server.py'); "
                       "print('IMPORT_OK')\" ")[0]
        if not ("SYNTAX_OK" in o and "IMPORT_OK" in _imp):
            log("  ★ 新代码自检不过，已回滚")
            for _n, _r in FILES:
                run("ls -1 %s.bak_* 2>/dev/null | tail -1 | "
                    "xargs -I{} cp -a {} %s" % (_r, _r))
            run("systemctl restart %s" % SERVICE)
            return 1
        log("  语法 + import 自检通过")

        # 重启
        run("systemctl restart %s" % SERVICE)
        log("  已重启 %s" % SERVICE)
        time.sleep(3)
        o, _ = run("systemctl is-active %s" % SERVICE)
        log("  服务状态: %s" % o)

        # 验证
        o, _ = run("curl -s -m 8 http://127.0.0.1:8000/health")
        log("  /health  : %s" % o[:120])
        # ★ 不能用 source: paramiko 走 /bin/sh(Ubuntu 是 dash), source 不是
        #   内建命令, 报错被吞掉 -> key 读成空 -> curl 401 -> 部署成功却报失败
        env_key = run(". /opt/strava/.env 2>/dev/null; echo \"$CLAIM_KEY\"",
                      quiet=True)[0]
        o, _ = run("curl -s -m 8 -H 'X-API-Key: %s' "
                   "http://127.0.0.1:8000/pkg/manifest" % env_key)
        log("  /pkg/manifest: %s" % o[:200])
        if '"version"' in o:
            log("")
            log("  ★ 部署成功 —— 服务端已经支持脚本分发")
            return 0
        log("")
        log("  ★ 端点没生效，看上面的输出")
        return 1
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
