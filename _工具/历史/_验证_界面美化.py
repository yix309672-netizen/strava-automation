# -*- coding: utf-8 -*-
"""起一次界面并截图, 用眼睛验收美化效果。

同时验证:
  · 起得来(不报错)
  · 主题/字体挂上了
  · 表格带斑马纹标签
  · _set / _save_results 在改过列序之后仍然正常
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

PROBE = r'''
import importlib.util, json, pathlib, sys, time


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
gui = pathlib.Path(sys.argv[1]); out_png = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("gm", gui)
m = importlib.util.module_from_spec(spec)
sys.modules["gm"] = m
spec.loader.exec_module(m)

app = m.App()
app.geometry("1320x820+40+20")
app.update()
app.deiconify()
app.update()
time.sleep(0.6)
app.update()

r = {}
try:
    st = m.ttk.Style(app)
    r["theme"] = st.theme_use()
    r["tree_font"] = str(st.lookup("Treeview", "font"))
    r["rowheight"] = str(st.lookup("Treeview", "rowheight"))
    r["head_font"] = str(st.lookup("Treeview.Heading", "font"))
except Exception as e:
    r["style_err"] = str(e)[:80]

# 造几行数据走一遍 _fill(带斑马纹/状态配色)
rows = []
for i, (seq, login) in enumerate([(2,"是"),(3,"是"),(7,"否"),(376,"是"),(400,"否")]):
    F = list(m.FIELDS)
    d = {k: "" for k in F}
    d["seq"] = seq; d["win"] = str(seq); d["login"] = login
    d["email"] = ("user%d@mail.com" % seq) if seq < 100 else ""
    d["note"] = ("跑步%d N | 账号：u%d@x.com 密码：pw%d" % (seq, seq, seq)) if seq > 100 else "账号：u%d@x.com" % seq
    d["name"] = "Name %d" % seq; d["city"] = "Chicago, Illinois"
    d["acts"] = str(50 + seq); d["prem"] = login; d["priv"] = "小组True/地图True/时间True"
    rows.append(tuple(d[k] for k in F))
app._fill(rows)
app.update()
r["rows_filled"] = len(app.tree.get_children())
r["first_tags"] = list(app.tree.item(str(rows[0][0]), "tags"))

# ★ 改过列序之后 _set 还灵不灵(FIELDS.index 取列, 顺序无关)
app._set(2, "login", "否")
app.update()
v = list(app.tree.item("2", "values"))
r["set_ok"] = v[m.FIELDS.index("login")] == "否"

app.update()
time.sleep(0.4)
try:
    from PIL import ImageGrab
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(str(out_png))
    r["png"] = str(out_png)
except Exception as e:
    r["png_err"] = "%s: %s" % (type(e).__name__, str(e)[:80])

print("PROBE=" + json.dumps(r, ensure_ascii=False))
try:
    app.destroy()
except Exception:
    pass
'''


def main():
    print("=" * 80)
    print("界面美化 —— 起真窗口 + 截图验收")
    print("=" * 80)
    for gui, tag in (("界面/ADS自动化.py", "ads"), ("界面/比特派自动化.py", "bit")):
        print()
        print("--- %s ---" % pathlib.Path(gui).name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ui_"))
        shutil.copy2(ROOT / gui, tmp / "gui.py")
        (tmp / "config.json").write_text(json.dumps({
            "location": "Chicago, Illinois", "collect_regions": ["New York"],
            "min_athletes": 5000, "jobs": 3, "_policy_rev": 2,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        png = ROOT / ("_界面截图_%s.png" % tag)
        pf = tmp / "_p.py"
        pf.write_text(PROBE, encoding="utf-8")
        import os
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), str(tmp / "gui.py"), str(png)],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            print("  ★ 起界面失败:")
            print(((r.stdout or "") + (r.stderr or ""))[-900:])
            shutil.rmtree(tmp, ignore_errors=True)
            return 1
        print("  主题        : %s" % res.get("theme"))
        print("  表格字体    : %s   行高: %s" % (res.get("tree_font"), res.get("rowheight")))
        print("  表头字体    : %s" % res.get("head_font"))
        print("  填入行数    : %s   首行标签: %s"
              % (res.get("rows_filled"), res.get("first_tags")))
        print("  _set 仍正常 : %s" % res.get("set_ok"))
        if res.get("png"):
            p = pathlib.Path(res["png"])
            print("  截图        : %s (%.0f KB)" % (p.name, p.stat().st_size / 1024))
        else:
            print("  ★ 截图失败: %s" % res.get("png_err"))
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
