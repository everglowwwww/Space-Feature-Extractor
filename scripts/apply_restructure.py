#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行目录结构与命名整理（依据 references/目录结构与命名规范.md v1.0）。

只做结构/命名，不跑阶段 A/B。步骤：
  1. 备份 input/output 到 _restore_backup/（可回滚）
  2. 单元文件夹改名：旧单元目录 -> {项目中文名}-{NN}
  3. 单元内文件标准化：源文件 -> plan.png / photo_0N.jpg / unit.dxf
  4. input 下 8~18 号占位项目空夹
  5. output 镜像骨架：{项目}/{单元} 空目录一次性建全
  6. 旧版平铺示例归档到 _legacy/

用法：
  python scripts/apply_restructure.py --dry-run   只打印计划，不动任何文件
  python scripts/apply_restructure.py             真执行（先备份）
  python scripts/apply_restructure.py --no-backup 不备份直接执行
"""
import os, sys, csv, shutil, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(ROOT, "input")
OUTPUT = os.path.join(ROOT, "output")
LEGACY = os.path.join(ROOT, "_legacy")
BACKUP = os.path.join(ROOT, "_restore_backup")

# 8~18 号占位项目（与 gen_manifest.PLACEHOLDER_PROJECTS 一致）
PLACEHOLDER_PROJECTS = ["8-北京王府国际中心", "9-北京中航产融大厦", "10-北京好世界商业广场",
    "11-北京隆福寺街95号", "12-北京远洋光华国际大厦", "13-北京辉煌时代大厦", "14-北京世茂大厦",
    "15-北京宫霄大厦", "16-北京酒仙桥路6号", "17-北京东煌大厦", "18-北京酒仙桥14号"]
# 旧版平铺示例（input 与 output 各一份，归档到 _legacy/）
LEGACY_ITEMS = [(os.path.join(INPUT, "北京 盈科中心-5"), "input_北京 盈科中心-5"),
                (os.path.join(OUTPUT, "北京 盈科中心-5"), "output_北京 盈科中心-5")]


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def plan():
    rename = load(os.path.join(ROOT, "input_rename_map.csv"))
    # 没有改名表（重命名已完成 / 无新增单元）=> 无操作
    if not rename:
        return dict(units=[], folder_ops=[], file_ops=[],
                    new_mkdir_input=[], new_mkdir_output=[], legacy_ops=[])

    # 项目 + 单元(新名) -> 旧单元目录（来自改名表）
    old_dir = {(r["项目"], r["单元(新名)"]): r["旧单元目录"] for r in rename}
    # 去重的 (项目, 单元(新名)) 列表
    units = []
    seen = set()
    for r in rename:
        k = (r["项目"], r["单元(新名)"])
        if k not in seen:
            seen.add(k)
            units.append(k)

    folder_ops = []
    for proj, unit in units:
        old = os.path.join(INPUT, proj, old_dir[(proj, unit)])
        new = os.path.join(INPUT, proj, unit)
        if os.path.isdir(old) and os.path.normpath(old) != os.path.normpath(new):
            folder_ops.append((old, new))

    file_ops = []
    for r in rename:
        # 文件在旧文件夹内改名（先改名文件，后改文件夹）
        d = os.path.join(INPUT, r["项目"], old_dir[(r["项目"], r["单元(新名)"])])
        s = os.path.join(d, r["源文件"])
        t = os.path.join(d, r["目标文件名"])
        if os.path.exists(s) and os.path.normpath(s) != os.path.normpath(t):
            file_ops.append((s, t))

    new_mkdir_input = [os.path.join(INPUT, p) for p in PLACEHOLDER_PROJECTS
                       if not os.path.exists(os.path.join(INPUT, p))]
    new_mkdir_output = []
    all_projects = set(p for p, _ in units) | set(PLACEHOLDER_PROJECTS)
    for p in sorted(all_projects):
        out_p = os.path.join(OUTPUT, p)
        if not os.path.isdir(out_p):
            new_mkdir_output.append(out_p)
        # 有单元的项目，补单元级镜像空夹
        for proj, unit in units:
            if proj == p:
                out_u = os.path.join(out_p, unit)
                if not os.path.isdir(out_u):
                    new_mkdir_output.append(out_u)

    legacy_ops = [(src, os.path.join(LEGACY, name)) for src, name in LEGACY_ITEMS
                  if os.path.exists(src) and not os.path.exists(os.path.join(LEGACY, name))]

    return dict(units=units, folder_ops=folder_ops, file_ops=file_ops,
                new_mkdir_input=new_mkdir_input, new_mkdir_output=new_mkdir_output,
                legacy_ops=legacy_ops)


def run(dry_run, do_backup):
    p = plan()
    print("=" * 70)
    print("目录结构整理计划")
    print("=" * 70)
    print(f"[单元] {len(p['units'])} 个")
    print(f"[① 单元文件夹改名] {len(p['folder_ops'])} 处")
    for old, new in p["folder_ops"]:
        print(f"    {os.path.relpath(old, ROOT)}  ->  {os.path.relpath(new, ROOT)}")
    print(f"[② 内部文件标准化] {len(p['file_ops'])} 处")
    for s, t in p["file_ops"][:8]:
        print(f"    {os.path.relpath(s, ROOT)}  ->  {os.path.relpath(t, ROOT)}")
    if len(p["file_ops"]) > 8:
        print(f"    ... (共 {len(p['file_ops'])} 处)")
    print(f"[③ input 占位项目夹] {len(p['new_mkdir_input'])} 个")
    for d in p["new_mkdir_input"]:
        print(f"    {os.path.relpath(d, ROOT)}/")
    print(f"[④ output 镜像骨架] {len(p['new_mkdir_output'])} 个")
    for d in p["new_mkdir_output"][:8]:
        print(f"    {os.path.relpath(d, ROOT)}/")
    if len(p["new_mkdir_output"]) > 8:
        print(f"    ... (共 {len(p['new_mkdir_output'])} 个)")
    print(f"[⑤ 归档到 _legacy] {len(p['legacy_ops'])} 个")
    for s, t in p["legacy_ops"]:
        print(f"    {os.path.relpath(s, ROOT)}  ->  {os.path.relpath(t, ROOT)}")

    if dry_run:
        print("\n[dry-run] 未做任何更改。确认无误后运行 python scripts/apply_restructure.py")
        return

    if do_backup:
        print("\n[备份] 正在备份 input/output 到 _restore_backup/ ...")
        for src_dir in (INPUT, OUTPUT):
            dst = os.path.join(BACKUP, os.path.basename(src_dir))
            if os.path.isdir(src_dir) and not os.path.exists(dst):
                shutil.copytree(src_dir, dst)
        print(f"[备份] 完成 -> {BACKUP}")

    # ① 文件标准化（先在旧文件夹内改名，再改文件夹）
    for s, t in p["file_ops"]:
        os.rename(s, t)
    # ② 文件夹改名
    for old, new in p["folder_ops"]:
        os.rename(old, new)
    # ③ input 占位
    for d in p["new_mkdir_input"]:
        os.makedirs(d, exist_ok=True)
    # ④ output 骨架
    for d in p["new_mkdir_output"]:
        os.makedirs(d, exist_ok=True)
    # ⑤ 归档
    if not os.path.isdir(LEGACY):
        os.makedirs(LEGACY, exist_ok=True)
    for s, t in p["legacy_ops"]:
        shutil.move(s, t)

    print(f"\n[完成] 结构整理执行完毕。备份: {BACKUP} ; 归档: {LEGACY}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="执行目录结构与命名整理")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不动文件")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    a = ap.parse_args()
    run(dry_run=a.dry_run, do_backup=not a.no_backup)
