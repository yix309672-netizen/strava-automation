# -*- coding: utf-8 -*-
"""把"缺 claim_client / 领取服务不可用" 的真正发生时间钉死。

用户反馈两个问题:
  ① 有些同事还是老版本, 一键推送没用
  ② 同事采集生成了文档, 但不在文件夹里

我不能靠猜。先把所有日志翻一遍, 看这些错误到底发生在哪天、哪个进程。
"""
import pathlib
import re
from collections import Counter


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

LOGDIR = pathlib.Path("主脚本/logs")
files = sorted(LOGDIR.glob("run_*.log"))
print("=" * 78)
print("日志清单")
print("=" * 78)
for f in files:
    print("  %-24s %9d B" % (f.name, f.stat().st_size))

print()
print("=" * 78)
print("『缺 claim_client』到底出现在哪个日志、什么时间段")
print("=" * 78)
for f in files:
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = [l for l in lines if "缺 claim_client" in l]
    if not hits:
        continue
    print()
    print("  【%s】%d 次" % (f.name, len(hits)))
    print("     第一次: %s" % hits[0].strip()[:100])
    print("     最后一次: %s" % hits[-1].strip()[:100])
    # 按小时统计
    hours = Counter()
    for l in hits:
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2})", l)
        if m:
            hours[m.group(1)] += 1
    print("     按小时: %s" % dict(sorted(hours.items())))

print()
print("=" * 78)
print("『领取服务不可用』(采集被取消)")
print("=" * 78)
for f in files:
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    hits = [l for l in lines if "领取服务不可用" in l]
    if not hits:
        continue
    print("  【%s】%d 次   首次 %s   末次 %s"
          % (f.name, len(hits), hits[0][:19], hits[-1][:19]))
