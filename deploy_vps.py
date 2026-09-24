#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VPS 一键部署脚本 (在 Ubuntu 24.04 上以 root 运行)

做这些事:
  1. 装 Python 依赖 (fastapi uvicorn requests)
  2. 建目录 /opt/strava, 校验收到的文件
  3. 生成随机 CLAIM_KEY 并写入 /opt/strava/.env
  4. 配 systemd 开机自启 + 崩溃自动重启
  5. 配 ufw 防火墙 (只放行 22 和 8000)
  6. 启动并自检 (/health)

用法:
    sudo python3 deploy_vps.py

重复运行是安全的(幂等): 已有密钥不会覆盖, 服务会重启。
"""
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP = Path("/opt/strava")
ENV = APP / ".env"
REQUIRED = ["claim_store.py", "claim_server.py"]
HELPER = ["claim_client.py", "geo_cities.py"]
PORT = 8000


def sh(cmd, check=True, capture=True, cwd=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd,
                       capture_output=capture, text=True)
    if check and r.returncode != 0:
        print(f"  [失败] {cmd}")
        print((r.stdout or "") + (r.stderr or ""))
        raise SystemExit(1)
    return r


def step(n, msg):
    print(f"\n[{n}] {msg}")


def get_ssh_ports():
    """探测本机实际在用的 SSH 端口 —— 绝不能写死 22!
    写错会在 ufw 启用的瞬间把自己锁在服务器外面(最致命的常见错误)。"""
    ports = set()
    # 1) 最可靠: 从当前 SSH 连接反推
    #    SSH_CONNECTION="客户端IP 客户端端口 服务端IP 服务端端口"
    conn = os.environ.get("SSH_CONNECTION", "")
    parts = conn.split()
    if len(parts) >= 4 and parts[3].isdigit():
        ports.add(int(parts[3]))
    # 2) sshd 配置
    for p in ("/etc/ssh/sshd_config", "/etc/ssh/sshd_config.d/50-cloud-init.conf"):
        try:
            for line in Path(p).read_text(errors="replace").splitlines():
                s = line.strip()
                if s.lower().startswith("port "):
                    ports.add(int(s.split()[1]))
        except Exception:
            pass
    # 3) 实际监听里的 sshd
    try:
        out = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "sshd" in line:
                m = re.search(r":(\d+)\s", line)
                if m:
                    ports.add(int(m.group(1)))
    except Exception:
        pass
    ports.discard(0)
    if not ports:
        print("  [警告] 探测不到 SSH 端口, 退回 22 —— 请人工核对, 否则可能锁死!")
        ports = {22}
    return sorted(ports)


def main():
    if os.geteuid() != 0:
        print("请用 root 运行: sudo python3 deploy_vps.py")
        return 1

    print("=" * 70)
    print("Strava 领取服务 — VPS 部署")
    print("=" * 70)

    # ---- 0. 检查系统 ----
    step(0, "检查系统")
    try:
        py = subprocess.run(["python3", "-V"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        print("  找不到 python3")
        return 1
    print(f"  {py}")
    m = re.search(r"3\.(\d+)", py)
    if not m or int(m.group(1)) < 10:
        print(f"  [致命] 需要 Python 3.10+, 当前 {py}")
        print("         Ubuntu 24.04 自带 3.12; 若是 AlmaLinux/CentOS 请换系统")
        return 1
    print("  Python 版本 OK")

    # ---- 1. 依赖 ----
    step(1, "安装 Python 依赖")
    sh("apt-get update -qq", check=False)
    r = sh("apt-get install -y -qq python3-pip", check=False)
    sh("python3 -m pip install --quiet --break-system-packages fastapi uvicorn requests",
       check=False)
    for mod in ("fastapi", "uvicorn", "requests"):
        chk = subprocess.run(["python3", "-c", f"import {mod}"], capture_output=True)
        mark = "OK" if chk.returncode == 0 else "缺失"
        print(f"  {mod:<10} {mark}")
        if chk.returncode != 0:
            print(f"  [致命] {mod} 装不上, 请手动: pip install {mod}")
            return 1

    # ---- 2. 文件 ----
    step(2, "校验程序文件")
    APP.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    missing = []
    for f in REQUIRED:
        src = here / f
        if not src.exists():
            missing.append(f)
            continue
        dst = APP / f
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        print(f"  {f:<20} {dst.stat().st_size} B")
    if missing:
        print(f"  [致命] 缺少必需文件: {missing}")
        print("         请把 claim_store.py claim_server.py 和本脚本放在同一目录")
        return 1
    for f in HELPER:
        src = here / f
        if src.exists() and src.resolve() != (APP / f).resolve():
            shutil.copy2(src, APP / f)
            print(f"  {f:<20} 已一并复制(备用)")

    # ---- 3. 密钥 ----
    step(3, "生成/读取 API 密钥")
    key = ""
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if line.startswith("CLAIM_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        key = secrets.token_urlsafe(32)
        ENV.write_text(f"CLAIM_KEY={key}\n")
        ENV.chmod(0o600)
        print(f"  已生成新密钥, 存于 {ENV} (权限 600)")
    else:
        print(f"  复用已有密钥 (存于 {ENV})")
    print(f"  CLAIM_KEY = {key}")
    print("  ^^^ 请记录这个密钥, 20 台客户端都要填 ^^^")

    # ---- 4. systemd ----
    step(4, "配置 systemd (开机自启 + 崩溃重启)")
    unit = f"""[Unit]
Description=Strava Claim Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={APP}
EnvironmentFile={ENV}
ExecStart=/usr/bin/python3 {APP}/claim_server.py --host 0.0.0.0 --port {PORT} --db {APP}/strava_claim.db
Restart=always
RestartSec=5
StandardOutput=append:{APP}/server.log
StandardError=append:{APP}/server.err.log

[Install]
WantedBy=multi-user.target
"""
    unit_p = Path("/etc/systemd/system/strava-claim.service")
    unit_p.write_text(unit)
    sh("systemctl daemon-reload")
    sh("systemctl enable strava-claim.service", check=False)
    sh("systemctl restart strava-claim.service")
    print(f"  {unit_p} 已写入并启动")

    # ---- 5. 防火墙 ----
    # 【关键】绝不能写死 22! 很多 VPS 用非标准 SSH 端口, 写错就会把自己锁在门外。
    step(5, "配置防火墙")
    ssh_ports = get_ssh_ports()
    print(f"  检测到 SSH 端口: {ssh_ports}")
    if ssh_ports == [22]:
        print("  [注意] 只有 22。如果你其实用别的端口登录, 先按 Ctrl-C 中止!")
    if shutil.which("ufw"):
        sh("ufw --force default deny incoming", check=False)
        for p in ssh_ports:
            sh(f"ufw allow {p}/tcp", check=False)
            print(f"  已放行 SSH 端口 {p}")
        sh(f"ufw allow {PORT}/tcp", check=False)
        print(f"  已放行服务端口 {PORT}")
        sh("ufw --force enable", check=False)
        r = sh("ufw status", check=False)
        print("  当前规则:")
        for line in (r.stdout or "").splitlines()[:14]:
            print("    " + line)
    else:
        print("  没有 ufw, 尝试安装")
        sh("apt-get install -y -qq ufw", check=False)

    # ---- 6. 自检 ----
    step(6, "自检")
    time.sleep(3)
    for i in range(10):
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as resp:
                import json
                d = json.loads(resp.read().decode())
            print(f"  /health -> {d}")
            break
        except Exception as e:
            if i == 9:
                print(f"  [失败] 服务没起来: {e}")
                print(f"  查日志: journalctl -u strava-claim -n 50  或  cat {APP}/server.err.log")
                return 1
            time.sleep(2)

    # 拿公网 IP
    ip = ""
    try:
        import urllib.request
        ip = urllib.request.urlopen("https://api.ipify.org", timeout=8).read().decode().strip()
    except Exception:
        ip = "<你的VPS公网IP>"

    print("\n" + "=" * 70)
    print("部署完成")
    print("=" * 70)
    print(f"""
  服务地址:  http://{ip}:{PORT}
  API 密钥:  {key}

  20 台机器上各执行一次(验证连通):
    python claim_client.py --server http://{ip}:{PORT} --key {key} --test

  常用运维命令:
    systemctl status strava-claim      # 看运行状态
    journalctl -u strava-claim -f      # 实时看日志
    systemctl restart strava-claim     # 重启

  看进度看板:
    curl -H "X-API-Key: {key}" http://127.0.0.1:{PORT}/stats

  导出全部成果:
    curl -H "X-API-Key: {key}" "http://127.0.0.1:{PORT}/export?fmt=csv" -o collected.csv

  生成备份快照(可再传百度网盘):
    curl -X POST -H "X-API-Key: {key}" http://127.0.0.1:{PORT}/backup
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
