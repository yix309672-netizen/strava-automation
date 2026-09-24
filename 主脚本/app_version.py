# -*- coding: utf-8 -*-
"""程序版本号 —— 【唯一真源】。发版前改这里一处, 四个文件自动跟着变。

为什么单独一个文件:
    ★ 两个界面 + 两个引擎都要显示版本号, 写 4 份必然漂移。
    ★ 以前只有服务器按内容算的一串哈希(如 f6354d90a6c9c40a) ——
      同事报问题时说不上来自己跑的是哪一版, 管理员也分不清新旧。
      现在界面标题栏直接显示, 一眼就能对。

怎么用:
    · 界面上: 标题栏 "ADS自动化  v3.0 · 2026-09-24"
    · 引擎里: 启动时打一行 [版本] v3.0 · 2026-09-24 到日志
    · 命令行: python 主脚本/app_version.py   直接打印

发版流程: 改下面的 VERSION/DATE/NOTE -> 跑 _同步分发.py -> 跑 发布更新.py
    ★ 这个文件必须登记在 _同步分发.py 的 PAIRS 里, 否则改了自己机器上变了、
      同事包里还是旧的(和当年 geo_cities.py / name_bank.py 漏发是同一个坑)。
"""

VERSION = "v3.3"
DATE = "2026-09-25"
NOTE = "美国锁硬锁进代码(不再读 config) · 德国号一律不要 · 按号地区锁定"


def label():
    """给人看的一行:'v3.0 · 2026-09-24'"""
    return f"{VERSION} · {DATE}"


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    print(label())
    print(NOTE)
