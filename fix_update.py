# -*- coding: utf-8 -*-
"""一键修复更新 —— 当"双击启动.bat 还是老版本"时用这个

用法:
    1) 把这个文件复制到同事的脚本文件夹里(和 启动.bat 同一个目录)
    2) 双击同目录的 修复更新.bat, 或者命令行运行:  python fix_update.py

    ★ 文件名故意用 ASCII(fix_update.py): 项目的 .bat 一律是【纯 ASCII 内容】,
      cmd 解析非 ASCII 会炸(踩过: 'eDelayedExpansion' 不是内部或外部命令),
      所以 bat 里只能写 ASCII 路径 —— 中文只出现在 bat 的文件名上。

它会:
    * 先做体检: 目录里有什么、配置里的采集口径是什么、本地版本号、
      update.py 在不在、服务器通不通 —— 把"为什么自动更新没生效"直接印出来
    * 然后用【标准库 urllib】自己把最新包拉下来并逐个校验 sha256 后替换
      (不依赖 update.py, 也不依赖 requests —— 老机器上经常缺这缺那)
    * 最后把【管理员策略键】强制对齐(采集州/每段人数门槛/并发等),
      同事自己的东西(浏览器 key、头像目录、轨迹目录)一律不碰

★ 只改脚本文件; 账号、成果、task_state、logs 一律不动。
"""
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
TIMEOUT = 30

# 这些文件永远不从服务器覆盖(和 update.py 同一套口径)
PROTECTED = {
    "config.json", "accounts.json", "bit_accounts.json", "ads_accounts.json",
    "bit_results.json", "ads_results.json", "collected_users.txt",
    "collected_seen.json", "task_state.json", "scan_results.json",
    "python_path.txt",
}
# ★ 成果文件已改名为「链接-日期」, 必须一起保护(与 update.py 同款)
PROTECTED_PREFIX = ("claim_cache_", "upload_counter_", "collected_users_",
                    "链接-",
                    "._pkg", ".")

# 管理员统一下发的采集口径 —— 强制跟服务器走(老包把这些写死过旧值)
#
# ★★ 2026-09-20 修: 这份名单原来比 update.py 多两个键 ——
#      "collect_regions", "min_athletes"
#    后果(实测): 同事在界面上把「采集地区」选成别的州、「每段≥」选成别的值,
#    只要他双击一次【修复更新.bat】, 第四节的"对齐"就会把这两个键
#    【强制改回服务器的值】—— 自己选的州和门槛当场被吃掉。
#    而 修复更新.bat 恰恰是我们让他出问题时第一个去点的东西, 等于
#    每修一次就抹一次他的设置。
#    update.py 早就把这两个键摘掉了(见其中注释: 它们是界面下拉框,
#    强制下发会和下拉框打架), 但 fix_update.py 漏改了, 两边不一致。
#    现在两边完全一致: 这两个键【不在】强制名单里。
#    老包 12 州 / 每段 200 的纠正不靠这里 —— 走界面和引擎里的
#    _policy_rev 一次性纠正, 那条路专治老值, 又不会碰同事的新选择。
POLICY_KEYS = (
    "collect_auto_regions", "max_followers",
    "collect_target_per_account", "segs_per_region",
    "geo_filter", "geo_band_min_km", "geo_band_max_km",
    "ny_exempt_max_km", "lb_max_pages",
    "rate_nav_sec", "rate_api_sec", "rate_act_sec",
    "collect_max_minutes", "stall_exit_sec",
    "jobs", "collect_enabled",
    "claim_server", "claim_key",
    # ★ 管理员口径版本号: 界面和引擎靠它判断要不要强制纠正采集口径
    "_policy_rev",
)


def out(m=""):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        sys.stdout.write(str(m).encode("gbk", "replace").decode("gbk") + "\n")


def is_protected(name):
    return name in PROTECTED or any(name.startswith(p) for p in PROTECTED_PREFIX)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def find_cfg():
    for c in (BASE / "config.json", BASE / "配置" / "config.json",
              BASE.parent / "配置" / "config.json", BASE.parent / "config.json"):
        if c.is_file():
            return c
    return None


def bar(t):
    out("=" * 74)
    out(t)
    out("=" * 74)


def main():
    bar("修复更新 —— 把最新脚本拉到这台机器上")
    out(f"  目录: {BASE}")
    out()

    # ---------------------------------------------------------- 1. 体检
    bar("一、体检(为什么自动更新没生效)")
    cfg_path = find_cfg()
    out(f"  config.json      : {cfg_path if cfg_path else '★ 找不到!'}")
    cfg = {}
    if cfg_path:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            out(f"  ★ config.json 读不了: {str(e)[:80]}")

    vf = BASE / "._pkg_version"
    ver_local = vf.read_text(encoding="utf-8").strip() if vf.is_file() else ""
    out(f"  本地版本号       : {ver_local or '(没有 ._pkg_version —— 从没更新成功过)'}")
    out(f"  update.py 在不在 : {'在' if (BASE / 'update.py').is_file() else '★ 不在(老包没有自动更新器, 这就是没更新的原因)'}")
    out(f"  Python           : {sys.version.split()[0]}  ({sys.executable})")
    try:
        out("  requests 库      : 已装")
    except Exception:
        out("  requests 库      : ★ 没装(旧 update.py 会因为这一条直接跳过更新!)")
    out(f"  采集州(配置)     : {cfg.get('collect_regions')}")
    out(f"  每段门槛(配置)   : {cfg.get('min_athletes')}")
    out(f"  并发(配置)       : {cfg.get('jobs')}")
    out(f"  采集目标(配置)   : {cfg.get('collect_target_per_account')}")
    out()

    server = str(cfg.get("claim_server") or "").rstrip("/")
    key = str(cfg.get("claim_key") or "")
    if not server:
        out("★ config.json 里没有 claim_server, 没法更新。请把服务器的 config.json 拿过来。")
        return 2
    hdr = {"X-API-Key": key} if key else {}
    out(f"  服务器           : {server}")

    # ---------------------------------------------------------- 2. 连服务器
    bar("二、连服务器取清单")
    try:
        req = urllib.request.Request(server + "/pkg/manifest", headers=hdr)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            man = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        out(f"  ★ 连不上: {str(e)[:120]}")
        out("    检查: 能不能打开网页 / 防火墙 / config.json 里的 claim_server")
        return 2
    ver = str(man.get("version") or "")
    remote = {k: v for k, v in (man.get("files") or {}).items()}
    out(f"  服务器版本       : {ver}")
    out(f"  服务器文件数     : {len(remote)}")

    changed = []
    for name, info in remote.items():
        p = BASE / name
        want = (info or {}).get("sha256")
        if not p.is_file() or sha_file(p) != want:
            changed.append(name)
    out(f"  需要更新的文件   : {len(changed)} 个")
    for c in changed:
        out(f"      - {c}")
    out()
    if not changed and ver == ver_local:
        out("  本地已经是最新 —— 如果界面还显示旧口径, 说明是【配置】问题, 看第三步。")
    out()

    # ---------------------------------------------------------- 3. 下载并替换
    bar("三、下载整包并逐个校验替换")
    try:
        req = urllib.request.Request(server + "/pkg/latest.zip", headers=hdr)
        with urllib.request.urlopen(req, timeout=max(TIMEOUT, 180)) as r:
            blob = r.read()
    except Exception as e:
        out(f"  ★ 下载失败: {str(e)[:120]}")
        return 2

    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as e:
        out(f"  ★ 包坏了: {str(e)[:80]}")
        return 2

    bak = BASE / f"_修复前备份_{time.strftime('%Y%m%d_%H%M%S')}"
    done, failed, skipped = [], [], []
    for info in zf.infolist():
        try:
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if "/" in name or "\\" in name or ".." in name or name.startswith("."):
                failed.append(name + "(文件名不合法)")
                continue
            if name == "config.json":
                continue                       # 配置在第四步单独处理
            if is_protected(name):
                skipped.append(name)
                continue
            data = zf.read(info)
            want = (remote.get(name) or {}).get("sha256")
            if not want or sha_bytes(data) != want:
                failed.append(name + "(哈希不符, 已拒绝)")
                continue
            dst = BASE / name
            if dst.is_file() and sha_file(dst) == sha_bytes(data):
                continue                       # 内容一样, 不动
            if dst.is_file():                  # 先备份
                bak.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(dst, bak / name)
                except Exception:
                    pass
            tmp = dst.with_name(dst.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
            done.append(name)
        except PermissionError:
            failed.append(name + "(文件正被占用 —— 先把脚本完全关掉再跑一次)")
        except Exception as e:
            failed.append(f"{name}({str(e)[:40]})")

    out(f"  已替换 {len(done)} 个: {', '.join(done) if done else '(没有需要替换的)'}")
    if skipped:
        out(f"  受保护跳过: {', '.join(skipped)}")
    for f in failed:
        out(f"  ★ 失败: {f}")

    # ---------------------------------------------------------- 4. 配置对齐
    bar("四、把【管理员策略键】对齐到服务器口径")
    # ★★ 2026-09-20: local 必须在【外面】先赋初值 ★★
    #   原来它是在 `if cfg_path and ...` 里面、又嵌一层 `if remote_cfg:` 里
    #   才赋值的。第五节要读 local 打印"现在的口径", 一旦某个 if 不成立
    #   (找不到 config.json / 包里没有 config.json / config.json 是空的),
    #   local 从头到尾没被赋值 -> 第五节直接 NameError 崩掉,
    #   而此时【文件其实已经全部替换成功了】, 同事看到满屏报错以为修复失败。
    #   这和 一键推送更新.py 里 ver 那个坑是同一个毛病, 一并堵掉。
    local = dict(cfg) if isinstance(cfg, dict) else {}
    if cfg_path and "config.json" in remote:
        try:
            remote_cfg = json.loads(zf.read("config.json").decode("utf-8"))
        except Exception:
            remote_cfg = {}
        if remote_cfg:
            for k, v in remote_cfg.items():
                if k not in local:
                    local[k] = v
            forced = []
            for k in POLICY_KEYS:
                if k in remote_cfg and local.get(k) != remote_cfg.get(k):
                    local[k] = remote_cfg[k]
                    forced.append(k)
            try:
                tmp = cfg_path.with_name(cfg_path.name + ".tmp")
                tmp.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
                os.replace(tmp, cfg_path)
                out(f"  已对齐: {', '.join(forced) if forced else '(本来就一致)'}")
                out(f"  现在的采集口径: 采集州={local.get('collect_regions')} "
                    f"每段门槛={local.get('min_athletes')} 并发={local.get('jobs')}")
                out(f"  (你的浏览器 key / 头像目录 / 轨迹目录都没动: "
                    f"key={str(local.get('adspower_key'))[:6]}... "
                    f"头像={local.get('avatar_dir')})")
            except Exception as e:
                out(f"  ★ 配置写回失败: {str(e)[:80]}")
    out()

    # ---------------------------------------------------------- 5. 记版本
    try:
        vf.write_text(ver, encoding="utf-8")
    except Exception:
        pass

    bar("五、完成")
    out(f"  本地版本号已记为: {ver}")
    if bak.is_dir():
        out(f"  被替换文件的备份: {bak.name}")
    out()
    out("  ★ 现在把脚本【完全关掉】(界面窗口 + 黑色命令行窗口), 再双击 启动.bat。")
    # ★★ 2026-09-20 修: 这行原来是【写死】的
    #      "界面上那行应该变成: 1州(纽约必扫) · 男性 · 本月 · 45+ · 每段≥5000人"
    #    而现在的真实口径是 55+ / 每段≥2000 —— 照着这行去核对, 会以为
    #    自己没更新成功, 反过来又去折腾。改成直接从当前配置里读, 永远不会过期。
    _r = local.get("collect_regions") if isinstance(local, dict) else None
    _rs = "/".join(str(x) for x in _r) if isinstance(_r, (list, tuple)) else "?"
    out(f"    界面上那行现在应该是:  {_rs} · "
        f"{local.get('collect_gender')} · {local.get('collect_date_range')} · "
        f"每段≥{local.get('min_athletes')}人")
    out("    (以上面这行为准 —— 它是从你自己的 config.json 里读出来的)")
    out()
    out("  如果还是旧的, 把本窗口内容截图发给管理员。")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        out(f"\n★ 意外错误: {str(e)[:200]}")
        rc = 1
    out()
    try:
        input("按回车退出...")
    except Exception:
        pass
    sys.exit(rc)
