# -*- coding: utf-8 -*-
"""服务器连通性细查: 把"到底哪一层挡着"钉死。

已知: 8000 和 33085 通, 22/80/443/3389 不通, 而面板里它们都显示"进 tcp 启用"。
要区分三种可能:
  A. 服务器内部防火墙(ufw/iptables)只放行了 8000/33085
  B. SSH 服务没在跑(端口根本没监听)
  C. 面板规则没真正下发(商家侧还有一层)
"""
import socket
import subprocess
import time


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

HOST = "137.175.71.171"


def probe(port, timeout=8, n=1):
    ok, ms = 0, []
    for _ in range(n):
        t0 = time.time()
        try:
            s = socket.create_connection((HOST, port), timeout=timeout)
            try:
                s.settimeout(4)
                s.recv(64)
            except Exception:
                pass
            s.close()
            ok += 1
            ms.append((time.time() - t0) * 1000)
        except Exception:
            pass
    return ok, (sum(ms) / len(ms) if ms else 0)


print("=" * 74)
print("1) 各端口能否建立 TCP 连接")
print("=" * 74)
PORTS = [(8000, "采集/更新服务"), (33085, "未知(你自己开的?)"),
         (22, "SSH"), (80, "HTTP"), (443, "HTTPS"), (3389, "远程桌面"),
         (5432, "PostgreSQL"), (8501, "Streamlit")]
for p, name in PORTS:
    ok, ms = probe(p, n=2)
    print("  %-6d %-22s %s" % (p, name, ("通 ✓  %.0f ms" % ms) if ok else "不通 ✗"))

print()
print("=" * 74)
print("2) ICMP(ping) —— 安全组里有 '进 icmp' 那条")
print("=" * 74)
r = subprocess.run(["ping", "-n", "3", "-w", "2000", HOST],
                   capture_output=True, text=True, encoding="gbk", errors="replace")
for line in (r.stdout or "").strip().splitlines()[-5:]:
    print("  " + line.strip())

print()
print("=" * 74)
print("3) 22 端口慢测(排除'防爆破降速')")
print("=" * 74)
for i in range(3):
    t0 = time.time()
    try:
        s = socket.create_connection((HOST, 22), timeout=25)
        s.close()
        print("  第%d次: 通 ✓  用了 %.1f 秒" % (i + 1, time.time() - t0))
        break
    except Exception:
        print("  第%d次: 超时(等了 %.0f 秒)" % (i + 1, time.time() - t0))

print()
print("=" * 74)
print("4) 判断")
print("=" * 74)
p8000, _ = probe(8000, n=1)
p33085, _ = probe(33085, n=1)
p22, _ = probe(22, n=1)
if p8000 and p33085 and not p22:
    print("  · 8000 / 33085 通, 22 不通")
    print("  · 这两条正是面板上【生效中(红点白底)】的规则")
    print("  · 说明: 面板安全组【是生效的】, 但 22 这一条没起到作用")
    print("  → 最可能: 服务器内部防火墙(ufw/iptables)只放行了 8000/33085,")
    print("    或者 SSH 服务没在跑。这两者都要登进服务器才能改。")
    print("  → 所以现在【必须找到一个能进服务器的通道】(VNC/控制台/Web终端)。")
else:
    print("  · 8000=%s 33085=%s 22=%s" % (p8000, p33085, p22))
