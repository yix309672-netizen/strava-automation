# -*- coding: utf-8 -*-
"""把候选主题【真正装好】再测性能, 单下 tcl 跑不起来不算数。

三条路线:
  A. 纯配色主题(ttkthemes 里的 arc/breeze/...): 只 set 颜色, 理论上零开销
  B. rdbende 那套(sv-ttk / azure): 重定义控件布局, 预计贵
  C. 系统原生(vista): 零额外开销(系统画)
测同一个最小界面的建窗口 + 填 200 行。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
import io
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
HDR = {"User-Agent": "Mozilla/5.0 (compatible; dsh-probe)"}

PROBE = r'''
import sys, time, json, pathlib
import tkinter as tk
from tkinter import ttk

kind = sys.argv[1]; arg = sys.argv[2] if len(sys.argv) > 2 else ""
libdir = sys.argv[3] if len(sys.argv) > 3 else ""
if libdir:
    sys.path.insert(0, libdir)

out = {}
t0 = time.time()
try:
    if kind == "ttkthemes":
        from ttkthemes import ThemedTk
        root = ThemedTk(theme=arg, toplevel=False); root.withdraw()
    else:
        root = tk.Tk(); root.withdraw()
        st = ttk.Style(root)
        if kind == "sv":
            import sv_ttk; sv_ttk.set_theme(arg)
        elif kind == "name":
            st.theme_use(arg)
        elif kind == "tcl":
            root.tk.call("source", arg)
            cands = [t for t in st.theme_names()
                     if t not in ("winnative","clam","alt","default","classic",
                                  "vista","xpnative")]
            if cands: st.theme_use(cands[-1])
    st = ttk.Style(root)
    out["theme"] = st.theme_use()
except Exception as e:
    out["err"] = "%s: %s" % (type(e).__name__, str(e)[:90])
    print("PROBE=" + json.dumps(out, ensure_ascii=False)); sys.exit(0)

f = ttk.Frame(root); f.pack()
for i in range(8): ttk.Button(f, text="按钮%d" % i).pack(side="left")
for _ in range(6): ttk.Entry(f, width=14).pack(side="left")
ttk.Checkbutton(f, text="勾").pack(side="left")
ttk.Combobox(f, values=["a","b"], width=8).pack(side="left")
fr = ttk.LabelFrame(root, text="表"); fr.pack(fill="both", expand=True)
tv = ttk.Treeview(fr, columns=[str(i) for i in range(8)], show="headings", height=14)
for i in range(8):
    tv.heading(str(i), text="列%d" % i); tv.column(str(i), width=90)
tv.pack(fill="both", expand=True)
root.update()
out["build_ms"] = (time.time() - t0) * 1000
rows = [tuple("r%dc%d" % (r, c) for c in range(8)) for r in range(200)]
t0 = time.time()
for i, r in enumerate(rows): tv.insert("", "end", iid=str(i), values=r)
root.update()
out["fill200_ms"] = (time.time() - t0) * 1000
root.destroy()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def pip_install(target, *pkgs):
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--target", str(target), *pkgs],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-200:]


def run(kind, arg="", libdir=""):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tp_"))
    pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
    best = None
    for _ in range(2):
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), kind, arg, libdir],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res and "build_ms" in res:
            if best is None or res["build_ms"] < best["build_ms"]:
                best = res
    shutil.rmtree(tmp, ignore_errors=True)
    return best


def main():
    print("=" * 92)
    print("主题性能实测(建好再测, 不是单下 tcl)")
    print("=" * 92)
    print("  %-26s %-13s %-13s %s" % ("主题", "建窗口(ms)", "填200行(ms)", "说明"))
    print("  " + "-" * 88)

    base = run("name", "clam")
    b = base["build_ms"] if base else 0
    if base:
        print("  %-26s %-13.0f %-13.0f %s" % ("clam(现状基线)", base["build_ms"],
                                              base["fill200_ms"], "零额外开销"))
    for t in ("vista", "alt", "classic", "default"):
        r = run("name", t)
        if r:
            print("  %-26s %-13.0f %-13.0f %s" % ("内置 " + t, r["build_ms"],
                                                  r["fill200_ms"],
                                                  "%.1fx" % (r["build_ms"] / b)))

    # sv-ttk(已内置在项目里)
    for t in ("light", "dark"):
        r = run("sv", t, str(ROOT))
        if r:
            print("  %-26s %-13.0f %-13.0f %s" % ("sv-ttk " + t, r["build_ms"],
                                                  r["fill200_ms"],
                                                  "%.1fx (贵)" % (r["build_ms"] / b)))

    # ttkthemes: 临时装一份, 只为挑主题, 不进项目
    lib = pathlib.Path(tempfile.mkdtemp(prefix="ttklib_"))
    print()
    print("  正在临时安装 ttkthemes(只为挑选, 不进项目) ...")
    ok, msg = pip_install(lib, "ttkthemes")
    if not ok:
        print("  ★ 装不上: %s" % msg); return 1
    try:
        sys.path.insert(0, str(lib))
        import importlib
        import ttkthemes
        importlib.reload(ttkthemes)
        names = sorted(ttkthemes.THEMES)
        print("  ttkthemes 提供 %d 个主题: %s" % (len(names), names))
        print()
        picks = [n for n in ("arc", "breeze", "equilux", "scid", "yaru", "adapta",
                             "black", "clearlooks", "itft1", "plastik", "radiance",
                             "smog") if n in names]
        for t in picks:
            r = run("ttkthemes", t, str(lib))
            if r:
                print("  %-26s %-13.0f %-13.0f %s"
                      % ("ttkthemes/" + t, r["build_ms"], r["fill200_ms"],
                         "%.1fx" % (r["build_ms"] / b)))
            else:
                print("  %-26s ★ 跑不起来" % ("ttkthemes/" + t))
    finally:
        shutil.rmtree(lib, ignore_errors=True)
    print()
    print("  ★ 挑「建窗口」最接近 clam 的那个 —— 那就是不卡又好看的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
