# -*- coding: utf-8 -*-
"""成果文件自检 —— 同事双击就能跑出结论。

用途: "采集了但没保存到文档" 时, 搞清楚到底卡在哪一步。

它会查:
  ① 程序把成果文件写在哪(和你以为的位置可能不一样)
  ② 那里现在有没有今天的文件、里面有多少条链接
  ③ 配置里有没有"会导致一条都不采"的设置
  ④ 日志里有没有"落盘失败/采集取消"的记录
  ⑤ 附上最近一次采集的关键行
"""
import datetime
import json
import os
import pathlib
import sys

for _s in (sys.stdout,):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
TODAY = datetime.datetime.now().strftime("%Y%m%d")


def rule(t):
    print("=" * 74)
    print(t)
    print("=" * 74)


def find_cfg():
    for c in (HERE / "config.json", HERE / "配置" / "config.json",
              HERE.parent / "配置" / "config.json", HERE.parent / "config.json"):
        if c.exists():
            return c
    return None


def main():
    rule("一、程序把成果文件写在哪")
    cfg_p = find_cfg()
    print("  脚本目录   : %s" % HERE)
    print("  读到的配置 : %s" % (cfg_p or "★ 找不到 config.json"))
    # 复刻引擎的 _find_data_dir
    if (HERE / "config.json").exists():
        data_dir = HERE
        layout = "平铺(文件写在脚本同级)"
    else:
        cands = [d for d in (HERE / "数据", HERE.parent / "数据") if d.is_dir()]
        data_dir = cands[0] if cands else HERE
        layout = "分层(文件写在 %s)" % data_dir.name
    print("  布局判断   : %s" % layout)
    print("  成果文件应 : %s" % (data_dir / ("链接-%s.txt" % TODAY)))
    print("  历史总表应 : %s" % (data_dir / "collected_users.txt"))

    rule("二、这些文件现在有没有")
    daily = data_dir / ("链接-%s.txt" % TODAY)
    master = data_dir / "collected_users.txt"
    for label, p in (("今天的成果文件", daily), ("历史总表", master)):
        if p.is_file():
            try:
                lines = [x for x in p.read_text(encoding="utf-8",
                                                errors="replace").splitlines()
                         if x.strip() and not x.startswith("#")]
                print("  ✓ %-14s %s" % (label, p.name))
                print("       %d 条链接, 最后修改 %s"
                      % (len(lines), datetime.datetime.fromtimestamp(
                          p.stat().st_mtime).strftime("%m-%d %H:%M:%S")))
            except Exception as e:
                print("  ★ %-14s 读不了: %s" % (label, str(e)[:50]))
        else:
            print("  ★ %-14s 【不存在】 %s" % (label, p.name))
    # 扫一遍整个目录, 看有没有别的成果文件
    print()
    print("  目录里所有成果文件:")
    found = sorted(list(data_dir.glob("链接-*.txt")) +
                   list(data_dir.glob("collected_users*.txt")))
    if found:
        for p in found[-10:]:
            print("     %-40s %8d B" % (p.name, p.stat().st_size))
    else:
        print("     (一个都没有)")
    # 也要看看别的目录(可能写错地方了)
    for d in (HERE, HERE.parent, HERE / "数据", HERE.parent / "数据"):
        if d == data_dir or not d.is_dir():
            continue
        hits = sorted(list(d.glob("链接-*.txt")) + list(d.glob("collected_users*.txt")))
        if hits:
            print()
            print("  ★ 但【%s】里发现了成果文件(可能写到这了):" % d)
            for p in hits[-6:]:
                print("     %-40s %8d B" % (p.name, p.stat().st_size))

    rule("三、配置里有没有'会导致一条都不采'的设置")
    cfg = {}
    if cfg_p:
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        except Exception as e:
            print("  ★ 配置读不了: %s" % str(e)[:60])
    checks = [
        ("collect_enabled", cfg.get("collect_enabled"), True,
         "关掉的话【只做资料不采集】"),
        ("us_only", cfg.get("us_only"), None,
         "开着=只要美国境内"),
        ("us_only_strict", cfg.get("us_only_strict"), None,
         "true 时'认不出国别'也淘汰, 可能过滤太狠"),
        ("min_athletes", cfg.get("min_athletes"), None,
         "太高会选不出路段 -> 采不到人"),
        ("min_athletes_floor", cfg.get("min_athletes_floor"), None, ""),
        ("collect_regions", cfg.get("collect_regions"), None, ""),
        ("collect_date_range", cfg.get("collect_date_range"), None, ""),
        ("collect_age_groups", cfg.get("collect_age_groups"), None, ""),
        ("collect_target_per_account", cfg.get("collect_target_per_account"), None, ""),
        ("claim_server", cfg.get("claim_server"), None,
         "连不上会导致'领取服务不可用 -> 取消采集'"),
        ("jobs", cfg.get("jobs"), None, ""),
    ]
    for k, v, want, note in checks:
        flag = ""
        if want is not None and v != want:
            flag = "   ★ 和期望不符"
        print("  %-28s = %-34r %s%s" % (k, v, note, flag))

    rule("四、日志里有没有线索")
    logs = []
    for d in (HERE / "logs", HERE.parent / "logs", HERE / "主脚本" / "logs"):
        if d.is_dir():
            logs += sorted(d.glob("run_*.log"))
    if not logs:
        print("  找不到日志文件(找过 本目录/logs, 上级/logs, 主脚本/logs)")
    else:
        newest = max(logs, key=lambda p: p.stat().st_mtime)
        print("  最新日志: %s (%d KB)"
              % (newest, newest.stat().st_size // 1024))
        txt = newest.read_text(encoding="utf-8", errors="replace").splitlines()
        KEY = ("落盘失败", "当天成果文件创建失败", "领取服务不可用",
               "采集取消", "非会员", "浏览器/页面已关闭", "已达标",
               "已达单号时间上限", "任务文件")
        hits = [l for l in txt if any(k in l for k in KEY)]
        if hits:
            print("  相关行(最后 15 条):")
            for l in hits[-15:]:
                print("     " + l.strip()[:100])
        else:
            print("  (没有异常关键词)")
        print()
        print("  最后 8 行(看它最后在干什么):")
        for l in txt[-8:]:
            print("     " + l.strip()[:100])

    rule("五、结论怎么看")
    print("  · 若'今天的成果文件'不存在, 但日志里有'领取服务不可用'")
    print("      -> 是中心服务连不上, 采集被主动取消(防重复), 一条都不会采")
    print("  · 若日志里有'落盘失败'")
    print("      -> 文件写不进去(权限/被杀软占用), 这是真丢数据, 要把原话发回来")
    print("  · 若日志里'非会员,跳过采集'")
    print("      -> 这个号被判成非会员, 没采(看是不是误判)")
    print("  · 若日志里一切正常、也有'任务文件'字样, 但文件不在这里")
    print("      -> 看第二节里'别的目录发现了成果文件'那条, 位置不对而已")
    print()
    print("★ 把这一整屏截图发给管理员。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("★ 意外错误: %s" % str(e)[:200])
    try:
        input("\n按回车退出...")
    except Exception:
        pass
