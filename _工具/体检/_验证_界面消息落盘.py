# -*- coding: utf-8 -*-
"""验证: 界面自己的消息(log()) 现在会写进 logs/run_*.log。

以前只有 self.logq.put -> 屏幕上显示一下就没了。用户报"采一半又停了",
我们翻日志文件, 界面的关键提示一条都查不到, 没法判断到底发生了什么。

这里直接验机制: 给 "strava" 挂一个临时文件 handler, 再调界面模块里的
_gui_file_logger(), 看消息有没有落到那个文件里。
"""
import importlib.util
import logging
import sys
import tempfile
from pathlib import Path

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
GUIS = [("ADS", ROOT / "界面" / "ADS自动化.py"),
        ("BIT", ROOT / "界面" / "比特派自动化.py")]
ok_all = True

for tag, path in GUIS:
    tmp = Path(tempfile.mkdtemp(prefix="_guilog_"))
    logf = tmp / "run_test.log"

    # 模拟引擎的 logging 配置: "strava" 上挂一个 FileHandler
    base = logging.getLogger("strava")
    base.handlers.clear()
    fh = logging.FileHandler(logf, encoding="utf-8", delay=True)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    base.addHandler(fh)
    base.setLevel(logging.INFO)

    spec = importlib.util.spec_from_file_location("_gui_" + tag, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_gui_" + tag] = m
    spec.loader.exec_module(m)

    # 调界面用的那个 logger
    m._gui_file_logger().info("[gui] %s", "测试用的界面消息 ABC123")
    for h in base.handlers:
        try:
            h.flush()
        except Exception:
            pass
    for h in logging.getLogger("strava.gui").handlers:
        try:
            h.flush()
        except Exception:
            pass

    body = logf.read_text(encoding="utf-8", errors="replace") if logf.is_file() else ""
    hit = "测试用的界面消息 ABC123" in body and "[gui]" in body
    # 关键: 不能把同一条消息塞两遍进界面日志框(_GuiLogHandler 那条路)
    dup = body.count("测试用的界面消息 ABC123")
    good = hit and dup == 1
    if not good:
        ok_all = False
    print(f"{'OK ' if good else '★  '}{tag}: 写进文件={hit}  出现次数={dup} (应为 1)")
    if body:
        print("     " + body.strip().splitlines()[-1][:100])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("★★★ 界面消息现在也会落盘 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
