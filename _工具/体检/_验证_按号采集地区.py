# -*- coding: utf-8 -*-
"""验证: 每个账号能单独选采集地区/年龄, 且成果文件按「地区_日期」命名。

用户要求(2026-09-24):
    「每个账号可以单独选择采集什么地区。比如说三个账号采集三个不同的地区。
      年纪。在每个账号单独开发, 如果没有选择, 就默认下拉框的地区。
      然后选择什么地区, 采集下来的链接保存文件名就是地区加日期。」

验四件事:
    ① 两个界面都有 region/age 两列, 且【不在】PROFILE_COLS 里
       —— 在里面的话每次刷新结果都会把用户设的值冲掉
    ② 按号设置是在【主线程】读出来的、能传到 collect_one
       —— 子线程读 tree 会死锁(项目里记过的坑)
    ③ 留空不动 cfg(默认口径原封不动); 填了才覆盖
    ④ 两个引擎的 _daily_path 传了 region 就是 地区_日期.txt
"""
import importlib.util, os, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
ok_all = True


def _src(p):
    """读源码, 剥掉注释和 docstring —— 只看真代码。

    ★ 项目铁律: 只剥 # 注释不够, docstring 也要剥, 否则注释里引用的旧写法
      会造成假警报(已出现 3 次)。
    """
    s = Path(p).read_text(encoding="utf-8")
    s = re.sub(r'"""(?:.|\n)*?"""', "", s)
    s = re.sub(r"'''(?:.|\n)*?'''", "", s)
    return re.sub(r"#[^\n]*", "", s)


def case(name, ok, detail=""):
    global ok_all
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name:34s} {detail}")


def load_mod(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


# ---- ①②③ 两个界面 ----
for gui, eng, tag in (("界面/ADS自动化.py", "主脚本/strava_ads.py", "ADS"),
                      ("界面/比特派自动化.py", "主脚本/strava_bit.py", "BIT")):
    p = ROOT / gui
    src = _src(p)
    mod = load_mod(p, "gui_" + tag.lower())
    print(f"===== {tag} =====")
    case("① 有 region / age 两列",
         "region" in mod.FIELDS and "age" in mod.FIELDS,
         f"FIELDS {len(mod.FIELDS)} 列")
    case("① 两列不在 PROFILE_COLS(刷新不冲)",
         not ({"region", "age"} & set(mod.PROFILE_COLS)),
         f"PROFILE_COLS={len(mod.PROFILE_COLS)} 项")
    case("① 表头写清楚了(空=默认)",
         "空=默认" in mod.HEADS.get("region", "")
         and "空=默认" in mod.HEADS.get("age", ""))
    case("② 表格收集是在主线程", "rowset[_s] = (_r, _a)" in src)
    case("② 打包传给工作线程", "rowset)" in src and "def _work(self, ids, mode, creds, cfg, rowset=None)" in src)
    case("③ 留空不动 cfg", "_rs = (rowset or {}).get(seq)" in src
         and "if _rs:" in src)
    case("③ 填了才覆盖地区", 'if _rs[0]:' in src and '_c["collect_regions"] = [_rs[0]]' in src)
    case("③ 填了才覆盖年龄", 'if _rs[1]:' in src and '_c["collect_age_groups"]' in src)
    case("② 走的是同一个 collect_one", "call_engine(SA.collect_one, seq, _c, _task)" in src)
    # ★★ 2026-09-24 用户实测报"选了独立地区还是按默认地区采" ★★
    #   根因: 光设 collect_regions 没用 —— 引擎里"每个号必扫纽约"会把 New York
    #   插到第一位, collect_auto_regions 再撒全美 50 州。采集从纽约开始填,
    #   目标人数一满就再也轮不到指定的地区。必须同时把这两条锁死。
    case("③ 设了 collect_only_regions", '_c["collect_only_regions"] = True' in src)
    case("③ 设了 collect_auto_regions=False", '_c["collect_auto_regions"] = False' in src)
    # ④ 引擎
    esrc = _src(ROOT / eng)
    case("④ 引擎有 only_regions 形参", "only_regions=False," in esrc)
    case("④ 引擎里「纽约必扫」被挡住",
         "if not only_regions and not any(region_is_ny" in esrc
         or "if only_regions:" in esrc)
    case("④ 引擎里「自动撒网」被挡住",
         "if auto_regions and not only_regions:" in esrc)
    case("④ 调用点把锁传下去了",
         'only_regions=bool(cfg.get("collect_only_regions", False))' in esrc)
    em = load_mod(ROOT / eng, "eng_" + tag.lower())
    import datetime
    d = datetime.datetime(2026, 9, 24)
    nm = em._daily_path(d, region="New Jersey").name
    nl = em._daily_path(d).name
    case("④ 地区_日期.txt", nm == "New Jersey_20260924.txt", nm)
    case("④ 没给地区还是老样子", nl.startswith("链接-") and nl.endswith("20260924.txt"), nl)
    case("④ 非法字符被清理",
         em._daily_path(d, region="a/b:c*d?e").name == "a_b_c_d_e_20260924.txt")
    case("④ 成果目录是 数据/", em._daily_path(d, region="X").parent.name == "数据")
    print()

print("=" * 74)
print("★★★ 按号地区/年龄 + 成果文件按地区命名 全部就绪 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
