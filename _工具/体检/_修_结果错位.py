# -*- coding: utf-8 -*-
"""把被"错位一格"写坏的结果文件还原。

★★ 错位是怎么来的(已实测确认) ★★
   界面 FIELDS = (seq, win, note, email, password, login, name, city, acts, prem, priv)
   老刷新代码却按【老列序】写死下标:
       ("login",4) ("name",5) ("city",6) ("acts",7) ("prem",8) ("priv",9) ("note",10)
   而新列序里 4=password, 5=login, 6=name, 7=city, 8=acts, 9=prem, 10=priv
   -> 资料列整体【左移一格】:
        新.password = 原.login     新.login = 原.name
        新.name     = 原.city      新.city  = 原.acts
        新.acts     = 原.prem      新.prem  = 原.priv
        新.priv     = 原.note      新.note  = 原.note(非空则不变) 或 邮箱(原为空)
      email / win / seq 没被动。

   还原就是右移回去:
        login = password'   name = login'   city = name'   acts = city'
        prem  = acts'       priv = prem'    note = priv'
   原 password 找不回来了(被 login 覆盖) -> 从账号文件按邮箱查回来;
   查不到就留空, 界面刷新时会自己从账号文件补上。

用法:
    python _修_结果错位.py            # 只看, 不改(默认)
    python _修_结果错位.py --apply    # 真的改(先自动备份)
"""
import json
import re
import shutil
import sys
import time
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

ROOT = _find_project_root(__file__)
APPLY = "--apply" in sys.argv
YN = {"是", "否"}
MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")
# ★ 活动数可能是 -1(引擎用它表示"读不到/私密"), 不能用 isdigit() 判
NUM = re.compile(r"^-?\d+$")
# ★ 真密码长相: 6~20 位纯字母数字(zx9kF7K3)。是/否/邮箱 一律不算密码。
PWD_LIKE = re.compile(r"^[A-Za-z0-9]{6,20}$")

# 右移映射: 新列 <- 现在哪一列的值
UNSHIFT = [("login", "password"), ("name", "login"), ("city", "name"),
           ("acts", "city"), ("prem", "acts"), ("priv", "prem"),
           ("note", "priv")]


def needs_fix(v):
    """判定这一条是否需要还原。

    用两列硬不变量 —— 它们取值范围固定, 移没移一眼能看出来:
        login 只能是 是/否;   acts 只能是数字(活动数, 可为 -1)
    """
    login = str(v.get("login") or "").strip()
    acts = str(v.get("acts") or "").strip()
    if login and login not in YN:
        return True
    if acts and not NUM.match(acts) and acts in YN:
        return True
    return False


def unshift(v):
    """算出还原后的记录。必须从【原始快照】取值, 不能边改边读(会连锁)。"""
    src = {f: v.get(f, "") for f in
           ("password", "login", "name", "city", "acts", "prem", "priv", "note")}
    nv = dict(v)
    for dst, srcf in UNSHIFT:
        nv[dst] = src[srcf]
    return nv


def valid(nv):
    """还原结果合不合规 —— 每一列都卡一遍。

    ★★ 为什么必须逐条验 ★★
      不是每条"看起来错位"的记录都真的错了一格。实测 bit_results 的 [_1]
      就是 login='是'(对) 但 acts='是'(错), 硬还原会把 acts 变成
      'Chicago, Illinois' —— 越修越坏。
      所以: 只修【还原后每一列都落回合理取值】的那些, 其余原样留着报出来。
    """
    lg = str(nv.get("login") or "").strip()
    ac = str(nv.get("acts") or "").strip()
    pr = str(nv.get("prem") or "").strip()
    nm = str(nv.get("name") or "").strip()
    ct = str(nv.get("city") or "").strip()
    if lg and lg not in YN:
        return False
    if ac and not NUM.match(ac):
        return False
    if pr and pr not in YN:
        return False
    if "," in nm:              # 人名不会带逗号; 带逗号说明这列其实是城市
        return False
    if NUM.match(ct):          # 城市不会是纯数字; 是数字说明这列其实是活动数
        return False
    return True


def acc_index(acc):
    """{邮箱小写: 密码} —— 用来把原 password 找回来。

    ★★ 必须验【像不像密码】(用户: "你确定修好了吗? 密码呢") ★★
       本工具第一次跑的时候账号文件【自己也坏了】(界面把坏表格存了回去),
       于是从这里"找回"的密码其实是 是/否 —— 等于没修, 还把坏值抄了一遍。
       所以只收 6~20 位纯字母数字; 其余一律当"没有", 留给
       _修_密码丢失.py 去历史快照里捞, 或让界面刷新时自己补。
    """
    idx = {}
    if isinstance(acc, dict):
        for _k, av in acc.items():
            if not isinstance(av, dict):
                continue
            e = str(av.get("email") or "").strip().lower()
            p = str(av.get("password") or "").strip()
            if e and PWD_LIKE.match(p):
                idx[e] = p
    return idx


def process(res_path, acc_path):
    if not res_path.is_file():
        print(f"[{res_path.name}] 不存在, 跳过")
        return
    d = json.loads(res_path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not d:
        print(f"[{res_path.name}] 空, 跳过")
        return
    acc = {}
    if acc_path.is_file():
        try:
            acc = json.loads(acc_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    A = acc_index(acc)

    fix_n, ok_n, skip_n = 0, 0, 0
    pwd_from_acc, pwd_blank = 0, 0
    skipped = []
    out = {}
    for k, v in d.items():
        if not isinstance(v, dict) or not needs_fix(v):
            out[k] = v
            ok_n += 1
            continue
        nv = unshift(v)
        if not valid(nv):
            # ★ 还原后不合规 -> 说明它不是干净的一格错位, 【绝不动它】
            out[k] = v
            skip_n += 1
            skipped.append(k)
            continue
        e = str(v.get("email") or "").strip()
        newp = A.get(e.lower())
        nv["password"] = newp if newp else ""
        if newp:
            pwd_from_acc += 1
        else:
            pwd_blank += 1
        out[k] = nv
        fix_n += 1

    # ---- 第二遍: 清掉被邮箱顶替的空备注 ----
    # ★ 有些记录的【备注原本就是空的】, 老刷新的第一句
    #      if not v[2] and a.get("email"): v[2] = a["email"]
    #   就把邮箱写了进去。这类没法从别的列推回来(原始值就是空),
    #   但特征很明确: 备注【完全等于】邮箱。正常备注是"账号：… 密码：…"
    #   或"关注…/小组…"这种, 不会是一个光秃秃的邮箱。
    note_cleaned = []
    for k, v in out.items():
        if not isinstance(v, dict):
            continue
        nt = str(v.get("note") or "").strip()
        em = str(v.get("email") or "").strip()
        if nt and em and nt.lower() == em.lower():
            nv = dict(v)
            nv["note"] = ""
            out[k] = nv
            note_cleaned.append(k)

    print("=" * 72)
    print(f"[{res_path.name}] 共 {len(d)} 条")
    print(f"    需要还原 : {fix_n} 条")
    print(f"    本来就正常: {ok_n} 条")
    print(f"    看着像错位、但还原后不合规 -> 保持原样: {skip_n} 条"
          + (f"  {skipped[:8]}" if skipped else ""))
    print(f"    备注是被邮箱顶掉的空备注 -> 清空: {len(note_cleaned)} 条")
    if fix_n:
        print(f"    密码从账号文件找回: {pwd_from_acc} 条; 留空待自动补: {pwd_blank} 条")

    # 还原后自检
    bad_after = 0
    for v in out.values():
        if not isinstance(v, dict):
            continue
        lg = str(v.get("login") or "").strip()
        ac = str(v.get("acts") or "").strip()
        if lg and lg not in YN:
            bad_after += 1
        elif ac and not NUM.match(ac) and ac in YN:
            bad_after += 1
    print(f"    还原后仍不合规: {bad_after} 条"
          + ("" if bad_after else "  (login 全是 是/否, acts 全是数字)"))

    if not APPLY:
        print("    (未改动 —— 加 --apply 才真的写)")
        return
    # ★ 不能只判断 fix_n: 第二遍"清空备注"是独立的一类改动,
    #   如果没有需要还原的行、但有需要清的备注, 这里必须照样写文件。
    if fix_n == 0 and not note_cleaned:
        print("    没有需要改的, 不写文件")
        return
    bak = res_path.with_name(res_path.name +
                             f".bak_before_错位还原_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(res_path, bak)
    tmp = res_path.with_name(res_path.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    import os
    os.replace(tmp, res_path)
    print(f"    已写回; 备份: {bak.name}")


print("模式:", "真的改(--apply)" if APPLY else "只看不改(默认)")
process(ROOT / "数据" / "ads_results.json", ROOT / "配置" / "ads_accounts.json")
process(ROOT / "数据" / "bit_results.json", ROOT / "配置" / "bit_accounts.json")
