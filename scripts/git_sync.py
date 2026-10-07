#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_sync.py —— 一键提交并同步到 GitHub（含数据强制入库 + 安全检查）

作用：把 skill 的全部改动（代码/文档 + input/output 数据）一次性提交并推送，
      避免手动忘记 `git add -f input output`（input/output 在 .gitignore 里）。

用法：
  python scripts/git_sync.py --dry-run                  # 只看将要提交什么，不提交
  python scripts/git_sync.py -m "说明"                   # 提交（不推送）
  python scripts/git_sync.py -m "说明" --push            # 提交并推送（推荐）
  python scripts/git_sync.py -m "说明" --push --no-data  # 只提交代码/文档，不含数据
  python scripts/git_sync.py --push                      # 用自动生成的提交信息

安全检查（重要）：
  - `config/deepseek.json`（API 密钥）与 `_restore_backup/`（冗余备份）**绝不允许入库**；
    若意外被暂存，脚本会中止并提示，不会提交。
"""
import os, sys, argparse, subprocess, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN = ("config/deepseek.json", "_restore_backup/")
DATA_DIRS = ["input", "output"]


def git(*args, check=True):
    """执行 git 命令并返回 stdout（UTF-8）。"""
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        sys.exit(f"[git 失败] git {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return (r.stdout or "").strip()


def detect_proxy():
    """探测可用代理（GitHub 直连常被墙）：环境变量优先，其次 Windows 系统代理(注册表)。
    返回 'http://host:port' 或 None。"""
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(k)
        if v:
            return v if "://" in v else f"http://{v}"
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    srv = str(winreg.QueryValueEx(key, "ProxyServer")[0])
                    return srv if "://" in srv else f"http://{srv}"
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="一键提交并同步 skill 到 GitHub")
    ap.add_argument("-m", "--message", default=None, help="提交信息（缺省自动生成）")
    ap.add_argument("--push", action="store_true", help="提交后推送到 GitHub")
    ap.add_argument("--no-data", action="store_true", help="不强制加入 input/output 数据")
    ap.add_argument("--proxy", default=None, help="推送用代理(如 http://127.0.0.1:7890)，缺省自动探测")
    ap.add_argument("--no-proxy", action="store_true", help="推送不走代理")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不提交")
    args = ap.parse_args()

    # 是否在 git 仓库内
    if git("rev-parse", "--is-inside-work-tree", check=False) != "true":
        sys.exit(f"[错误] {ROOT} 不是 git 仓库")

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "main"

    # 1) 暂存全部改动（遵循 .gitignore）
    git("add", "-A")
    # 2) 数据强制入库（input/output 默认被 gitignore）
    if not args.no_data:
        for d in DATA_DIRS:
            if os.path.isdir(os.path.join(ROOT, d)):
                git("add", "-f", d, check=False)

    staged = git("diff", "--cached", "--name-only").splitlines()
    # 3) 安全检查
    bad = [p for p in staged if p in FORBIDDEN or p.startswith("_restore_backup/")]
    if bad:
        sys.exit("[中止] 暂存区含禁止入库的文件：\n  " + "\n  ".join(bad[:10]) +
                 "\n请检查 .gitignore，勿提交密钥/备份。")

    # 4) 概览
    status_counts = {}
    for line in git("diff", "--cached", "--name-status").splitlines():
        k = line[:1]
        status_counts[k] = status_counts.get(k, 0) + 1
    label = {"A": "新增", "M": "修改", "D": "删除", "R": "重命名", "C": "复制"}
    print(f"[仓库] {ROOT}")
    print(f"[分支] {branch}   [暂存] {len(staged)} 个文件  " +
          " ".join(f"{label.get(k, k)}:{v}" for k, v in sorted(status_counts.items())))
    if not staged:
        print("[提示] 没有需要提交的改动。")
        return

    if args.dry_run:
        print("\n[dry-run] 将提交以上内容，未实际提交。")
        for p in staged[:15]:
            print("   ", p)
        if len(staged) > 15:
            print(f"    ...（共 {len(staged)} 个）")
        return

    # 5) 提交
    msg = args.message or f"chore: 同步更新 ({datetime.datetime.now():%Y-%m-%d %H:%M})"
    git("commit", "-m", msg)
    print(f"[提交] {git('log', '-1', '--format=%h | %s')}")

    # 6) 推送（自动走代理：GitHub 直连常被墙）
    if args.push:
        proxy = None if args.no_proxy else (args.proxy or detect_proxy())
        cmd = ["git"]
        if proxy:
            cmd += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
        cmd += ["push", "origin", branch]
        print(f"[推送] {'经代理 ' + proxy + ' ' if proxy else '(直连) '}git push origin {branch} ...")
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            sys.exit(f"[推送失败]（网络/代理问题？可加 --proxy http://127.0.0.1:7890）\n{out}")
        print("[推送] 完成 ->", [l for l in out.splitlines() if "->" in l or "main" in l][-1:] or out[-120:])
        ahead = git("rev-list", "--left-right", "--count", f"origin/{branch}...{branch}")
        print(f"[同步] 领先/落后 = {ahead}（0 0 表示完全同步）")
    else:
        print("[提示] 未推送。加 --push 可推送到 GitHub。")


if __name__ == "__main__":
    main()
