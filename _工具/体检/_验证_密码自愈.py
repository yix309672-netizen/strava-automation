# -*- coding: utf-8 -*-
"""验证"密码列"在错位自愈里也能被救回来。

★★ 用户问 "你确定修好了吗? 密码呢" —— 原来的自愈确实没修密码 ★★
   错位时 password 被原 login 覆盖(变成 是/否), 而 _unshift 的映射表里
   根本没有 password 这一项 -> 自愈后 password 还是 是/否;
   refresh_results 又只在【单元格为空】时才补 -> 坏值永远赖着不走,
   再被 _save_accounts 写回账号文件, 于是账号文件里的真密码也被冲掉。

本脚本验 5 件事(每条都必须过):
   ① 自愈时按邮箱把真密码从账号文件找回来
   ② 邮箱查不到时, password 必须【清空】而不是留 是/否
   ③ _restore() 走完: 表格和磁盘上的密码都是真的
   ④ refresh_results(): 单元格里已是 是/否 的, 也要被真密码顶掉
   ⑤ _save_accounts(): 表格里是 是/否 时, 绝不能拿它覆盖账号文件里的真密码
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
UN = [("login", "password"), ("name", "login"), ("city", "name"),
      ("acts", "city"), ("prem", "acts"), ("priv", "prem"), ("note", "priv")]
PWD = "zx9kF7K3"                     # 真密码长相: 8 位字母数字

GOOD = {"seq": "48", "win": "_48", "email": "a@b.com", "password": PWD,
        "login": "是", "name": "Natalie Jiang", "city": "Chicago, Illinois",
        "acts": "50", "prem": "是", "priv": "已设置", "note": "Irene Du"}
# ★ 键用 win(=_48/_49/_51) —— _save_accounts 就是按 win 当键写的,
#   这样 ⑤ 才能真的验到"坏值有没有把账号文件里的真密码冲掉"
ACC = {"_48": {"email": "a@b.com", "password": PWD},
       "_49": {"email": "a@b.com", "password": PWD},
       "_51": {"email": "nobody@nowhere.com", "password": PWD}}


def shift(d):
    """把一行左移一格, 模拟被写坏的样子(和真机一致)。"""
    out = dict(d)
    for dst, s in UN:
        out[s] = d.get(dst, "")
    return out


ok_all = True
# ★ 分发包里的那两份(同事真正拿到的)也必须一起测 ——
#   只测源码等于没测: _同步分发.py 忘了拷就是"改了却发不出去"。
for tag, gui in (("源码 ADS", ROOT / "界面" / "ADS自动化.py"),
                 ("源码 BIT", ROOT / "界面" / "比特派自动化.py"),
                 ("分发 _gui_ads", ROOT / "_分发给同事" / "_gui_ads.py"),
                 ("分发 _gui_bit", ROOT / "_分发给同事" / "_gui_bit.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_pwd_"))
    resfile, accfile = tmp / "res.json", tmp / "acc.json"
    broken = shift(GOOD)                      # password 被 login 顶成了 "是"
    broken["seq"] = "49"
    broken["win"] = "_49"
    orphan = shift(GOOD)                      # 邮箱在账号文件里查不到
    orphan["seq"] = "51"
    orphan["win"] = "_51"
    orphan["email"] = "nobody@nowhere.com"
    resfile.write_text(json.dumps({"48": GOOD, "49": broken, "51": orphan},
                                  ensure_ascii=False), encoding="utf-8")
    accfile.write_text(json.dumps(ACC, ensure_ascii=False), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("_p_" + tag, gui)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_p_" + tag] = m
    spec.loader.exec_module(m)
    m.RES_FILE, m.ACC_FILE = resfile, accfile

    cases = []

    # ① / ② 纯函数: 带账号文件自愈
    data = json.loads(resfile.read_text(encoding="utf-8"))
    try:
        healed, n = m.heal_shifted(data, ACC)
    except TypeError:                          # 还没加 acc 参数 -> 就是没修
        healed, n = m.heal_shifted(data)
    cases.append(("① 坏密码按邮箱从账号文件找回",
                  healed["49"].get("password") == PWD,
                  f"救回={healed['49'].get('password')!r}"))
    cases.append(("② 查不到邮箱的清空(不留 是/否)",
                  str(healed["51"].get("password") or "") not in ("是", "否"),
                  f"值是 {healed['51'].get('password')!r}"))

    # ③ 真实 _restore(): 表格 + 磁盘
    app = m.App()
    app.withdraw()
    app._restore()
    iP = list(m.FIELDS).index("password")
    vals = {iid: list(app.tree.item(iid, "values"))
            for iid in app.tree.get_children()}
    cases.append(("③ 表格里 49 行密码是真的",
                  str(vals.get("49", [""] * 9)[iP]) == PWD,
                  f"表格={vals.get('49', [''] * 9)[iP]!r}"))
    on_disk = json.loads(resfile.read_text(encoding="utf-8"))
    cases.append(("③ 磁盘上 49 行密码也是真的",
                  on_disk["49"].get("password") == PWD,
                  f"磁盘={on_disk['49'].get('password')!r}"))

    # ④ refresh_results(): 表格里已是坏值也要被顶掉
    app.tree.set("49", "password", "是")
    app.refresh_results()
    got = [list(app.tree.item("49", "values"))[iP]
           for _ in [0] if app.tree.exists("49")]
    cases.append(("④ 刷新把单元格里的 是 顶成真密码",
                  str(got[0] if got else "") == PWD, f"刷新后={got!r}"))

    # ⑤ _save_accounts(): 坏值绝不能覆盖账号文件
    app.tree.set("49", "password", "是")
    app._save_accounts()
    acc_disk = json.loads(accfile.read_text(encoding="utf-8"))
    cases.append(("⑤ 坏值没冲掉账号文件里的真密码",
                  str(acc_disk.get("_49", {}).get("password")) == PWD,
                  f"_49 号={acc_disk.get('_49', {}).get('password')!r}"))
    app.destroy()

    print("=" * 74)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:30s} {detail}")
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("★★★ 密码列也能自愈了 ★★★" if ok_all else "★★★ 有失败项 —— 密码还没修好 ★★★")
sys.exit(0 if ok_all else 1)
