# -*- coding: utf-8 -*-
"""实测候选主题的开销, 用数据挑。

方法: 把每个候选主题的 tcl 下到临时目录, 用同一个最小界面跑
      启动 / 填200行 / 更新50行, 和 clam 基线比。

★ 关键假设: 开销来自【重新定义控件布局的 tcl 代码量】。
  纯改配色的主题(只 set 颜色)应该几乎零开销;
  重画控件的(sv-ttk/azure 这类)会贵。这里验证这个假设。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
HDR = {"User-Agent": "Mozilla/5.0 (compatible; dsh-probe)"}

PROBE = r'''
import sys, time, json, pathlib
import tkinter as tk
from tkinter import ttk

mode = sys.argv[1]; tcl = sys.argv[2] if len(sys.argv) > 2 else ""
root = tk.Tk(); root.withdraw()
st = ttk.Style(root)
out = {}
t0 = time.time()
try:
    if mode == "clam":
        st.theme_use("clam")
        out["theme"] = "clam"
    elif mode == "vista":
        st.theme_use("vista")
        out["theme"] = "vista"
    elif mode == "tcl":
        root.tk.call("source", tcl)
        # 用这个 tcl 注册进来的第一个非内置主题名
        cands = [t for t in st.theme_names()
                 if t not in ("winnative","clam","alt","default","classic",
                              "vista","xpnative")]
        if cands:
            st.theme_use(cands[-1]); out["theme"] = cands[-1]
        else:
            out["theme"] = "?"; out["warn"] = "tcl 没注册新主题"
except Exception as e:
    out["err"] = "%s: %s" % (type(e).__name__, str(e)[:90])
    print("PROBE=" + json.dumps(out, ensure_ascii=False)); sys.exit(0)

f = ttk.Frame(root); f.pack()
for i in range(8):
    ttk.Button(f, text="按钮%d" % i).pack(side="left")
for _ in range(6):
    ttk.Entry(f, width=14).pack(side="left")
ttk.Checkbutton(f, text="勾").pack(side="left")
ttk.Combobox(f, values=["a","b"], width=8).pack(side="left")
fr = ttk.LabelFrame(root, text="表"); fr.pack(fill="both", expand=True)
tv = ttk.Treeview(fr, columns=[str(i) for i in range(8)], show="headings", height=14)
for i in range(8):
    tv.heading(str(i), text="列%d" % i); tv.column(str(i), width=90)
tv.pack(fill="both", expand=True)
root.update()
out["build_ms"] = (time.time() - t0) * 1000      # 含建窗口+控件

rows = [tuple("r%dc%d" % (r, c) for c in range(8)) for r in range(200)]
t0 = time.time()
for i, r in enumerate(rows):
    tv.insert("", "end", iid=str(i), values=r)
root.update()
out["fill200_ms"] = (time.time() - t0) * 1000
root.destroy()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''

CANDS = [
    ("clam(基线)", "clam", None),
    ("vista(系统原生)", "vista", None),
    ("azure(rdbende)", "tcl", "https://raw.githubusercontent.com/rdbende/Azure-ttk-theme/main/azure.tcl"),
    ("sun-valley(rdbende)", "tcl", "https://raw.githubusercontent.com/rdbende/Sun-Valley-ttk-theme/main/sv_ttk/sv.tcl"),
]


def download(url, dst):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR),
                                timeout=60) as r:
        dst.write_bytes(r.read())


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="thmperf_"))
    pf = tmp / "_p.py"; pf.write_text(PROBE, encoding="utf-8")
    print("=" * 88)
    print("候选主题性能实测(同一个最小界面, 各跑 2 次取最好)")
    print("=" * 88)
    print("  %-24s %-12s %-14s %s" % ("主题", "建窗口(ms)", "填200行(ms)", "备注"))
    print("  " + "-" * 84)

    base = None
    for name, mode, url in CANDS:
        tcl = ""
        if url:
            tcl = str(tmp / (name.split("(")[0] + ".tcl"))
            try:
                download(url, pathlib.Path(tcl))
                # rdbende 的两个都需要连同 theme/ 目录, 单独一个 sv.tcl 可能不完整
                sz = pathlib.Path(tcl).stat().st_size
            except Exception as e:
                print("  %-24s ★ 下载失败: %s" % (name, str(e)[:40])); continue
        best = None
        for _ in range(2):
            env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
            r = subprocess.run([sys.executable, str(pf), mode, tcl], cwd=str(tmp),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=200, env=env)
            res = None
            for line in (r.stdout or "").splitlines():
                if line.startswith("PROBE="):
                    res = json.loads(line[6:])
            if res and "build_ms" in res:
                if best is None or res["build_ms"] < best["build_ms"]:
                    best = res
        if best is None:
            print("  %-24s ★ 跑不起来" % name); continue
        if base is None:
            base = best["build_ms"]
        note = best.get("err") or best.get("warn") or best.get("theme", "")
        print("  %-24s %-12.0f %-14.0f %s"
              % (name, best["build_ms"], best["fill200_ms"], str(note)[:36]))
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("  ★ 结论看第二列: 越小越不卡。基线是 clam, 比它大一倍以上就是「贵」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
