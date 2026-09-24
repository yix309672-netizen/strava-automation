# -*- coding: utf-8 -*-
"""验证界面里的「列错位自愈」。

用户报「脚本主页信息又错位了。不能固定死吗?」—— 要的就是这个:
界面读到错位的数据时【自己掰回来并写回文件】, 而不是原样显示、再原样存回去。

验三件事:
  ① 纯函数 heal_shifted: 错位的掰回来, 本来就对的【一根汗毛都不动】
  ② _restore() 走完: 表格里是对的, 而且磁盘上的文件也被治好
  ③ 复验不过的行要【保持原样】, 绝不越修越坏
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


def shift(d):
    """把一行【左移一格】, 模拟被写坏的样子。

    ★★ 方向别搞反(第一版就反了, 结果测了个假的) ★★
      自愈是  nv[dst] = src[s]:
          login←password  name←login  city←name  acts←city
          prem←acts       priv←prem   note←priv
      那么被写坏时的【正向】就是  out[s] = d[dst]:
          out.password=原login  out.login=原name  out.name=原city …
      也就是"登录列里躺着名字、城市列里躺着活动数"—— 和真机上看到的一模一样。
    """
    out = dict(d)
    for dst, s in UN:
        out[s] = d.get(dst, "")
    return out


GOOD = {"seq": "48", "win": "48", "email": "a@b.com", "password": "PW1",
        "login": "是", "name": "Natalie Jiang", "city": "Chicago, Illinois",
        "acts": "50", "prem": "是", "priv": "已设置", "note": "Irene Du"}

ok_all = True
for tag, gui in (("ADS", ROOT / "界面" / "ADS自动化.py"),
                 ("BIT", ROOT / "界面" / "比特派自动化.py")):
    tmp = Path(tempfile.mkdtemp(prefix="_heal_"))
    resfile = tmp / "ads_results.json"
    # 磁盘上放: 1 条好的 + 1 条错位的 + 1 条"看着像错位但掰不动"的
    broken = shift(GOOD)
    broken["seq"] = "49"
    weird = dict(GOOD, seq="50", login="某某人", acts="不是数字")
    resfile.write_text(json.dumps({"48": GOOD, "49": broken, "50": weird},
                                  ensure_ascii=False), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("_g_" + tag, gui)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_g_" + tag] = m
    spec.loader.exec_module(m)
    m.RES_FILE = resfile          # 让界面读我们造的这个文件

    cases = []

    # ① 纯函数
    #   ★ 只比【掰得回来的列】: password 是找不回来的 —— 错位时它被 login
    #     覆盖了(原始密码没了)。真机上靠账号文件补, 见 _修_结果错位.py。
    #     第一版直接比整个 dict, 于是把"实现正确"报成了失败。
    RECOVERABLE = ("login", "name", "city", "acts", "prem", "priv", "note")
    data = json.loads(resfile.read_text(encoding="utf-8"))
    healed, n = m.heal_shifted(data)
    cases.append(("heal_shifted 只掰坏的那条", n == 1, f"修了 {n} 条"))
    cases.append(("好的那条一根汗毛没动",
                  healed["48"] == GOOD, f"{healed['48'].get('login')!r}"))
    _bad_vs_good = [f for f in RECOVERABLE
                    if healed["49"].get(f) != GOOD.get(f)]
    cases.append(("坏的那条掰回正确值", not _bad_vs_good,
                  f"不符的列={_bad_vs_good or '无'}"))
    cases.append(("掰不动的保持原样",
                  healed["50"] == weird, "原样保留"))

    # ② 走真实 _restore(): 表格对不对 + 磁盘治没治好
    app = m.App()
    app.withdraw()
    app._restore()
    vals = {}
    for iid in app.tree.get_children():
        vals[iid] = list(app.tree.item(iid, "values"))
    i_login = list(m.FIELDS).index("login")
    i_name = list(m.FIELDS).index("name")
    _row49 = vals.get("49", [""] * len(m.FIELDS))
    cases.append(("表格里那条已是正确值",
                  str(_row49[i_login]) == "是"
                  and str(_row49[i_name]) == "Natalie Jiang",
                  f"login={_row49[i_login]!r} name={_row49[i_name]!r}"))
    on_disk = json.loads(resfile.read_text(encoding="utf-8"))
    cases.append(("磁盘上也被治好了",
                  on_disk["49"].get("login") == "是"
                  and on_disk["49"].get("acts") == "50",
                  f"login={on_disk['49'].get('login')!r} acts={on_disk['49'].get('acts')!r}"))
    app.destroy()

    print("=" * 74)
    print(f"===== {tag} =====")
    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:28s} {detail}")
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("★★★ 界面会自己把错位掰回来, 并写回文件 ★★★" if ok_all else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
