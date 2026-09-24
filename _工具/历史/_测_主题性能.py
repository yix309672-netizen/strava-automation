# -*- coding: utf-8 -*-
"""横向实测几个开源 ttk 主题的【性能代价】, 用数据挑一个不卡的。

已排除的:
  sv-ttk(Sun Valley) 启动 964ms / 填表 157ms —— 比基线慢 2.7 倍, 太贵。

被测的:
  · ttkthemes 里的几个纯 tcl 主题(arc / breeze / equilux / scid / yaru ...)
    纯 tcl 换配色, 【不重定义控件布局】-> 通常几乎零开销, 这是重点怀疑对象里的好苗子
  · azure-ttk-theme / forest-ttk-theme(rdbende 那套, 和 sv-ttk 同作者)
    ★ 这两个是 .tcl 文件, 同样要重定义控件 -> 预计也贵, 但要量了才知道

口径统一: 用同一个最小界面(若干按钮+输入框+200 行表格)测
   启动 / 填 200 行 / 更新 50 行
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

PROBE = r'''
import sys, time, pathlib, json
sys.path.insert(0, sys.argv[1])          # 主题库目录
import tkinter as tk
from tkinter import ttk

mode = sys.argv[2]
theme = sys.argv[3] if len(sys.argv) > 3 else ""

out = {}
t0 = time.time()
root = tk.Tk(); root.withdraw()
st = ttk.Style(root)

if mode == "ttkthemes" and theme:
    from ttkthemes import ThemedTk
    root.destroy()
    root = ThemedTk(theme=theme, toplevel=False); root.withdraw()
    st = ttk.Style(root)
elif mode == "tclfile" and theme:
    # rdbende 那套: 直接 source 它的 tcl
    root.tk.call("source", theme)
    st.theme_use("azure" if "azure" in theme.lower() else "forest-light")
elif mode == "svg" and theme:
    import sv_ttk
    sv_ttk.set_theme(theme)
elif mode == "clam":
    try:
        st.theme_use("clam")
    except Exception:
        pass

out["theme"] = st.theme_use()

# ---- 造一个和实际界面差不多的控件集 ----
f = ttk.Frame(root); f.pack()
btns = [ttk.Button(f, text="按钮%d" % i) for i in range(8)]
for b in btns: b.pack(side="left")
ents = [ttk.Entry(f, width=14) for _ in range(6)]
for e in ents: e.pack(side="left")
ttk.Checkbutton(f, text="勾选").pack(side="left")
ttk.Combobox(f, values=["a", "b"], width=8).pack(side="left")
fr = ttk.LabelFrame(root, text="表"); fr.pack(fill="both", expand=True)
tv = ttk.Treeview(fr, columns=[str(i) for i in range(8)], show="headings", height=14)
for i in range(8):
    tv.heading(str(i), text="列%d" % i); tv.column(str(i), width=90)
tv.pack(fill="both", expand=True)
root.update()
out["startup_ms"] = (time.time() - t0) * 1000

rows = [tuple("r%dc%d" % (r, c) for c in range(8)) for r in range(200)]
t0 = time.time()
for i, r in enumerate(rows):
    tv.insert("", "end", iid=str(i), values=r, tags=("odd" if i % 2 else "even"))
root.update()
out["fill200_ms"] = (time.time() - t0) * 1000

t0 = time.time()
for i in range(50):
    v = list(tv.item(str(i), "values")); v[0] = "x"
    tv.item(str(i), values=tuple(v))
root.update()
out["set50_ms"] = (time.time() - t0) * 1000
root.destroy()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def probe(mode, theme="", libdir=None):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="thm_"))
    pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, str(pf), str(libdir or ROOT), mode, theme],
                       cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, env=env)
    shutil.rmtree(tmp, ignore_errors=True)
    for line in (r.stdout or "").splitlines():
        if line.startswith("PROBE="):
            return json.loads(line[6:])
    return {"err": ((r.stdout or "") + (r.stderr or ""))[-160:]}


def main():
    print("=" * 90)
    print("开源 ttk 主题 —— 性能横向对比(同一个最小界面)")
    print("=" * 90)
    print("  %-26s %-10s %-12s %-12s %s"
          % ("主题", "换算", "启动(ms)", "填200行(ms)", "更新50行(ms)"))
    print("  " + "-" * 86)

    base = probe("clam")
    if "err" in base:
        print("  ★ 基线失败: %s" % base["err"]); return 1
    print("  %-26s %-10s %-12.0f %-12.0f %.0f"
          % ("clam(基线/现用)", "-", base["startup_ms"], base["fill200_ms"],
             base["set50_ms"]))

    for t in ("light", "dark"):
        r = probe("svg", t)
        if "err" in r:
            print("  %-26s ★ %s" % ("sv-ttk " + t, r["err"][:40])); continue
        print("  %-26s %-10s %-12.0f %-12.0f %.0f"
              % ("sv-ttk " + t,
                 "%.1fx" % (r["startup_ms"] / base["startup_ms"]),
                 r["startup_ms"], r["fill200_ms"], r["set50_ms"]))

    # ttkthemes 里的纯 tcl 主题
    try:
        import ttkthemes  # noqa
        have = True
    except Exception:
        have = False
    if not have:
        print()
        print("  (ttkthemes 没装 —— 下面这些要在临时环境里装, 可能会慢)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
