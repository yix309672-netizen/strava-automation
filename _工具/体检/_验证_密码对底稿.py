# -*- coding: utf-8 -*-
"""拿桌面上的【账号底稿】核对项目里的密码 —— 这是唯一权威的标准答案。

★★ 为什么要它 ★★
   项目里的账号/结果文件都被错位事故污染过, 互相之间有分歧:
       nk0reyu33ko1@stubsyouki.us 在本项目里出现过 kaOS99kY 和 ka0S99kY 两种写法
       fuh18lxc0321@yangca.us     出现过 O1Bw0EF3 和 01Bw0EF3
   (字母 O / 数字 0 只差一个字符, 但从文件里永远分不出谁对。)
   桌面底稿是人手维护的原始清单, 一句 "邮箱 密码 绑定邮箱" —— 以它为准。

底稿格式(两种分隔都吃):
   okcbluimkkwi@yangca.us        kvKfv61I        rcd2wnh3aq@outlook.com
   nk0reyu33ko1@stubsyouki.us----kaOS99kY----a27eus8cge@126.com

用法:
    python _验证_密码对底稿.py            # 只看差异
    python _验证_密码对底稿.py --apply    # 按底稿改正(先自动备份)
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path


def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。"""
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

ROOT = _find_project_root(__file__)
DESK = Path.home() / "Desktop"
APPLY = "--apply" in sys.argv
MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")
PWD = re.compile(r"^[A-Za-z0-9]{6,20}$")

# 底稿(按修改时间新->旧; 同一个邮箱以【最新底稿】为准)
SRC = [
    (DESK / "运动真号邮箱.txt", "真号"),
    (DESK / "运动假号邮箱.txt", "假号"),
    (DESK / "_已删除_可还原" / "新建文件夹 (2)" / "账号_1-10.txt", "账号1-10"),
]


def load_sources():
    """{邮箱小写: (密码, 来源)} —— 按 SRC 顺序, 先到先得。"""
    m = {}
    for p, tag in SRC:
        if not p.is_file():
            print(f"  (底稿不存在, 跳过: {p})")
            continue
        n = 0
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = re.split(r"[\s\-]{2,}", line.strip())
            if len(parts) < 2:
                continue
            e, w = parts[0].strip(), parts[1].strip()
            if MAIL.match(e) and PWD.match(w):
                m.setdefault(e.lower(), (w, tag))
                n += 1
        print(f"  底稿 {p.name:20s} [{tag}] 读到 {n} 条")
    return m


print("模式:", "按底稿改正(--apply)" if APPLY else "只看差异(默认)")
print("-" * 74)
print("读底稿:")
SRC_MAP = load_sources()
print(f"  合计 {len(SRC_MAP)} 个邮箱有标准答案")
print("-" * 74)

FILES = [("配置/ads_accounts.json", "ADS账号"),
         ("配置/bit_accounts.json", "比特账号"),
         ("数据/ads_results.json", "ADS结果"),
         ("数据/bit_results.json", "比特结果")]

total_bad = total_unknown = 0
for rel, lb in FILES:
    p = ROOT / rel
    if not p.is_file():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    bad, unknown, good, fixed = [], 0, 0, 0
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        e = str(v.get("email") or "").strip().lower()
        cur = str(v.get("password") or "").strip()
        if not e or not cur:
            continue
        std = SRC_MAP.get(e)
        if not std:
            unknown += 1
            continue
        if std[0] == cur:
            good += 1
            continue
        bad.append((k, e, cur, std[0], std[1]))
        if APPLY:
            v["password"] = std[0]
            fixed += 1
    total_bad += len(bad)
    total_unknown += unknown
    print(f"[{lb}] {Path(rel).name}: 与底稿一致 {good} 条, "
          f"★ 不一致 {len(bad)} 条, 底稿没收录 {unknown} 条")
    for k, e, cur, std, tag in bad[:8]:
        print(f"     [{k}] {e:34s} 现在={cur!r}  底稿({tag})={std!r}")
    if APPLY and fixed:
        bak = p.with_name(p.name +
                          f".bak_before_对底稿_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(p, bak)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        import os
        os.replace(tmp, p)
        print(f"     已按底稿改正 {fixed} 条; 备份: {bak.name}")

print("-" * 74)
print(f"与底稿不一致合计: {total_bad} 条; 底稿未收录(无法判定): {total_unknown} 条")
