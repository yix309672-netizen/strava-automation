# -*- coding: utf-8 -*-
"""端到端验证: 同事机器能不能正确收到子目录(sv_ttk/)。

复刻真实链路: 本地打包 -> 上传 VPS -> 同事的 update.py 下载并还原 -> 检查结果

要点(子代理报告的结论):
  · 必须【客户端先上、服务端后上】, 否则是静默损坏
  · 所以这里服务端和客户端都已经是新版, 这是"都改完"之后的验证
  · 还要测【向后兼容】: 老的扁平包能不能照常更新
"""
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
SRV = CFG["claim_server"].rstrip("/")
KEY = CFG["claim_key"]

PASS, FAIL = [], []


def ck(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-52s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


def get(path, timeout=180):
    r = urllib.request.Request(SRV + path, headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


def main():
    print("=" * 84)
    print("端到端: 同事机器收到含子目录的新包")
    print("=" * 84)

    # ---------- 1. 服务器清单里有没有子目录 ----------
    print()
    print("--- 1. 服务器 manifest ---")
    man = json.loads(get("/pkg/manifest"))
    files = man.get("files") or {}
    print("    版本 %s, %d 个文件" % (man["version"], len(files)))
    subs = [k for k in files if "/" in k]
    ck("manifest 里有子目录条目", len(subs) > 0, True)
    ck("含 sv_ttk/__init__.py", "sv_ttk/__init__.py" in files, True)
    ck("含嵌套的 sv_ttk/theme/light.tcl",
       "sv_ttk/theme/light.tcl" in files, True)
    print("    子目录条目 %d 个:" % len(subs))
    for k in sorted(subs):
        print("       %s" % k)

    # ---------- 2. zip 里的条目名要和清单一致 ----------
    print()
    print("--- 2. zip 内容 vs 清单(口径必须一致) ---")
    blob = get("/pkg/latest.zip")
    zf = zipfile.ZipFile(io.BytesIO(blob))
    znames = set(n for n in zf.namelist() if not n.endswith("/"))
    print("    zip 条目 %d 个, 清单 %d 个" % (len(znames), len(files)))
    ck("zip 条目数 == 清单条目数", len(znames) == len(files), True)
    only_zip = sorted(znames - set(files))
    only_man = sorted(set(files) - znames)
    ck("没有'只在 zip 里'的", only_zip, [])
    ck("没有'只在清单里'的", only_man, [])
    # 关键: 不能再有拍平的裸名
    flat = sorted(n for n in znames if "/" in n and n.split("/")[-1] in
                  ("__init__.py", "sv.tcl", "light.tcl", "dark.tcl"))
    ck("子目录文件没有被拍平到根目录", flat, [])

    # ---------- 3. 模拟同事机器还原 ----------
    print()
    print("--- 3. 模拟同事机器: 用真 update.py 还原 ---")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="colleague_sub_"))
    # 造一台"干净的同事机器": 只有 update.py 和 config.json
    shutil.copy2(ROOT / "update.py", tmp / "update.py")
    (tmp / "config.json").write_text(json.dumps({
        "claim_server": SRV, "claim_key": KEY,
        "adspower_key": "COLLEAGUE_KEY_KEEP",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "update.py"], cwd=str(tmp),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    out = (r.stdout or "") + (r.stderr or "")
    print("    update.py 退出码 %d" % r.returncode)
    for line in out.splitlines()[-14:]:
        print("       " + line[:100])

    # ---------- 4. 检查落地结果 ----------
    print()
    print("--- 4. 落地结果 ---")
    ck("update.py 跑成功", r.returncode, 0)
    for rel in ("sv_ttk/__init__.py", "sv_ttk/sv.tcl",
                "sv_ttk/theme/light.tcl", "sv_ttk/theme/dark.tcl",
                "sv_ttk/theme/spritesheet_light.png",
                "strava_ads.py", "启动.bat"):
        ck("落到了 %s" % rel, (tmp / rel).is_file(), True)

    # 根目录不能被撒进散文件
    stray = [n for n in ("__init__.py", "sv.tcl", "light.tcl", "dark.tcl")
             if (tmp / n).is_file()]
    ck("根目录没被撒进散落的主题文件", stray, [])

    # 内容要对得上(逐个 sha256 比对清单)
    import hashlib
    mism = []
    for rel, info in files.items():
        p = tmp / rel
        if not p.is_file():
            mism.append(rel + "(缺)")
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h != info.get("sha256"):
            mism.append(rel + "(内容不符)")
    ck("每个文件都和清单的 sha256 一致", mism, [])

    # sv_ttk 要能真的 import(这才是子目录发出去的意义)
    r2 = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); import sv_ttk; "
         "import tkinter as tk; r=tk.Tk(); r.withdraw(); "
         "sv_ttk.set_theme('light'); print('IMPORT_OK'); r.destroy()" % tmp],
        cwd=str(tmp), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120, env=env)
    ck("同事机器上 sv_ttk 能 import 并切主题",
       "IMPORT_OK" in (r2.stdout or ""), True)

    # 同事自己的东西没被动
    c2 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
    ck("同事的 adspower_key 没被动", c2.get("adspower_key"), "COLLEAGUE_KEY_KEEP")

    # 版本号写上了
    vf = tmp / "._pkg_version"
    ck("._pkg_version 已写入", vf.is_file() and
       vf.read_text(encoding="utf-8").strip() == man["version"], True)

    shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 5. 向后兼容: 老扁平包 ----------
    print()
    print("--- 5. 向后兼容(老的扁平包不含 / ) ---")
    sys.path.insert(0, str(ROOT))
    import importlib.util
    spec = importlib.util.spec_from_file_location("uu", ROOT / "update.py")
    u = importlib.util.module_from_spec(spec); sys.modules["uu"] = u
    spec.loader.exec_module(u)
    ck("老扁平名仍然合法", u.safe_rel("strava_ads.py"), True)
    ck("老扁平名(中文)合法", u.safe_rel("启动.bat"), True)

    print()
    print("=" * 84)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✓ 通过 %d 项: 子目录能正确发布、正确还原、内容一致、"
          "同事的东西没被动、老包仍兼容" % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
