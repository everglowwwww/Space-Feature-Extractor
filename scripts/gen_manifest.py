#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成目录结构整理所需的清单（只扫描 + 输出映射，不做任何改名/移动）。

产出（均在 skill 根目录）：
  manifest.csv            每个空间单元一行（精简）：项目/编号/中文名/单元(新名)/路径/状态
  input_rename_map.csv    改名映射（含旧目录名）：项目/单元(新名)/旧单元目录/源文件/目标文件名/类型/动作

用法：
  python scripts/gen_manifest.py                # 扫描 input/ 并写两份 CSV（保留已有状态）
  python scripts/gen_manifest.py --dry-run      # 只打印预览，不写盘

依据：references/目录结构与命名规范.md v1.0
"""
import os, re, csv, argparse

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(SKILL_ROOT, "input")
IGNORE_DIR = "北京 盈科中心-5"          # 弃用示例，忽略

# 未拆分建筑：占位项目文件夹名 -> 对应总平面图（二者一起登记，便于后续拆分）
PLACEHOLDER_PROJECTS = {
    "8-北京王府国际中心": "北京-8 王府国际中心总平面.jpg",
    "9-北京中航产融大厦": "北京-9 中航产融大厦总平面.jpg",
    "10-北京好世界商业广场": "北京-10 好世界商业广场总平面.jpg",
    "11-北京隆福寺街95号": "北京-11 隆福寺街95号总平面.jpg",
    "12-北京远洋光华国际大厦": "北京-12 远洋光华国际大厦总平面.jpg",
    "13-北京辉煌时代大厦": "北京-13 辉煌时代大厦总平面.jpg",
    "14-北京世茂大厦": "北京-14 世茂大厦总平面.jpg",
    "15-北京宫霄大厦": "北京-15 宫霄大厦总平面.jpg",
    "16-北京酒仙桥路6号": "北京-16 酒仙桥路6号总平面.jpg",
    "17-北京东煌大厦": "北京-17 东煌大厦总平面.jpg",
    "18-北京酒仙桥14号": "北京-18 酒仙桥14号总平面.jpg",
}

# manifest 列（精简，只保留更新后的信息）
MANIFEST_COLS = ["项目", "项目编号", "项目中文名", "单元(新名)", "新单元路径", "状态"]
# 改名表列（含旧目录名，供 apply_restructure 读取）
RENAME_COLS = ["项目", "单元(新名)", "旧单元目录", "源文件", "目标文件名", "类型", "动作"]


def trailing_number(name):
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def detect_plan_unit(files):
    """单元内平面图：优先 AI 渲染 png（盈科系）或 平面-*.png，也认已标准化的 plan.*。"""
    for f in sorted(files):
        if f.lower().startswith("ai") and f.lower().endswith(".png"):
            return f
    for f in sorted(files):
        if f.lower().startswith("平面") and f.lower().endswith(".png"):
            return f
    for f in sorted(files):
        if f.lower().startswith("plan"):
            return f
    return ""


def detect_photos(files):
    """人视图/人视角-*.jpg（原始命名）或 photo_*.jpg（已标准化），按尾部数字排序。"""
    ps = [f for f in files if re.match(r"^人(视图|视角)-\d+", f)]
    ps += [f for f in files if re.match(r"^photo_\d+", f)]
    ps = sorted(set(ps))
    ps.sort(key=lambda x: trailing_number(x) or 0)
    return ps


def load_existing_status():
    """读取现有 manifest.csv 的状态映射 {(项目, 单元(新名)): 状态}，用于保留。"""
    status_map = {}
    mf = os.path.join(SKILL_ROOT, "manifest.csv")
    if os.path.isfile(mf):
        try:
            with open(mf, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    status_map[(r["项目"], r["单元(新名)"])] = r.get("状态", "待分析")
        except Exception:
            pass
    return status_map


def build_rows(status_map=None):
    """扫描 input，返回 (manifest_rows, rename_rows)。status_map 保留已有状态。"""
    manifest = []
    rename = []
    status_map = status_map if status_map is not None else load_existing_status()
    for proj in sorted(os.listdir(INPUT)):
        proj_path = os.path.join(INPUT, proj)
        if not os.path.isdir(proj_path):
            continue
        if proj == IGNORE_DIR:
            continue
        m = re.match(r"^(\d+)-(.+)$", proj)
        if not m:
            continue
        proj_num, proj_cn = m.group(1), m.group(2)
        units = [d for d in os.listdir(proj_path)
                 if os.path.isdir(os.path.join(proj_path, d))]
        units.sort(key=lambda u: (trailing_number(u) is None, trailing_number(u) or 0, u))
        for u in units:
            up = os.path.join(proj_path, u)
            files = os.listdir(up)
            idx = trailing_number(u) or 0
            newu = f"{proj_cn}-{idx:02d}"
            plan_src = detect_plan_unit(files)
            photos = detect_photos(files)
            dxf = [f for f in files if f.lower().endswith(".dxf")]
            dxf_src = dxf[0] if dxf else ""
            # 精简 manifest：只用更新后的信息，状态保留
            manifest.append({
                "项目": proj, "项目编号": proj_num, "项目中文名": proj_cn,
                "单元(新名)": newu, "新单元路径": os.path.join(proj, newu),
                "状态": status_map.get((proj, newu), "待分析"),
            })
            # 改名表：带旧目录名，供 apply_restructure 对新增单元做标准化
            if plan_src:
                rename.append([proj, newu, u, plan_src, "plan.png", "平面图", "重命名"])
            for i, p in enumerate(photos, 1):
                rename.append([proj, newu, u, p, f"photo_{i:02d}.jpg", "照片", "重命名"])
            if dxf_src:
                rename.append([proj, newu, u, dxf_src, "unit.dxf", "DXF", "重命名"])
    return manifest, rename


def write_manifest(manifest):
    mf = os.path.join(SKILL_ROOT, "manifest.csv")
    try:
        with open(mf, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
            w.writeheader()
            w.writerows(manifest)
        return True
    except PermissionError:
        return False


def main(dry_run=False):
    manifest, rename = build_rows()
    if dry_run:
        print(f"[Dry-run] 单元数: {len(manifest)}  文件映射数: {len(rename)}")
        for row in manifest[:5]:
            print(row)
        return

    ok = write_manifest(manifest)
    print(f"[{'已写出' if ok else '跳过-被占用'} manifest.csv] ({len(manifest)} 个单元)")
    mf = os.path.join(SKILL_ROOT, "input_rename_map.csv")
    with open(mf, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(RENAME_COLS)
        w.writerows(rename)
    print(f"已写出 {os.path.join(SKILL_ROOT, 'input_rename_map.csv')}  ({len(rename)} 条文件映射)")
    print(f"\n占位项目 {len(PLACEHOLDER_PROJECTS)} 个：{', '.join(PLACEHOLDER_PROJECTS)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成目录整理清单（只读，不改文件）")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写盘")
    main(dry_run=ap.parse_args().dry_run)
