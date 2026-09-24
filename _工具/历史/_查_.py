# -*- coding: utf-8 -*-
"""排查: 成果文档"生成了但不在文件夹里" —— 它到底写到哪去了。

★ 关键怀疑点: 引擎判断"数据目录"用的是一个【决定性信号】:
     config.json 在脚本同级  -> 平铺布局 -> 文件写在同级
     config.json 在 配置/    -> 分层布局 -> 文件写在 数据/
   同事的分发包是平铺的(config.json 和脚本同级), 所以文件应该写在
   【脚本同级】。但同事如果在界面上改过什么, 或者目录结构变了,
   文件就可能落到别的地方 —— 甚至落到【上级目录】或【桌面】。

   还有一种可能: 同事在 数据/ 里找, 但文件其实在脚本根目录。
"""
import pathlib
import sys

for _s in (sys.stdout,):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
print("=" * 78)
print("成果文档到底写在哪 —— 用引擎自己的判断逻辑推一遍")
print("=" * 78)

print()
print("1) 引擎怎么判断数据目录(照抄引擎的 _find_data_dir)")
print("-" * 78)
print("   规则:")
print("     if (脚本目录/config.json).exists():  -> 脚本同级(平铺)")
print("     elif 脚本目录/数据 存在:              -> 那里面")
print("     elif 上级目录/数据 存在:              -> 那里面")
print("     else:                                -> 脚本同级")
print()
print("   当前这台机器:")
print("     脚本目录: %s" % HERE)
c1 = (HERE / "config.json").exists()
c2 = (HERE / "配置" / "config.json").exists()
c3 = (HERE.parent / "配置" / "config.json").exists()
d1 = (HERE / "数据").is_dir()
d2 = (HERE.parent / "数据").is_dir()
print("     %-40s %s" % ("本目录 config.json", "有" if c1 else "无"))
print("     %-40s %s" % ("本目录 配置/config.json", "有" if c2 else "无"))
print("     %-40s %s" % ("上级 配置/config.json", "有" if c3 else "无"))
print("     %-40s %s" % ("本目录 数据/", "有" if d1 else "无"))
print("     %-40s %s" % ("上级 数据/", "有" if d2 else "无"))
if c1:
    dd, why = HERE, "平铺布局 -> 文件写【脚本同级】"
elif d1:
    dd, why = HERE / "数据", "分层 -> 文件写【本目录/数据】"
elif d2:
    dd, why = HERE.parent / "数据", "分层 -> 文件写【上级/数据】"
else:
    dd, why = HERE, "兜底 -> 文件写【脚本同级】"
print()
print("   >>> 引擎认定的数据目录: %s" % dd)
print("   >>> 原因: %s" % why)

print()
print("2) 这个目录里现在有什么")
print("-" * 78)
if dd.is_dir():
    fs = sorted([p for p in dd.iterdir() if p.is_file()],
                key=lambda p: p.stat().st_mtime, reverse=True)
    print("   共 %d 个文件, 最近 10 个:" % len(fs))
    for p in fs[:10]:
        print("     %-44s %9d B" % (p.name, p.stat().st_size))
else:
    print("   ★ 这个目录不存在: %s" % dd)
    print("     -> 这就是「生成了但找不到」的原因: 目录压根没建出来")

print()
print("3) 全盘找: 别的地方有没有成果文档(重点看这些位置)")
print("-" * 78)
CAND = [HERE, HERE.parent, HERE / "数据", HERE.parent / "数据",
        HERE / "主脚本", HERE / "界面",
        pathlib.Path.home() / "Desktop",
        pathlib.Path.home() / "Desktop" / "数据",
        pathlib.Path.home() / "Documents"]
seen = set()
found_any = False
for d in CAND:
    try:
        if not d.is_dir() or d in seen:
            continue
        seen.add(d)
    except Exception:
        continue
    hits = []
    for pat in ("链接-*.txt", "collected_users*.txt"):
        hits += list(d.glob(pat))
    if hits:
        found_any = True
        print("   【%s】" % d)
        for p in sorted(hits, key=lambda x: x.stat().st_mtime, reverse=True)[:8]:
            print("      %-40s %9d B" % (p.name, p.stat().st_size))
if not found_any:
    print("   ★ 上面这些地方都没找到成果文档")

print()
print("4) 那其它文件(日志/状态/总表)在哪? 这能反推目录")
print("-" * 78)
for name in ("collected_users.txt", "collected_seen.json",
             "task_state.json", "scan_results.json", "ads_results.json"):
    hits = []
    for d in CAND:
        try:
            p = d / name
            if p.is_file():
                hits.append(p)
        except Exception:
            pass
    if hits:
        for p in hits[:2]:
            print("   %-24s -> %s" % (name, p))
    else:
        print("   %-24s -> ★ 没找到" % name)

print()
print("=" * 78)
print("怎么看")
print("=" * 78)
print("  · 如果第 1 节推出来的目录 != 你找的那个目录")
print("      -> 文件在【引擎认定的目录】里, 你没找对地方")
print("  · 如果第 3 节在【上级目录】或【桌面】找到了")
print("      -> 说明引擎把数据目录判到那里去了(通常是目录里多了一个 config.json)")
print("  · 如果到处都没有")
print("      -> 那文档真的没生成, 是采集侧的问题(看日志里的'落盘失败')")
