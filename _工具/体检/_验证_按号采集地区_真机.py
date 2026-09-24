# -*- coding: utf-8 -*-
"""真机冒烟: 把界面真建起来, 验 13 列表格 + 按号设置收集 + _fill 回填。"""
import importlib.util, sys, tkinter as tk
sys.stdout.reconfigure(errors="replace")
ROOT = r"C:\Users\1\Desktop\Strava自动化_备份_20260917"
spec = importlib.util.spec_from_file_location("gui", ROOT + r"\界面\ADS自动化.py")
M = importlib.util.module_from_spec(spec); sys.modules["gui"] = M; spec.loader.exec_module(M)
print("FIELDS:", M.FIELDS)
app = M.App()
app.withdraw()
app.update()
cols = app.tree["columns"]
print("表格列数:", len(cols), "->", "OK" if len(cols) == len(M.FIELDS) else "★不符")
# 造两行, 一行设地区一行留空
app._fill([("1","_1","a@b.c","pw","是","Name","Los Angeles, California","38","否","已设置","New Jersey","只要 65-69 (单个)","note"),
           ("2","_2","d@e.f","pw","是","Name2","Los Angeles, California","38","否","已设置","","",  "note")])
app.update()
vals1 = app.tree.item("1","values"); vals2 = app.tree.item("2","values")
print("1号 region/age:", vals1[M.FIELDS.index("region")], "/", vals1[M.FIELDS.index("age")])
print("2号 region/age:", repr(vals2[M.FIELDS.index("region")]), "/", repr(vals2[M.FIELDS.index("age")]))
# 复刻 _start 里的 rowset 收集
rowset = {}
for iid in app.tree.get_children():
    v = app.tree.item(iid, "values")
    _r = str(v[M.FIELDS.index("region")] or "").strip()
    _a = str(v[M.FIELDS.index("age")] or "").strip()
    if _r or _a: rowset[int(v[M.I_SEQ])] = (_r, _a)
print("rowset:", rowset, "->", "OK" if rowset == {1: ("New Jersey", "只要 65-69 (单个)")} else "★不符")
# 复刻 _work 里的 cfg 覆盖
cfg = {"collect_regions": ["默认地区"], "collect_age_groups": ["55_64","65_69"]}
def apply(seq):
    _c = cfg; _rs = rowset.get(seq)
    if _rs:
        _c = dict(cfg)
        if _rs[0]: _c["collect_regions"] = [_rs[0]]
        if _rs[1]: _c["collect_age_groups"] = list(M._value_of(M.AGE_CHOICES, _rs[1]))
    return _c
c1, c2 = apply(1), apply(2)
print("1号 cfg:", c1["collect_regions"], c1["collect_age_groups"])
print("2号 cfg:", c2["collect_regions"], c2["collect_age_groups"])
ok1 = c1["collect_regions"] == ["New Jersey"] and c1["collect_age_groups"] == ["65_69"]
ok2 = c2 is cfg
print("1号覆盖正确:", ok1, "| 2号留空原封不动:", ok2)
app.destroy()
print()
print("=== 冒烟", "通过 ===" if (ok1 and ok2 and rowset == {1:("New Jersey","只要 65-69 (单个)")}) else "★失败 ===")
