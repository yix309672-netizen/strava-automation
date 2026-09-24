# -*- coding: utf-8 -*-
"""把被错位事故写坏的 password 列救回来。

★★ 为什么之前的 _修_结果错位.py 没救回密码 ★★
   它从 配置/ads_accounts.json 按邮箱查密码 —— 但那个文件【自己也坏了】:
   界面当时显示的是坏表格, 一保存就把 是/否 写进了账号文件,
   于是"找回"回来的还是 是/否。真相是: 密码【只在别处的老文件里】还活着。

★★ 真密码藏在哪(已实测) ★★
   1. 配置/accounts.json          —— 09-17 原始账号表, 70 键, 真密码
   2. 数据/scan_results.json      —— 09-17 扫描结果, 50 条真密码
   3. 备注/私密列里的 "账号：xx 密码：yy" 文本
   4. _备份/ 下的历史快照
   取【所有来源的并集】, 邮箱 -> 密码。

真密码特征: 8 位纯字母数字(zx9kF7K3)。用它当过滤器,
是/否/邮箱/中文 一律不收 —— 否则等于没修。

用法:
    python _修_密码丢失.py            # 只看, 不改
    python _修_密码丢失.py --apply    # 真的改(先自动备份)
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
APPLY = "--apply" in sys.argv
GOOD = re.compile(r"^[A-Za-z0-9]{6,20}$")          # 真密码长相
MAIL = r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+"
PAIR = re.compile(r"(" + MAIL + r")[\s：:，,]+?([A-Za-z0-9]{6,20})\b")

# 按优先级: 越靠前越可信(都是事故前的快照)
SOURCES = [
    ROOT / "配置" / "accounts.json",
    ROOT / "数据" / "scan_results.json",
    ROOT / "_备份" / "_改造前备份_20260919_051455" / "数据" / "scan_results.json",
    ROOT / "_备份" / "_改造前备份_20260919_051455" / "数据" / "ads_results.json",
    ROOT / "_备份" / "_改造前备份_20260919_051455" / "数据" / "bit_results.json",
    ROOT / "数据" / "ads_results.json",
    ROOT / "数据" / "bit_results.json",
]


def harvest(obj, put):
    """从一个 json 对象里挖 (邮箱, 密码)。两种形态都吃: 账号表 / 结果表。"""
    if not isinstance(obj, dict):
        return
    for v in obj.values():
        if not isinstance(v, dict):
            continue
        e = str(v.get("email") or "").strip()
        if e:
            put(e, v.get("password"))
        # 备注/私密列里的 "账号：xx 密码：yy" 文本
        for f in ("note", "priv"):
            t = str(v.get(f) or "")
            for m in PAIR.finditer(t):
                put(m.group(1), m.group(2))


def build_index():
    idx = {}

    def put(e, p):
        e = str(e or "").strip().lower()
        p = str(p or "").strip()
        if e and GOOD.match(p):
            idx.setdefault(e, p)      # 先到先得 = 高优先级来源赢

    for p in SOURCES:
        if not p.is_file():
            continue
        try:
            harvest(json.loads(p.read_text(encoding="utf-8")), put)
        except Exception as ex:
            print(f"    (跳过 {p.name}: {ex})")
    # 再补一遍 _备份 下所有 json(低优先级, 只填空缺)
    for p in sorted((ROOT / "_备份").rglob("*.json")):
        try:
            harvest(json.loads(p.read_text(encoding="utf-8")), put)
        except Exception:
            pass
    return idx


PW_KEYS = ("password",)


def build_borrow(*files):
    """{win或键: (邮箱, 密码)} —— 账号表某些行被清空时, 从结果表借回来。

    ★ bit_accounts 的键是 _N, bit_results 的键是 N 但带 win=_N, 所以要两个都收。
    ★★ 只能【同引擎内】借(bit 找 bit, ads 找 ads) ★★
       第一版把两边的结果表一起收进来, 结果 bit_results 里一个空的占位行
       (43) 被填上了 ADS 的 43 号账号 —— 凭空造出一条不该存在的数据。
       空占位行就该保持空着。
    """
    b = {}
    for d in files:
        if not d.is_file():
            continue
        try:
            j = json.loads(d.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k, v in (j or {}).items():
            if not isinstance(v, dict):
                continue
            e = str(v.get("email") or "").strip()
            p = str(v.get("password") or "").strip()
            txt = " ".join(str(v.get(f) or "") for f in ("note", "priv"))
            if not e:
                m = re.search(MAIL, txt)
                e = m.group(0) if m else ""
            if not GOOD.match(p):
                m = re.search(r"密码[：:]\s*([A-Za-z0-9]{6,20})", txt)
                p = m.group(1) if m else ""
            if e and GOOD.match(p):
                for kk in (k, str(v.get("win") or "").strip()):
                    if kk:
                        b.setdefault(kk, (e, p))
    return b


def fix_file(path, idx, label, borrow=None):
    if not path.is_file():
        print(f"[{label}] {path.name} 不存在, 跳过")
        return 0, 0
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not d:
        print(f"[{label}] {path.name} 空, 跳过")
        return 0, 0
    borrow = borrow or {}
    hit = miss = blank = 0
    fixed = 0                             # ★ 真的被改过的条数
    missing_mails = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        # ★ 有数据但邮箱丢了(被错位事故顶掉) -> 从备注/私密列里把邮箱挖回来
        e = str(v.get("email") or "").strip()
        if not e:
            if not any(str(v.get(f) or "").strip() for f in
                       ("name", "city", "acts", "prem", "priv", "note")):
                # 全空占位行。★ 但账号表这种行里可能【藏着账号】, 去结果表借
                bo = borrow.get(str(k).strip()) or borrow.get(
                    str(v.get("win") or "").strip())
                if bo:
                    e = bo[0]
                    if APPLY:
                        v["email"], v["password"] = bo[0], bo[1]
                    hit += 1
                    fixed += 1
                    continue
                blank += 1
                continue
            m = re.search(MAIL, " ".join(str(v.get(f) or "") for f in
                                         ("note", "priv", "name", "city")))
            if m:
                e = m.group(0)
                if APPLY:
                    v["email"] = e
            else:
                miss += 1
                missing_mails.append(f"{k}(无邮箱)")
                continue
        cur = str(v.get("password") or "").strip()
        if GOOD.match(cur):
            hit += 1                      # 本来就是对的, 不动
            continue
        newp = idx.get(e.lower())
        if newp:
            hit += 1
            fixed += 1
            if APPLY:
                v["password"] = newp
        else:
            miss += 1
            missing_mails.append(e)
    print(f"[{label}] {path.name}: 共 {len(d)} 条 -> 本来就对 {hit - fixed} 条, "
          f"★ 救回 {fixed} 条, 空占位 {blank} 条, 找不回 {miss} 条")
    if missing_mails:
        print(f"    找不回的例子: {missing_mails[:6]}")
    if APPLY and fixed:
        bak = path.with_name(path.name +
                             f".bak_before_密码恢复_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(path, bak)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        import os
        os.replace(tmp, path)
        print(f"    已写回; 备份: {bak.name}")
    return hit, miss


print("模式:", "真的改(--apply)" if APPLY else "只看不改(默认)")
print("-" * 72)
IDX = build_index()
print(f"密码索引: 收到 {len(IDX)} 个邮箱的真密码")
print("-" * 72)
total_miss = 0
RA, RB = ROOT / "数据" / "ads_results.json", ROOT / "数据" / "bit_results.json"
# ★ 借用表按引擎分开: bit 只能借 bit, ads 只能借 ads
for f, lb, bor in (("配置/ads_accounts.json", "ADS账号", build_borrow(RA)),
                   ("配置/bit_accounts.json", "比特账号", build_borrow(RB)),
                   ("数据/ads_results.json", "ADS结果", build_borrow(RA)),
                   ("数据/bit_results.json", "比特结果", build_borrow(RB))):
    _h, m = fix_file(ROOT / f, IDX, lb, bor)
    total_miss += m
print("-" * 72)
print("完成。" if not total_miss else
      f"★ 还有 {total_miss} 条邮箱在任何历史文件里都找不到真密码, 需要你手工补。")
