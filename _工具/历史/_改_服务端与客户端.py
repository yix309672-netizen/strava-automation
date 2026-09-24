# -*- coding: utf-8 -*-
"""更新链路支持子目录 —— 第 2 步: 服务端 + 客户端。

子代理报告的核心发现: 【不是 3 处, 是 6 处】。这一步处理另外 5 处:

  claim_server.py:79   manifest 的 key 用 Path(...).name 拍平 —— 【最关键的一处】。
                       不改它, 客户端从清单里就看不到 sv_ttk/xxx, 子目录永远建不起来,
                       反而会在根目录撒出 __init__.py。而且 /pkg/latest.zip 是
                       原样字节透传(保留子目录) -> 清单与包内容【口径不一致】。
  claim_server.py:252  /pkg/upload 的必需文件检查也拍平
  update.py:283        客户端还原时 Path(info.filename).name 拍平
  update.py:307        子目录首次落地时 dst.parent 不存在 -> FileNotFoundError
  update.py:102        is_protected 要同时判【基名】(保护名单是按文件名写的)
  fix_update.py:190    救急工具同样拍平(最需要救的老机器会走它)

★ 安全: 路径校验必须逐段做。子代理点名 —— 只判 ".." 是不够的:
    '/abs/evil.py'(首段是 /)、'C:/x.py'(含 :)、'sv_ttk/x.py:ads'(NTFS ADS)
    都不含 "..", 会全部漏网。
"""
import pathlib
import py_compile

DONE = []


def edit(path, old, new, tag):
    p = pathlib.Path(path)
    s = p.read_text(encoding="utf-8")
    if old not in s:
        DONE.append("· %s (没匹配到)" % tag)
        return
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    DONE.append("✓ %s" % tag)


# ==================== ① claim_server.py: manifest 保留相对路径 ====================
edit("claim_server.py",
     "            nm = Path(info.filename).name",
     '''            # ★★ 2026-09-20 支持子目录(claude: 这行是【最关键的一处】) ★★
            #   原来用 Path(...).name 拍平, 于是清单里只有 "light.tcl",
            #   而 zip 里是 "sv_ttk/theme/light.tcl" —— 两者口径不一致:
            #   客户端按清单比对, 永远看不到子目录文件 -> 子目录建不起来,
            #   反而可能在根目录撒出 __init__.py。必须保留相对路径。
            nm = info.filename.replace("\\\\", "/")''',
     "claim_server.py:79 manifest 保留相对路径")

edit("claim_server.py",
     "            names = [Path(i.filename).name for i in infos]",
     "            names = [i.filename.replace(\"\\\\\", \"/\") for i in infos]",
     "claim_server.py:252 upload 的必需文件检查")

# ==================== ② update.py ====================
# 安全的相对路径校验(替换 safe_name 的调用方式)
SRC = pathlib.Path("update.py").read_text(encoding="utf-8")
if "def safe_rel(" not in SRC:
    anchor = "def safe_name(n):"
    i = SRC.index(anchor)
    j = SRC.index("\n\n\n", i)
    SAFE_REL = '''def safe_rel(rel):
    """校验 zip 条目名(相对路径)。返回 True 表示可以安全落地。

    ★★ 子代理点名: 只判 ".." 是不够的 ★★
        '/abs/evil.py'       首段是 "/"       -> 会写到盘根/绝对路径
        'C:/x.py'            含 ":"          -> Windows 盘符/ADS
        'sv_ttk/x.py:ads'    NTFS 备用数据流 -> 写到隐藏流
      这三个都【不含 ".."】, 用老办法全部漏网。所以逐段校验:
        · 每段非空、不是 "." / ".."
        · 每段不含 : \\ / 等危险字符
        · 不能是绝对路径
    """
    try:
        n = str(rel or "").replace("\\\\", "/").strip()
        if not n or n.startswith("/") or Path(n).is_absolute():
            return False
        for seg in n.split("/"):
            if not seg or seg in (".", ".."):
                return False
            if any(c in seg for c in ':*?"<>|'):
                return False
            if seg != seg.strip():          # 前后空格: Windows 会截断, 易被利用
                return False
        return True
    except Exception:
        return False


def safe_name(n):'''
    SRC = SRC[:i] + SAFE_REL + SRC[i + len(anchor):]
    pathlib.Path("update.py").write_text(SRC, encoding="utf-8")
    DONE.append("✓ update.py 新增 safe_rel()(逐段校验, 挡绝对路径/盘符/ADS)")

edit("update.py",
     "        name = Path(info.filename).name\n"
     "        if not safe_name(name):\n"
     "            failed.append(Path(info.filename).name + \"(文件名不合法)\")",
     '''        # ★★ 2026-09-20 支持子目录 ★★
        #   原来 Path(...).name 会把 sv_ttk/theme/light.tcl 拍成 light.tcl,
        #   于是子目录结构全丢, 解出来一堆散落文件。
        #   改用【相对路径】, 并用 safe_rel 逐段校验。
        rel = str(info.filename).replace("\\\\", "/")
        name = Path(rel).name               # 保护名单是按文件名写的, 判名用基名
        if not safe_rel(rel):
            failed.append(rel + "(路径不合法, 已拒绝)")''',
     "update.py:283 改用相对路径 + safe_rel")

# 子目录落地前先建父目录
edit("update.py",
     "        if is_protected(name):",
     '''        # ★ 子目录首次落地时父目录还不存在, 不建就会 FileNotFoundError
        _dst = BASE / rel
        try:
            _dst.parent.mkdir(parents=True, exist_ok=True)
        except Exception as _e:
            failed.append("%s(建目录失败: %s)" % (rel, str(_e)[:30]))
            continue
        if is_protected(name):''',
     "update.py:301 落地前建父目录")

print("=" * 76)
for d in DONE:
    print("  " + d)
print()
print("语法检查:")
for f in ("claim_server.py", "update.py"):
    try:
        py_compile.compile(f, doraise=True, cfile="__pycache__/x.pyc")
        print("  OK   " + f)
    except Exception as e:
        print("  FAIL %s  %s" % (f, str(e)[:180]))
