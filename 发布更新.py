# -*- coding: utf-8 -*-
"""把当前分发包发布到服务器 —— 管理员专用

用法:
    python 发布更新.py            打包并上传
    python 发布更新.py --dry-run  只打包和体检, 不上传

★ 上传前会做和 _重做启动器.py 一样的「发货前体检」:
  只要包里出现任何真实邮箱, 直接拒绝上传。

★ 包里【不含】账号文件、扫描结果、采集成果 —— 那些是同事自己的,
  永远不从服务器覆盖(config.json 例外: 只把新增的键补给他们)。
"""
import io
import json
import re
import sys
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent
PKG = WS / "_分发给同事"

# 不进更新包的（同事本地的数据 / 运行时产物）
# ★ 这里是【子串匹配】(见下面 any(x in f.name ...)), 所以"按任务命名的成果文件"
#   必须单独列一条 collected_users_: 新名字 collected_users_20260919_003012_3.txt
#   并不含子串 "collected_users.txt" —— 只列旧名挡不住它, 同事的成果会被打进
#   包上传 VPS 再分发给所有人(成果泄露)。
#   反过来说 "collected_users_" 不是 "collected_users.txt" 的子串, 加它不误伤旧名。
EXCLUDE = (
    "bit_accounts.json", "ads_accounts.json",
    "bit_results.json", "ads_results.json",
    "collected_users.txt", "collected_users_", "collected_seen.json",
    # ★★ 2026-09-19 成果文件改名叫「链接-日期」之后必须加上这条 ★★
    #   漏了它 -> 同事当天采到的链接会被打进更新包上传 VPS,
    #   再分发给所有人 —— 成果泄露, 而且是在管理员自己机器上发起的。
    "链接-",
    "task_state.json", "scan_results.json",
    "python_path.txt", "__pycache__", "logs", "_python",
    "._pkg_version", ".log",
)
ALLOW_MAIL = ("example.com", "test.com", "localhost")

MAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+")


def log(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(m.encode("gbk", "replace").decode("gbk") + "\n")


def find_cfg():
    for c in (WS / "配置" / "config.json", WS / "config.json"):
        if c.is_file():
            return c
    return None


def main():
    dry = "--dry-run" in sys.argv

    cfg_path = find_cfg()
    if not cfg_path:
        log("找不到 配置/config.json")
        return 1
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    server = str(cfg.get("claim_server") or "").rstrip("/")
    key = str(cfg.get("claim_key") or "")
    if not server:
        log("config.json 里没有 claim_server")
        return 1

    # ★★ 2026-09-20 支持子目录(sv_ttk/ 这类) ★★
    #   · 用 rglob 收【所有层级】的文件, 而不是 iterdir 只看顶层
    #   · 排除改成按【相对路径】匹配 —— 按基名匹配会漏掉
    #     sv_ttk/__pycache__/x.pyc 这种(它的基名里没有 "__pycache__")
    #   · files 存 (绝对路径, zip 条目名) —— 条目名就是相对路径, 带 /
    files = []
    for f in sorted(PKG.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(PKG).as_posix()          # 统一用 / (zip 规范)
        if any(x in rel for x in EXCLUDE):
            continue
        files.append((f, rel))

    log("=== 准备发布 ===")
    log("  服务器: %s" % server)
    log("  文件  : %d 个(含子目录)" % len(files))

    # ---------------- 体检（和发货前一样，不通过就不传）----------------
    # ★ 要挡两类东西: 邮箱, 和【任何密钥值】。
    #   以前只查邮箱、且只清 config.json 里的 adspower_key ——
    #   而 key 恰恰还被硬编码在 strava_ads.py 源码里, 于是每次发版都会
    #   把作者机器的 AdsPower key 传到 VPS, 再分发到所有同事机器上。
    secrets = []
    try:
        _my = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        _my = {}
    # ★ 只拦【每台机器各不相同的私钥】。
    #   claim_key 是 20 台共享的去重密钥, 本来就是靠 config.json 下发的,
    #   拦它等于把功能拦掉(零配置的前提就是它随包发)。
    for _k in ("adspower_key", "bitbrowser_key"):
        _v = str(_my.get(_k) or "").strip()
        if len(_v) >= 12:
            secrets.append((_k, _v))
    if not secrets:
        log("  [提示] config 里没有 adspower_key/bitbrowser_key, 跳过私钥扫描")

    problems = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f, rel in files:
            data = f.read_bytes()
            text = data.decode("utf-8", "ignore")
            # ★ 许可证文件放行邮箱体检:
            #   MIT/Apache 这类许可【要求随分发保留版权声明】, 里面必然带作者邮箱。
            #   拦掉它 = 要么违反许可、要么发不出去。所以只对许可文件放行,
            #   其它文件照旧严查(那道闸门是防同事账号外泄的, 不能松)。
            _is_license = rel.lower().endswith(("license.txt", "license", "license.md"))
            for m in MAIL_RE.finditer(text):
                if _is_license:
                    break
                if not any(a in m.group(0).lower() for a in ALLOW_MAIL):
                    problems.append("%s 含邮箱 %s" % (rel, m.group(0)))
            for _k, _v in secrets:
                if _v in text:
                    problems.append("%s 里写死了 %s (%s...)"
                                    % (rel, _k, _v[:8]))
            if rel == "config.json":
                try:
                    c = json.loads(text)
                    for _k in ("adspower_key", "bitbrowser_key"):
                        c[_k] = ""              # 绝不把你的 key 发出去
                    data = (json.dumps(c, ensure_ascii=False, indent=2)
                            + "\n").encode("utf-8")
                except Exception as e:
                    problems.append("config.json 解析失败: %s" % e)
            # ★ 关键: 必须写【相对路径】, 不能写 f.name ——
            #   写 f.name 会让 zip 里全是扁平名, 子目录结构和 __init__.py 全丢,
            #   而且 sv_ttk/sv.tcl 会和别的 */sv.tcl 撞成同名条目互相覆盖。
            z.writestr(rel, data)

    if problems:
        log("")
        log("  [拒绝发布] 体检不通过:")
        for p in problems:
            log("      - " + p)
        return 1
    log("  体检  : 干净（无邮箱, 你的 adspower_key 已清空）")

    blob = buf.getvalue()
    log("  大小  : %.0f KB" % (len(blob) / 1024))
    log("")
    log("  内容:")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in sorted(z.namelist()):
            log("    %-24s %8d B" % (n, z.getinfo(n).file_size))

    if dry:
        out = WS / "_待发布.zip"
        out.write_bytes(blob)
        log("")
        log("  --dry-run: 已写到 %s , 没有上传" % out.name)
        return 0

    log("")
    log("=== 上传 ===")
    import requests
    try:
        r = requests.post(server + "/pkg/upload", data=blob,
                          headers={"X-API-Key": key,
                                   "Content-Type": "application/zip"},
                          timeout=180)
    except Exception as e:
        log("  上传失败: %s" % str(e)[:120])
        return 1

    if r.status_code != 200:
        log("  服务器返回 %d: %s" % (r.status_code, r.text[:200]))
        return 1

    j = r.json()
    log("  发布成功")
    log("  新版本号: %s" % j.get("version"))
    log("  文件数  : %s" % j.get("count"))
    log("")
    log("★ 同事下次双击 Start_*.bat 时会自动更新到这一版。")
    log("★ 想核对: python 发布更新.py --dry-run 可先本地体检。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
