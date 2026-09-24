# -*- coding: utf-8 -*-
"""修"采集时界面卡" —— 真正的瓶颈是日志刷屏, 不是主题。

实测数据(本机):
    clam 基线       建窗口 105ms
    sv-ttk          建窗口 203ms  (1.9x)
    ttkthemes/arc   建窗口 1085ms (10.4x)   ← 所有"好看"的主题都贵在这个量级
  → 不存在"好看又不卡"的现成主题; 好看的代价就是重绘所有控件。

但真正的卡顿其实来自【日志】:
    引擎采集时每处理一个候选就写一行([check]/[quota]/[region]),
    界面每 200ms 把队列里的日志【逐条 insert】进 Tk Text, 而且【从不删除旧行】。
    Tk 的 Text 每插一行都要重排, 行数上万之后每次都越来越慢 ——
    跑几十分钟后界面就"点不动"了。

改法(两处, 都很小):
  ① 批量插入: 一次性把队列里的行 join 起来插一次, 而不是一行一 insert
  ② 行数上限: 超过 MAX_LINES 就从头部删掉一批(只保留最近的部分)
     ★ 只影响【屏幕上显示的日志】, 日志文件(logs/run_*.log)一个字都不少
"""
import pathlib
import py_compile

OLD = '''    def _drain_log(self):
        if not getattr(self, "_alive", True):
            return
        try:
            while not self.logq.empty():
                self.logt.insert("end", self.logq.get() + "\\n")
                self.logt.see("end")
            self._after_log = self.after(200, self._drain_log)
        except Exception:
            pass'''

NEW = '''    # 日志框里最多留多少行。超了从【头部】删掉一批。
    # ★ 只影响屏幕上显示的内容; logs/run_*.log 那个文件是完整的, 一个字不少。
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
                    self.logt.insert("end", "\\n".join(lines) + "\\n")
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
            pass'''

for gui in ("界面/ADS自动化.py", "界面/比特派自动化.py"):
    P = pathlib.Path(gui)
    s = P.read_text(encoding="utf-8")
    print("=" * 72)
    print(P.name)
    if OLD in s:
        s = s.replace(OLD, NEW)
        print("  ✓ 日志改成批量插入 + 行数上限")
    elif "LOG_MAX_LINES" in s:
        print("  · 已改过")
    else:
        print("  ★ 没匹配到 _drain_log")
    P.write_text(s, encoding="utf-8")
    try:
        py_compile.compile(str(P), doraise=True, cfile="__pycache__/x.pyc")
        print("  语法 OK")
    except Exception as e:
        print("  ★ 语法失败: %s" % str(e)[:180])
