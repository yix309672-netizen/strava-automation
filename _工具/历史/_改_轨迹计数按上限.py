# -*- coding: utf-8 -*-
"""修: pending_todo 显示的"轨迹N个"要把【每日上限】算进去。

用户 2026-09-24 问: "我设置的上线38.为什么显示上传轨迹60个呢"
    实际机制:
      · pending_todo 显示的是【还剩多少个文件没传】(整个目录, 60 个)
      · upload_gpx 提交前会 todo = todo[:remain], remain = 每日上限 - 今天已传
      => 真正只传 38 个, 但 todo 那行写 60 —— 显示与实际不符, 会让人误判。

改法(两个引擎):
  ① 新增 _today_upload_remain(): 今天还能传多少(上限 - 今天已传), 逻辑与
     upload_gpx 里那段完全一致, 抽出来共用, 免得两边算得不一样
  ② pending_todo 加 daily_cap 参数, 显示"今天会传几个", 并把目录里的总数
     用括号带上(信息不丢)
  ③ run_one 调用处把 daily_cap 传进去
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HELPER = '''

def _today_upload_remain(tag, daily_cap=None):
    """今天还能传多少个轨迹 = 每日上限 - 今天已传。拿不到就返回 None(不限制)。

    ★★ 2026-09-24 用户问"我设的上限38, 为什么显示轨迹60个" ★★
      upload_gpx 提交前有一句 `todo = todo[:remain]`, 那个 remain 就是这里算的。
      抽成一个函数, 让"显示的数量"和"真传的数量"用同一套算法 ——
      以前 pending_todo 只数文件总数, 于是显示 60 而实际传 38。
    """
    try:
        cap = int(daily_cap) if daily_cap else int(CFG.get("daily_cap") or 38)
    except Exception:
        cap = 38
    if cap <= 0:
        return None
    try:
        counter = _data_path(f"upload_counter_{str(tag).lstrip('_')}.txt")
        today = datetime.now().strftime("%Y-%m-%d")
        used = 0
        if counter.exists():
            d, n = counter.read_text().strip().split(",")
            if d == today:
                used = int(n)
        return max(0, cap - used)
    except Exception:
        return None

'''

A_OLD = '''    if gpx_files:
        done = set(st.get("uploaded", []))
        rest = [p for p in gpx_files if str(p) not in done]
        if rest:
            todo.append(f"轨迹{len(rest)}个")
'''
A_NEW = '''    if gpx_files:
        done = set(st.get("uploaded", []))
        rest = [p for p in gpx_files if str(p) not in done]
        if rest:
            # ★★ 显示"今天会传几个", 不是"目录里还剩几个" ★★
            #   用户设的每日上限 38, 这里原来写 60(目录总数), 对不上 ——
            #   因为真正能传几个由 upload_gpx 按每日上限截断。
            _n = len(rest)
            _cap = _today_upload_remain(win, daily_cap)
            if _cap is None or _cap >= _n:
                todo.append(f"轨迹{_n}个")
            else:
                todo.append(f"轨迹{_cap}个(还差{_n - _cap}个, 受每日上限限制)")
'''

B_OLD = "def pending_todo(win, name=None, location=None, avatar=None, gpx_files=None):\n"
B_NEW = ("def pending_todo(win, name=None, location=None, avatar=None, gpx_files=None,\n"
         "                 daily_cap=None):\n")

C_OLD = "        todo = pending_todo(state_key, name, location, avatar, files)\n"
C_NEW = ("        todo = pending_todo(state_key, name, location, avatar, files,\n"
         "                            daily_cap=daily_cap)\n")

ok = True
for name in ("strava_ads.py", "strava_bit.py"):
    p = ROOT / "主脚本" / name
    src = p.read_text(encoding="utf-8")
    print(f"=== {name}")
    bad = False
    for tag, o, n in (("① 加辅助函数", "def pending_todo(win", HELPER.lstrip("\n") + "\ndef pending_todo(win"),
                      ("② 计数改成算上限", A_OLD, A_NEW),
                      ("③ 签名加 daily_cap", B_OLD, B_NEW),
                      ("④ 调用处传参", C_OLD, C_NEW)):
        if tag.startswith("①"):
            c = src.count(o)
        else:
            c = src.count(o)
        if c != 1:
            print(f"   ★ {tag}: 命中 {c} 次(要 1 次) —— 放弃, 文件没动")
            bad = True
            break
        src = src.replace(o, n, 1)
        print(f"   OK {tag}")
    if bad:
        ok = False
        continue
    try:
        compile(src, str(p), "exec")
    except SyntaxError as e:
        print(f"   ★ 语法不过: {e} —— 放弃")
        ok = False
        continue
    bak = p.with_name(p.name + f".bak_before_轨迹计数_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(p, bak)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(src, encoding="utf-8")
    import os
    os.replace(tmp, p)
    print(f"   已写回; 备份 {bak.name}")

print()
print("完成" if ok else "★ 有步骤失败")
sys.exit(0 if ok else 1)
