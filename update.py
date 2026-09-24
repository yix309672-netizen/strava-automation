# -*- coding: utf-8 -*-
"""脚本自动更新 —— 同事双击 Start_*.bat 时自动跑一次

用法:
    python update.py            手动更新, 显示细节
    python update.py --auto     静默模式(供 Start_*.bat / 启动.bat 调用)
    python update.py --check    只看有没有新版, 不下载

★ 三条安全原则:

  1. 只换脚本和说明。账号文件、采集数据、task_state、logs、
     _python 一律不碰; config.json 特殊处理 —— 只把【新增加的键】
     补进去, 绝不覆盖同事已经填好的值。

  2. 每个文件先写成 .tmp, 校验 sha256 通过才 os.replace 原子替换。
     下载中断也不会留下半个文件。

  3. 服务器连不上就跳过并正常退出(退出码 0)。
     更新失败绝不能挡着人用 —— 这和"连不上就不采集"是两回事:
     去重错了会白干, 少更新一次只是旧版本继续跑。
"""
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
VER_FILE = BASE / "._pkg_version"       # 记已应用的版本号
TIMEOUT = 30

# 这些文件永远不从服务器覆盖（精确名）
PROTECTED = {
    "config.json",                      # 特殊: 只补缺失的键
    "accounts.json",                    # ★ 账号文件, 以前漏了
    "bit_accounts.json", "ads_accounts.json",
    "bit_results.json", "ads_results.json",
    "collected_users.txt", "collected_seen.json",
    "task_state.json", "scan_results.json",
    "python_path.txt",
}
# 前缀保护: 这类文件每台机器各有一份, 绝不能被服务器上的同名文件顶掉
# ★ collected_users_ 必须在这里: 成果文件已按任务改名成
#   collected_users_<时间戳>[_号].txt, 而 PROTECTED 是【精确名】集合,
#   改成按任务命名后那些文件就掉出保护口径了(服务器上万一出现同名文件
#   会把同事机器上的成果顶掉 —— 成果只能多不能少)。
#   它不会误伤历史总表: "collected_users_" 不是 "collected_users.txt" 的子串,
#   总表由下面 PROTECTED 里的精确名继续保护。
# ★★ 2026-09-19 成果文件改名为「链接-日期」之后必须加上 "链接-" ★★
#   漏了它 -> 更新器会把 链接-20260920.txt 当成"服务器上的普通文件",
#   直接用旧包里的同名文件覆盖/删除 -> 同事当天采到的链接【丢数据】。
PROTECTED_PREFIX = ("claim_cache_", "upload_counter_", "collected_users_",
                    "链接-",
                    "._pkg", ".")

# ★★ 2026-09-19 【管理员策略键: 必须跟着服务器走, 不能被本地旧值钉住】★★
#   背景(管理员实测): 同事更新完代码, 界面上却仍写着
#       "12州(纽约必扫) · 男性 · 本月 · 45+ · 每段≥200人"
#   根因: 老发行包把这些值写进了同事本地的 config.json, 而 merge_config()
#   的策略是"只补缺失的键, 绝不改已有值" —— 于是旧值永远改不掉,
#   同事看起来和最新版完全不一样(代码新了、口径还是旧的)。
#
#   下面这些是【管理员统一下发的采集口径】, 不属于同事的本地设置, 所以强制覆盖。
#   同事自己的东西 —— 浏览器 api/key、头像目录、轨迹目录、windows 列表、
#   账号文件 —— 一律不在此列, 永远不会被覆盖。
POLICY_KEYS = (
    # ★★ 2026-09-19 用户要求"采集州/性别/时间/年纪 做成框框供选择"之后,
    #    collect_regions 从这份名单里【摘掉】了。
    #    原因: 界面上现在有「采集地区」下拉框, 同事选了会写进自己的 config.json;
    #          而这里每次更新都会把 POLICY_KEYS 里的键【强制】改成服务器的值 ——
    #          两条正好打架, 同事的选择下一次启动就被抹掉, 下拉框等于白做。
    #    摘掉不影响"老机器 12 个州"的修复: 那条路走的是界面/引擎里的
    #    _policy_rev 一次性纠正(_ADMIN_POLICY), 和这份名单无关。
    #    其余键(min_athletes/max_followers/jobs/速率/闸门…)仍强制下发 ——
    #    它们没有暴露成下拉框, 属于"管理员口径"。
    # ★ 2026-09-19: min_athletes 也摘掉了 —— 界面上「每段≥」下拉框能选,
    #   留在这里会每次更新把同事的选择强制改回服务器值, 和下拉框打架。
    #   老配置的 200 仍由界面/引擎的 _policy_rev 一次性纠正兜住。
    "collect_auto_regions", "max_followers",
    "collect_target_per_account", "segs_per_region",
    "geo_filter", "geo_band_min_km", "geo_band_max_km",
    "ny_exempt_max_km", "lb_max_pages",
    "rate_nav_sec", "rate_api_sec", "rate_act_sec",
    "collect_max_minutes", "stall_exit_sec",
    "jobs", "collect_enabled",
    "claim_server", "claim_key",
    # ★★ 2026-09-19 "_policy_rev" 只做占位, 【绝不能】预先写进分发包的 config.json ★★
    #   "_policy_rev" 是【管理员口径版本号】, 界面和引擎靠它判断要不要强制纠正
    #   采集口径。它必须由【新代码自己】写进去。
    #   如果把 _policy_rev: 2 预先放进了分发包的 config.json:
    #     老机器的旧 update.py 走的是"缺失的键就补上" —— 它会把这个键补进去,
    #     然后新界面/新引擎一看版本号已经 >= 2, 就以为口径早就纠正过了,
    #     直接 return, 采集州【永远停在 12 个州】。
    #   所以这里虽然有这一项, 但因为服务器的 config.json 里没有它,
    #   forced 分支要 k in remote 才成立, 实际永远不触发 —— 是安全的空操作。
    #   将来真要下发它, 必须同时确认老机器上不会出现"键在、值对、口径其实是错的"。
    "_policy_rev",
)


def is_protected(name):
    return name in PROTECTED or any(name.startswith(p)
                                    for p in PROTECTED_PREFIX)


def log(msg, quiet=False):
    if not quiet:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            sys.stdout.write(msg.encode("gbk", "replace").decode("gbk") + "\n")
            sys.stdout.flush()


def find_cfg():
    for c in (BASE / "config.json", BASE / "配置" / "config.json",
              BASE.parent / "配置" / "config.json",
              BASE.parent / "config.json"):
        if c.is_file():
            return c
    return None


def safe_rel(rel):
    """校验 zip 条目名(相对路径)。返回 True 表示可以安全落地。

    ★★ 子代理点名: 只判 ".." 是不够的 ★★
        '/abs/evil.py'       首段是 "/"       -> 会写到盘根/绝对路径
        'C:/x.py'            含冒号          -> Windows 盘符/ADS
        'sv_ttk/x.py:ads'    NTFS 备用数据流 -> 写到隐藏流
      这三个都【不含 ".."】, 用老办法全部漏网。所以逐段校验:
        · 每段非空、不是 "." / ".."
        · 每段不含冒号 / 反斜杠 / 竖线 等危险字符
        · 不能是绝对路径
    """
    try:
        raw = str(rel or "")
        # ★ 不能用 .strip() —— 那会把前后的空格提前吃掉, 下面第 146 行的
        #   "前后空格" 检查就永远为真、形同虚设。
        #   为什么前后空格危险: Windows 会【静默截断】尾随空格,
        #   于是 "x.py " 和 "x.py" 落到同一个文件, 可用来绕过保护名单。
        if raw != raw.strip():
            return False
        n = raw.replace("\\", "/")
        if not n or n.startswith("/") or Path(n).is_absolute():
            return False
        for seg in n.split("/"):
            if not seg or seg in (".", ".."):
                return False
            if any(c in seg for c in ':*?"<>|'):
                return False
            if seg != seg.strip():          # 段内前后空格(同上, 兜底)
                return False
        return True
    except Exception:
        return False


def safe_name(n):
    """只接受同级目录下的普通文件名, 防目录穿越"""
    if not n or n.startswith("."):
        return False
    if "/" in n or "\\" in n or ".." in n:
        return False
    return True


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merge_config(local_path, remote_bytes, quiet):
    """补缺失的键; 另外把【管理员策略键】强制改成服务器上的值。

    ★ 普通键: 只补缺失, 绝不覆盖(同事自己填的值必须留住)。
    ★ POLICY_KEYS: 强制跟服务器走 —— 否则老发行包写进去的
      "12 州 / 每段≥200" 永远改不掉, 同事的采集口径会一直和最新版不一样。
    """
    try:
        remote = json.loads(remote_bytes.decode("utf-8"))
    except Exception:
        return []
    try:
        local = json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(remote, dict) or not isinstance(local, dict):
        return []
    added = [k for k in remote if k not in local]
    forced = [k for k in POLICY_KEYS
              if k in remote and k in local and local.get(k) != remote.get(k)]
    if not added and not forced:
        return []
    for k in added:
        local[k] = remote[k]
    for k in forced:
        local[k] = remote[k]
    # 保持原有键顺序, 新键追加在后面
    # ★ 原子写: 直接 write_text 写一半被打断会留下截断的 JSON,
    #   下次启动 json.loads 失败 -> 界面/引擎直接起不来。
    import os as _os
    _txt = json.dumps(local, ensure_ascii=False, indent=2) + "\n"
    _tmp = local_path.with_name(local_path.name + ".tmp")
    _tmp.write_text(_txt, encoding="utf-8")
    _os.replace(_tmp, local_path)
    if added:
        log("    config.json: 新增 %s" % ", ".join(added), quiet)
    if forced:
        log("    config.json: ★ 按管理员口径纠正 %s" % ", ".join(forced))
    return added + forced


def main():
    auto = "--auto" in sys.argv
    check_only = "--check" in sys.argv

    cfg_path = find_cfg()
    if not cfg_path:
        log("  [更新] 找不到 config.json, 跳过", auto)
        return 0
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        log("  [更新] config.json 读不了(%s), 跳过" % str(e)[:40], auto)
        return 0

    server = str(cfg.get("claim_server") or "").rstrip("/")
    key = str(cfg.get("claim_key") or "")
    if not server:
        log("  [更新] 没配 claim_server, 跳过", auto)
        return 0

    try:
        import requests
    except ImportError:
        log("  [更新] 还没装 requests, 跳过", auto)
        return 0

    hdr = {"X-API-Key": key} if key else {}

    # ---------------- 1. 问服务器当前版本 ----------------
    try:
        r = requests.get(server + "/pkg/manifest", headers=hdr, timeout=TIMEOUT)
        if r.status_code == 401:
            log("  [更新] 服务器说 key 不对, 跳过", auto)
            return 0
        r.raise_for_status()
        man = r.json()
    except Exception as e:
        log("  [更新] 连不上服务器, 跳过更新 (%s)" % str(e)[:60], auto)
        return 0

    remote = {k: v for k, v in (man.get("files") or {}).items()
              if safe_name(k)}
    ver = str(man.get("version") or "")
    if not remote or not ver:
        log("  [更新] 服务器还没发布过版本", auto)
        return 0

    # ---------------- 2. 本地比对 ----------------
    changed = []
    for name, info in remote.items():
        if name in PROTECTED:
            continue
        p = BASE / name
        if not p.is_file() or sha_file(p) != info.get("sha256"):
            changed.append(name)

    ver_local = ""
    if VER_FILE.is_file():
        try:
            ver_local = VER_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    if not changed and ver == ver_local:
        log("  [更新] 已是最新版本 (%s)" % ver, auto)
        return 0

    if check_only:
        log("  服务器版本: %s" % ver)
        log("  本地版本  : %s" % (ver_local or "未知"))
        log("  需要更新 %d 个文件: %s" % (len(changed), ", ".join(changed) or "(仅配置)"))
        return 0

    log("  [更新] 发现新版本 %s, 正在下载 ..." % ver, quiet=False)

    # ---------------- 3. 下载整包 ----------------
    try:
        r = requests.get(server + "/pkg/latest.zip", headers=hdr,
                         timeout=max(TIMEOUT, 120))
        r.raise_for_status()
        blob = r.content
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as e:
        log("  [更新] 下载失败, 继续用当前版本 (%s)" % str(e)[:60], auto)
        return 0

    # ---------------- 4. 逐个文件原子替换 ----------------
    done, failed = [], []
    # ★ 清单就是白名单: zip 里出现清单之外的文件一律不写。
    #   以前 want 为 None 时整个哈希校验被跳过, 于是一个"清单外"的文件
    #   会被无校验地落盘 —— 配合"人人都有发布密钥"就是可用的投毒链。
    allowed = set(remote)
    for info in zf.infolist():
      try:
        if info.is_dir():
            continue
        # ★★ 2026-09-20 支持子目录 ★★
        #   原来 Path(...).name 会把 sv_ttk/theme/light.tcl 拍成 light.tcl,
        #   于是子目录结构全丢, 解出来一堆散落文件。
        #   改用【相对路径】, 并用 safe_rel 逐段校验。
        rel = str(info.filename).replace("\\", "/")
        name = Path(rel).name               # 保护名单是按文件名写的, 判名用基名
        if not safe_rel(rel):
            failed.append(rel + "(路径不合法, 已拒绝)")
            continue
        if name not in allowed:
            failed.append(name + "(不在服务器清单里, 已拒绝)")
            continue
        data = zf.read(info)

        # 校验服务器给的哈希, 防止传输出错
        want = (remote.get(name) or {}).get("sha256")
        if not want or sha_bytes(data) != want:
            failed.append(name + "(哈希不符, 已拒绝)")
            continue

        if name == "config.json":
            merge_config(cfg_path, data, auto)
            continue
        # ★ 子目录首次落地时父目录还不存在, 不建就会 FileNotFoundError
        _dst = BASE / rel
        try:
            _dst.parent.mkdir(parents=True, exist_ok=True)
        except Exception as _e:
            failed.append("%s(建目录失败: %s)" % (rel, str(_e)[:30]))
            continue
        if is_protected(name):
            continue

        dst = BASE / name
        if dst.is_file() and sha_file(dst) == sha_bytes(data):
            continue                      # 没变
        tmp = dst.with_name(dst.name + ".tmp")
        try:
            tmp.write_bytes(data)
            import os
            os.replace(tmp, dst)          # 原子替换
            done.append(name)
        except PermissionError:
            # 正在运行的 .bat 会被系统占用 —— 下次启动时自动生效
            try:
                tmp.unlink()
            except Exception:
                pass
            failed.append(name + "(正在使用, 下次生效)")
        except Exception as e:
            try:
                tmp.unlink()
            except Exception:
                pass
            failed.append("%s(%s)" % (name, str(e)[:30]))
      except Exception as _one_err:
        # 单个文件出错不能中断整批(否则会留下"部分新部分旧"的混合安装)
        failed.append("%s(处理异常: %s)"
                      % (Path(info.filename).name, str(_one_err)[:30]))

    # ---------------- 5. 记录版本 ----------------
    try:
        VER_FILE.write_text(ver, encoding="utf-8")
    except Exception:
        pass

    # 真的换了东西就要让同事看见；"已是最新"才静默
    if done:
        log("  [更新] 已更新 %d 个文件: %s" % (len(done), ", ".join(done)))
    for f in failed:
        log("  [更新] 跳过 %s" % f)
    if not done and not failed:
        log("  [更新] 已是最新版本 (%s)" % ver, auto)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        # 更新器自己绝不能把主程序搞挂
        try:
            print("  [更新] 意外错误, 已忽略: %s" % str(e)[:80], flush=True)
        except Exception:
            pass
        sys.exit(0)
