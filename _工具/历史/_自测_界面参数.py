# -*- coding: utf-8 -*-
"""_自测_界面参数.py —— 新采集参数落地自测(不联网、不开浏览器)

测什么(两个界面文件各测一遍, 逻辑必须完全一致):
  1) 真起一个 Tk 窗口(不是 mock), 证明界面还能建起来、不报 TclError;
  2) 「每州路段」「每段查人」两个输入框已消失;
  3) 新的「每号目标人数」输入框存在、是 ttk.Spinbox、范围 1~2000、默认 200;
  4) _cfg() 里 collect_target_per_account == 200(int),
     且【不含】check_per_segment / segs_per_region;
  5) _cfg()["min_athletes"] == 5000、collect_regions == ["New York"]
     —— 注意: 界面目录下【没有】config.json, 值只能来自 配置/config.json,
     所以这一条同时验证了「配置查找顺序」修好了;
  6) 8 个按钮的文本与绑定方法一个没变;
  7) 两份界面文件的 _cfg() 采集相关键集合完全一致。

运行:  python _自测_界面参数.py
"""
import importlib.util
import ast
import json
import re
import sys
import types
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
CFG_P = HERE / "配置" / "config.json"
GUIS = [HERE / "界面" / "ADS自动化.py", HERE / "界面" / "比特派自动化.py"]

# 采集相关键(父代理口径): 界面 _cfg() 里必须出现/必须不出现的键
MUST_HAVE = ["collect_regions", "min_athletes", "collect_target_per_account"]
MUST_NOT_HAVE = ["check_per_segment", "segs_per_region"]

# 上一轮逐项验收过的按钮: (按钮文本, 绑定的方法名)
BTNS = [("1.连接并加载", "load_items"),
        ("2.扫描状态", "scan_all"),
        ("⟳ 刷新结果", "refresh_results"),
        ("3.预览分配", "preview"),
        ("▶ 开始任务", "start_task"),
        ("◎ 只采集", "start_collect"),
        ("■ 停止", "stop_task"),
        ("✕ 关闭全部浏览器", "close_browsers")]

OK = []
BAD = []

# 每个界面对应的引擎文件, 以及 close_browsers 该调 / 不该调的引擎函数名
ENGINE_OF = {"ADS自动化": "strava_ads.py", "比特派自动化": "strava_bit.py"}
CLOSE_OF = {"ADS自动化": "ads_close_all", "比特派自动化": "bit_close_all"}
WRONG_CLOSE = {"ADS自动化": "bit_close_all", "比特派自动化": "ads_close_all"}


def engine_path(engine_file):
    """按界面 __main__ 里那套顺序找引擎脚本"""
    for c in (HERE / "界面" / engine_file, HERE / "界面" / "主脚本" / engine_file,
              HERE / "主脚本" / engine_file, HERE / engine_file):
        if c.exists():
            return c
    hit = [h for h in sorted(HERE.rglob(engine_file)) if "__pycache__" not in str(h)]
    return hit[0] if hit else None


def gui_sa_names(src):
    """界面源码里所有 SA.xxx 引用"""
    return sorted(set(re.findall(r"SA\.([A-Za-z_]\w*)", src)))


def engine_toplevel_names(src):
    """引擎模块顶层真实存在的名字(函数/类/全局变量) —— 不导入引擎, 只解析源码"""
    names = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def fn_referenced_names(fn):
    """函数(含内部嵌套函数)运行时真正会去取的属性名 —— 查字节码, 不是查注释"""
    names = set(fn.__code__.co_names)
    for c in fn.__code__.co_consts:
        if isinstance(c, types.CodeType):
            names |= set(c.co_names)
    return names


def ck(cond, msg):
    (OK if cond else BAD).append(msg)
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    return bool(cond)


def walk(w):
    """递归收集所有子控件"""
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(walk(c))
    return out


def load_mod(fp, name):
    spec = importlib.util.spec_from_file_location(name, fp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)          # __main__ 段不会跑, 引擎不会被导入
    return mod


def cfg_keys_from_source(src):
    """从源码里抠出 _cfg() 的 return {...} 块, 解析出顶层键名"""
    m = re.search(r"def _cfg\(self\):(.*?)\n    def ", src, re.S)
    if not m:
        return None
    block = m.group(1)
    start = block.index("return {")
    depth, end = 0, None
    for i, ch in enumerate(block[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    body = block[start + len("return "):end]
    return set(re.findall(r'^\s{12}"([a-z_]+)":', body, re.M))


def main():
    print("=" * 72)
    print("自测: 新采集参数(每号目标人数 / min_athletes 5000 / 纽约必扫)")
    print("=" * 72)

    # ---------- 0. 前置: 只有 配置/config.json, 界面 下没有 config.json ----------
    print("\n[0] 前置条件")
    ck(CFG_P.exists(), f"存在 {CFG_P.relative_to(HERE)}")
    for g in GUIS:
        ck(not (g.parent / "config.json").exists(),
           f"{g.parent.name}\\config.json 不存在(界面只能去 配置\\ 找) —— 这正是原来的坑")
    rc = json.loads(CFG_P.read_text(encoding="utf-8"))
    ck(rc.get("min_athletes") == 5000, f"配置 min_athletes={rc.get('min_athletes')}")
    ck(rc.get("collect_target_per_account") == 200,
       f"配置 collect_target_per_account={rc.get('collect_target_per_account')}")
    ck(rc.get("collect_regions") == ["New York"], f"配置 collect_regions={rc.get('collect_regions')}")
    ck("check_per_segment" not in rc, "配置里已删掉 check_per_segment")
    ck(rc.get("segs_per_region") == 0, f"配置 segs_per_region={rc.get('segs_per_region')}")

    # ---------- 1. 配置查找顺序必须和引擎一致 ----------
    print("\n[1] 配置查找候选顺序 vs 引擎")
    eng = HERE / "主脚本" / "strava_ads.py"
    eng_cands = re.findall(r'cands\s*=\s*\[(.*?)\]', eng.read_text(encoding="utf-8"), re.S)
    eng_norm = re.sub(r"\s+", "", eng_cands[0]).replace('"', "") if eng_cands else ""
    print(f"  引擎候选: {eng_norm}")
    for g in GUIS:
        src = g.read_text(encoding="utf-8")
        m = re.search(r"for _c in \((.*?)\):", src, re.S)
        gui_norm = re.sub(r"\s+", "", m.group(1)).replace('"', "") if m else ""
        # 引擎: ROOT/config.json,ROOT/配置/config.json,ROOT.parent/配置/config.json,ROOT.parent/config.json
        ck(gui_norm == eng_norm, f"{g.name} 候选顺序: {gui_norm}")

    keysets = {}
    for g in GUIS:
        name = g.stem
        print("\n" + "=" * 72)
        print(f"[{name}] {g.name}")
        print("=" * 72)
        src = g.read_text(encoding="utf-8")

        # ---------- 2. 静态: 旧控件没了, 新控件在 ----------
        print("\n[2] 源码检查")
        ck("var_segs" not in src and "var_check" not in src,
           "var_segs / var_check 已彻底移除")
        ck('"check_per_segment"' not in src, '源码里不再有 "check_per_segment" 这个键')
        ck('"segs_per_region"' not in src, '源码里不再有 "segs_per_region" 这个键')
        ck('text="每州路段"' not in src and 'text="每段查人"' not in src,
           "「每州路段」「每段查人」标签已删")
        ck('text="每号目标人数"' in src, "新标签「每号目标人数」在")
        ck("ttk.Spinbox(f2, from_=1, to=2000" in src, "ttk.Spinbox(from_=1, to=2000) 在")
        ck('_rc.get("min_athletes") or 5000' in src, "min_athletes 默认值已是 5000")

        kset = cfg_keys_from_source(src)
        keysets[name] = kset
        print(f"  _cfg() 键集合: {sorted(kset)}")
        for k in MUST_HAVE:
            ck(k in kset, f"_cfg() 含 {k}")
        for k in MUST_NOT_HAVE:
            ck(k not in kset, f"_cfg() 不含 {k}")

        # ---------- 3. 真起窗口 ----------
        print("\n[3] 真起 Tk 窗口")
        import tkinter as tk
        mod = load_mod(g, f"_selftest_{name}")
        app = mod.App()
        app.update()                       # 真正布局一遍, TclError 会在这里炸
        ck(True, f"{name} 窗口建起来了: {app.title()} {app.winfo_width()}x{app.winfo_height()}")

        ws = walk(app)
        labels = [str(w.cget("text")) for w in ws
                  if w.winfo_class() in ("TLabel", "Label") and "text" in w.keys()]
        spins = [w for w in ws if w.winfo_class() == "TSpinbox"]
        entries = [w for w in ws if w.winfo_class() == "TEntry"]

        ck("每号目标人数" in labels, "界面上有「每号目标人数」标签")
        ck("每州路段" not in labels and "每段查人" not in labels,
           "界面上已无「每州路段」「每段查人」标签")
        ck(len(spins) == 1, f"全界面恰好 1 个 Spinbox(实际 {len(spins)})")
        if spins:
            sp = spins[0]
            ck(float(sp.cget("from")) == 1.0, f"Spinbox from={sp.cget('from')}")
            ck(float(sp.cget("to")) == 2000.0, f"Spinbox to={sp.cget('to')}")
            ck(str(sp.cget("textvariable")) == str(app.var_target),
               "Spinbox 绑的正是 var_target")
        # 其余输入框数量: 编号from/to(2) + 位置 + 头像目录 + 轨迹目录 + 每批+上限(2) + 并发 = 8
        ck(len(entries) == 8, f"其余 Entry 仍是 8 个(实际 {len(entries)})")
        ck(hasattr(app, "var_target"), "app.var_target 存在")
        ck(app.var_target.get() == "200", f"默认值 = {app.var_target.get()} (要 200)")

        # ---------- 4. 采集/身份参数 ----------
        print("\n[4] 关键变量")
        ck(app._min_ath == 5000, f"app._min_ath = {app._min_ath} (要 5000, 证明读到了 配置\\config.json)")
        ck(app._regions == ["New York"], f"app._regions = {app._regions}")
        ck(app._max_fol == 200, f"app._max_fol = {app._max_fol}")
        cfg_label = [t for t in labels if "州" in t and "男性" in t]
        ck(bool(cfg_label) and "每段≥5000人" in cfg_label[0],
           f"说明文字已更新: {cfg_label[0] if cfg_label else '(没找到)'}")

        # ---------- 5. 按钮绑定没被动过 ----------
        print("\n[5] 按钮绑定(上一轮验收过的, 一个都不许变)")
        # 真窗口里的按钮(不去重: 两个「浏览」文本一样, 去重会漏数)
        btns = [(str(w.cget("text")), str(w.cget("command")))
                for w in ws if w.winfo_class() == "TButton"]
        texts = sorted(t for t, _ in btns)
        for text, meth in BTNS:
            cmd = dict(btns).get(text)
            ck(cmd is not None and cmd.endswith(meth), f"「{text}」 -> {meth}  (实际 {cmd})")
        # 和改之前的备份逐字对比: 按钮文本一个不多一个不少
        bak = Path(str(g) + ".bak_target").read_text(encoding="utf-8")
        bak_texts = sorted(re.findall(r'ttk\.Button\([^)]*text="([^"]+)"', bak))
        ck(texts == bak_texts, f"按钮文本集合与备份完全一致({len(texts)} 个): {texts}")
        ck(str(app.btn_stop.cget("state")) == "disabled", "■ 停止 初始仍是 disabled")

        # ---------- 5b. 所有 SA.xxx 调用在对应引擎里必须真实存在 ----------
        print("\n[5b] SA.* 调用 vs 引擎(比特派界面必须看 strava_bit.py)")
        eng_p = engine_path(ENGINE_OF[name])
        ck(eng_p is not None, f"找到引擎 {ENGINE_OF[name]}: {eng_p}")
        eng_src = eng_p.read_text(encoding="utf-8")
        eng_names = engine_toplevel_names(eng_src)
        used = gui_sa_names(src)
        print(f"  界面用到: {used}")
        for nm in used:
            ck(nm in eng_names, f"引擎里有 {nm}")

        # close_browsers: 源码 + 运行时字节码双重断言(踩过的坑: 比特派界面调了 ads_close_all)
        right, wrong = CLOSE_OF[name], WRONG_CLOSE[name]
        ck(f"SA.{right}()" in src, f"源码里 close_browsers 调的是 SA.{right}()")
        ck(f"SA.{wrong}" not in src, f"源码里已无错误的 SA.{wrong}")
        ck(right in eng_names, f"引擎顶层真的有 def {right}")
        ck(wrong not in eng_names, f"引擎里确实没有 {wrong}(所以以前必失败)")
        _cb = fn_referenced_names(mod.App.close_browsers)
        ck(right in _cb, f"运行时 close_browsers 字节码引用 {right}: {sorted(_cb)}")
        ck(wrong not in _cb, f"运行时不再引用 {wrong}")
        _ds = fn_referenced_names(mod.App.destroy)
        ck(right in _ds, f"destroy() 里关浏览器的调用也是 {right}")

        # ---------- 6. _cfg() ----------
        print("\n[6] _cfg() 真实返回值")
        cfg = app._cfg()
        print("  " + json.dumps(cfg, ensure_ascii=False))
        ck(cfg.get("collect_target_per_account") == 200
           and isinstance(cfg.get("collect_target_per_account"), int),
           f"collect_target_per_account = {cfg.get('collect_target_per_account')!r} (int 200)")
        ck("check_per_segment" not in cfg, "不含 check_per_segment")
        ck("segs_per_region" not in cfg, "不含 segs_per_region")
        ck(cfg.get("min_athletes") == 5000, f"min_athletes = {cfg.get('min_athletes')}")
        ck(cfg.get("collect_regions") == ["New York"], f"collect_regions = {cfg.get('collect_regions')}")
        ck(cfg.get("max_followers") == 200, f"max_followers = {cfg.get('max_followers')}")
        for k in ("location", "avatar_dir", "gpx_dir", "per_batch", "daily_cap",
                  "jobs", "background", "auto_close", "task_mode"):
            ck(k in cfg, f"其余键还在: {k}")

        # 输入框改动要真的生效 / 坏值要兜底
        app.var_target.set("350")
        ck(app._cfg()["collect_target_per_account"] == 350, "改成 350 -> _cfg() 就是 350")
        app.var_target.set("abc")
        ck(app._cfg()["collect_target_per_account"] == 200, "乱填 abc -> 兜底 200")
        app.var_target.set("0")
        ck(app._cfg()["collect_target_per_account"] == 200, "填 0 -> 兜底 200")
        app.var_target.set("200")

        # ---------- 7. 收尾: 不触发 destroy() 的副作用(不写结果文件/不关浏览器) ----------
        print("\n[7] 关窗口")
        app._alive = False
        for aid in ("_after_ui", "_after_log"):
            try:
                i = getattr(app, aid, None)
                if i:
                    app.after_cancel(i)
                    setattr(app, aid, None)
            except Exception:
                pass
        tk.Tk.destroy(app)                 # 直接调父类, 绕开 _save_results/SA
        ck(True, f"{name} 窗口已关闭(未写结果文件、未调用浏览器接口)")

    # ---------- 8. 两个文件 _cfg() 键集合必须完全一致 ----------
    print("\n" + "=" * 72)
    print("[8] 两份界面 _cfg() 键集合比对")
    a, b = keysets["ADS自动化"], keysets["比特派自动化"]
    print(f"  ADS自动化  : {sorted(a)}")
    print(f"  比特派自动化: {sorted(b)}")
    ck(a == b, "两份 _cfg() 键集合完全一致" if a == b else f"不一致! 差异: {a ^ b}")
    ck(len(a) == 13, f"键数量 {len(a)}")

    print("\n" + "=" * 72)
    print(f"结果: OK={len(OK)}  FAIL={len(BAD)}")
    for m in BAD:
        print("  FAIL: " + m)
    print("=" * 72)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
