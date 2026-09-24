# -*- coding: utf-8 -*-
"""验证 A: 误传【任务级 ctx】给 append_task_url 不再抛 KeyError。

红: 改之前 -> KeyError: 'urls'
绿: 改之后 -> 正常返回 True, 且文件真的落盘

★★ 隔离要求(踩过坑): 引擎的 ROOT = Path(__file__).resolve().parent,
   所以必须【把引擎文件本身拷进临时目录】再加载, 否则 ROOT 会指向
   真实项目的 主脚本/, 成果文件就会写进【真实 数据/ 目录】。
   2026-09-20 就因为没做这一步, 往 数据\链接-20260920.txt 里写进了两条假链接。
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else
           r"C:\Users\1\Desktop\Strava自动化_备份_20260917\主脚本\strava_ads.py")
PROJ = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")

D = Path(tempfile.mkdtemp(prefix="_verA_"))
shutil.copy2(SRC, D / SRC.name)                       # ★ 关键: 引擎进沙箱
(D / "config.json").write_text("{}", encoding="utf-8")
for dep in ("geo_cities.py", "claim_client.py"):      # 引擎的依赖
    if (PROJ / "主脚本" / dep).exists():
        shutil.copy2(PROJ / "主脚本" / dep, D / dep)
    elif (PROJ / dep).exists():
        shutil.copy2(PROJ / dep, D / dep)

os.chdir(D)
sys.path.insert(0, str(D))
spec = importlib.util.spec_from_file_location("eng", D / SRC.name)
M = importlib.util.module_from_spec(spec)
sys.modules["eng"] = M
spec.loader.exec_module(M)

assert str(M.ROOT) == str(D), f"沙箱失败! ROOT={M.ROOT} 应为 {D}"
assert str(M.DATA_DIR) == str(D), f"沙箱失败! DATA_DIR={M.DATA_DIR} 应为 {D}"
print(f"[隔离] ROOT={M.ROOT}  (在临时目录内, 不会碰真实数据)")

task = M.new_task_ctx(target="t", mode="cli", worker="w")
u = "https://www.strava.com/athletes/123456789"
try:
    ok = M.append_task_url(task, u)          # ★ 故意传任务级 ctx
except Exception as e:
    print(f"[红] 仍然抛异常: {type(e).__name__}: {e}")
    sys.exit(1)

p = task.get("path")
print(f"[绿] append_task_url(任务级ctx) 返回 = {ok}")
print(f"     落盘文件 = {p}")
print(f"     urls 键 = {task.get('urls')}")
assert ok is True, "应当写入成功"
assert p and Path(p).exists(), "文件应当存在"
assert str(Path(p).parent) == str(D), "文件必须落在沙箱里"
assert u in Path(p).read_text(encoding="utf-8"), "内容应当包含该链接"

task2 = M.new_task_ctx(target="t2", mode="cli", worker="w")
sub = M.new_account_ctx(task2, "1")
u2 = "https://www.strava.com/athletes/987654321"
ok2 = M.append_task_url(sub, u2)
print(f"[绿] append_task_url(号级ctx)   返回 = {ok2}  urls={sub.get('urls')}")
assert ok2 is True and u2 in sub["urls"]
print("★★★ A 修复验证通过 ★★★")
shutil.rmtree(D, ignore_errors=True)
