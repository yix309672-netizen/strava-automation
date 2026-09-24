# -*- coding: utf-8 -*-
"""验证: 给人看的版本号, 从真源一路走到界面标题栏, 且发得出去。

为什么要有这个: 版本号最大的价值是【同事能报出自己跑的是哪一版】。
这条链上任何一环断了都会【静默】退化(兜底成 "v?"、标题栏空白),
不报错, 所以必须专门验。断点一共五处:
    ① 真源         主脚本/app_version.py 在不在、VERSION 合不合法
    ② 引擎         两个引擎都 import 得到吗(import 失败会兜底成 "v?")
    ③ 界面         标题栏真的显示出来了吗(真建窗口读 title())
    ④ 同步清单     _同步分发.py 的 PAIRS 里有没有它 —— 漏了同事包里就没有
    ⑤ 打包守卫     _打包给同事.py 的 NEED 里有没有它 —— 漏了打包不会挡
"""
import importlib.util, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "_分发给同事"
ok_all = True


def case(name, ok, detail=""):
    global ok_all
    if not ok:
        ok_all = False
    print(f"   {'OK ' if ok else '★  '}{name:36s} {detail}")


def load(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[tag] = m
    spec.loader.exec_module(m)
    return m


# ---- ① 真源 ----
src = ROOT / "主脚本" / "app_version.py"
case("① 真源在 主脚本/app_version.py", src.is_file())
if not src.is_file():
    sys.exit(1)
V = load(src, "ver_src")
case("① VERSION 形如 vX.Y", bool(re.match(r"^v\d+\.\d+$", V.VERSION)), V.VERSION)
case("① 有日期", bool(re.match(r"^\d{4}-\d{2}-\d{2}$", V.DATE)), V.DATE)
case("① label() 可读", V.label() == f"{V.VERSION} · {V.DATE}", V.label())

# ---- ② 引擎 + ③ 界面 ----
for eng, gui, tag in (("strava_ads.py", "ADS自动化.py", "ADS"),
                      ("strava_bit.py", "比特派自动化.py", "BIT")):
    print(f"===== {tag} =====")
    em = load(ROOT / "主脚本" / eng, "ve_" + tag)
    case("② 引擎读到真源的值", em.APP_VERSION == V.VERSION,
         f"{em.APP_VERSION} (不是兜底的 v?)")
    case("② 引擎有 ver_label", callable(getattr(em, "ver_label", None)))
    try:
        gm = load(ROOT / "界面" / gui, "vg_" + tag)
        gm.SA = em
        app = gm.App()
        app.withdraw()
        app.update()
        title = app.title()
        app.destroy()
        case("③ 标题栏显示了版本", V.VERSION in title, repr(title))
        case("③ 标题栏有日期", V.DATE in title)
    except Exception as e:
        case("③ 标题栏显示了版本", False, f"起界面失败: {str(e)[:60]}")

# ---- ④ 同步清单 ----
t = (ROOT / "_同步分发.py").read_text(encoding="utf-8")
case("④ _同步分发.py PAIRS 里有它",
     '("主脚本/app_version.py", "app_version.py")' in t)

# ---- ⑤ 打包守卫 ----
t2 = (ROOT / "_打包给同事.py").read_text(encoding="utf-8")
case("⑤ _打包给同事.py NEED 里有它", '"app_version.py"' in t2)

# ---- ⑥ 分发包里有没有(没同步过就会缺) ----
d = DIST / "app_version.py"
if d.is_file():
    case("⑥ 分发包里已有(值一致)",
         load(d, "ver_dist").VERSION == V.VERSION)
else:
    case("⑥ 分发包里已有", False, "还没同步 —— 跑一次 _同步分发.py")

# ---- ⑦ 桌面推送脚本(另一条发布路径) ----
desk = Path.home() / "Desktop" / "一键推送更新.py"
if desk.is_file():
    case("⑦ 桌面推送脚本也登记了", "app_version.py" in desk.read_text(encoding="utf-8"))
else:
    case("⑦ 桌面推送脚本也登记了", False, f"找不到 {desk}")

print()
print("=" * 74)
print("★★★ 版本号全链路就绪: 真源 -> 引擎 -> 界面标题栏 -> 发得出去 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
