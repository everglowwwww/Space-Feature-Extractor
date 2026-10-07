#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享办公空间特征提取 —— 单一入口 / 增量分析管道（标准化流程的"一次命令"入口）

作用：扫描 input/，对【尚未分析】的单元自动补跑阶段 A / 阶段 B，
      并把结果写入 output/{项目}/{单元}/，最后回写 manifest.csv 的「状态」。
      幂等 + 增量：已完成的单元自动跳过，只处理新增/缺漏。

依赖已有脚本（同目录 scripts/）：
  llm_phase_a.py     阶段A-视觉：DeepSeek 看图 -> llm_understanding.json
  dxf_parser.py      阶段A-几何：DXF 精确尺度融合进 llm_understanding.json
  space_analyzer.py  阶段B：OpenCV + Mask2Former -> features.* + 分割图

用法（每种都会保持完全相同的执行流程，只是范围不同）：
  python scripts/run_pipeline.py --dry-run          # 只输出状态总览 + 聚合汇总，不跑
  python scripts/run_pipeline.py --interactive      # 概览后暂停询问是否执行
  python scripts/run_pipeline.py --phase a          # 只补跑缺阶段A的单元
  python scripts/run_pipeline.py --phase b          # 只补跑已有阶段A但缺阶段B的单元
  python scripts/run_pipeline.py                     # 默认 all：缺什么补什么
  python scripts/run_pipeline.py --unit 1-北京盈科中心/北京盈科中心-05   # 只处理指定单元
  python scripts/run_pipeline.py --force            # 忽略"已完成"状态，强制重跑
  python scripts/run_pipeline.py --report           # 阶段B额外生成 HTML 报告

环境：阶段B需要离线变量与模型缓存路径（默认带推理，可用 M2F_MODEL_DIR 覆盖）。
"""
import os, sys, csv, glob, subprocess, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(ROOT, "input")
OUTPUT = os.path.join(ROOT, "output")
SCRIPTS = os.path.join(ROOT, "scripts")
MANIFEST = os.path.join(ROOT, "manifest.csv")

# 阶段B所需的默认模型缓存（可被环境变量 M2F_MODEL_DIR 覆盖）
DEFAULT_M2F_DIR = r"E:\毕业论文\.venv\hf_cache\model_download"

# 阶段B运行必须的离线变量
def run_env():
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    if "M2F_MODEL_DIR" not in env:
        env["M2F_MODEL_DIR"] = DEFAULT_M2F_DIR
    return env


def discover_units():
    """扫描 input/{项目}/{单元}，返回已标准化（含 plan.png）的单元列表 [(项目, 单元), ...]。"""
    units = []
    for proj in sorted(os.listdir(INPUT)):
        proj_path = os.path.join(INPUT, proj)
        if not os.path.isdir(proj_path):
            continue
        if not proj[:1].isdigit() and '-' not in proj[:3]:
            continue  # 仅处理 N-项目名 形式的项目夹
        for unit in sorted(os.listdir(proj_path)):
            up = os.path.join(proj_path, unit)
            if not os.path.isdir(up):
                continue
            # 只要已标准化的单元（含 plan.png + photo_*.jpg 或 unit.dxf）
            if os.path.isfile(os.path.join(up, "plan.png")):
                units.append((proj, unit))
    return units


def unit_status(proj, unit):
    out_dir = os.path.join(OUTPUT, proj, unit)
    a = os.path.isfile(os.path.join(out_dir, "llm_understanding.json"))
    b = os.path.isfile(os.path.join(out_dir, "features.json"))
    return out_dir, a, b


def run_stage_a(proj, unit):
    up = os.path.join(INPUT, proj, unit)
    out_dir = os.path.join(OUTPUT, proj, unit)
    os.makedirs(out_dir, exist_ok=True)
    out_json = os.path.join(out_dir, "llm_understanding.json")
    # 阶段A-视觉
    print(f"    [A-视觉] {proj}/{unit}")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "llm_phase_a.py"),
                    "--case-dir", up, "--out", out_json, "--name", unit],
                   check=True, env=run_env())
    # 阶段A-几何（若有 unit.dxf）
    dxf = os.path.join(up, "unit.dxf")
    if os.path.isfile(dxf):
        print(f"    [A-几何] {proj}/{unit}")
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "dxf_parser.py"),
                        "--dxf", dxf, "--llm-json", out_json],
                       check=True, env=run_env())
    return out_json


def run_stage_b(proj, unit, report):
    up = os.path.join(INPUT, proj, unit)
    out_dir = os.path.join(OUTPUT, proj, unit)
    plan = os.path.join(up, "plan.png")
    photos = sorted(glob.glob(os.path.join(up, "photo_*.jpg")))
    cmd = [sys.executable, os.path.join(SCRIPTS, "space_analyzer.py"),
           "--plan", plan, "--photos"] + photos
    cmd += ["--llm-json", os.path.join(out_dir, "llm_understanding.json"),
            "--name", f"{proj} {unit}", "--out", out_dir]
    if report:
        cmd.append("--report")
    print(f"    [B] {proj}/{unit} ({len(photos)} 张照片)")
    subprocess.run(cmd, check=True, env=run_env())


def load_manifest():
    if not os.path.isfile(MANIFEST):
        return None
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def update_manifest(rows, done_map):
    """把 (项目, 单元) -> 状态 写回 manifest.csv（容错：占用则跳过）。"""
    if rows is None:
        return
    idx = {(r["项目"], r["单元(新名)"]): r for r in rows}
    for (proj, unit), st in done_map.items():
        r = idx.get((proj, unit))
        if r is not None:
            r["状态"] = st
    try:
        with open(MANIFEST, "w", newline="", encoding="utf-8-sig") as f:
            cols = list(rows[0].keys())
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"  [manifest] 已更新 {len(done_map)} 个单元的「状态」")
    except PermissionError:
        print("  [manifest] 被占用，跳过状态回写（不影响分析结果）")


def plan_units(units, phase, force):
    """对每个单元计算 need_a/need_b，打印状态行；同时统计已/待处理数。"""
    plans = []
    a_done = b_done = 0
    for proj, unit in units:
        out_dir, ad, bd = unit_status(proj, unit)
        if ad:
            a_done += 1
        if bd:
            b_done += 1
        if phase == "a":
            need_a = (not ad) or force
            need_b = False
        elif phase == "b":
            need_a = False
            need_b = (ad and not bd) or force
        else:  # all
            need_a = (not ad) or force
            need_b = (not bd) or force
        act = []
        if need_a:
            act.append("阶段A")
        if need_b:
            act.append("阶段B")
        state = ("需" + "+".join(act)) if act else ("已完成" if (ad and bd) else "待阶段A")
        print(f"  {proj}/{unit:<26} 阶段A={'√' if ad else '×'} 阶段B={'√' if bd else '×'}  → {state}")
        plans.append({"proj": proj, "unit": unit, "need_a": need_a, "need_b": need_b, "out": out_dir})
    return plans, a_done, b_done


def main():
    ap = argparse.ArgumentParser(description="共享办公空间特征提取——增量分析管道")
    ap.add_argument("--phase", choices=["a", "b", "all"], default="all")
    ap.add_argument("--unit", help="只处理指定单元，格式：{项目}/{单元}；多个用英文逗号分隔")
    ap.add_argument("--force", action="store_true", help="忽略已完成状态，强制重跑")
    ap.add_argument("--dry-run", action="store_true", help="只输出状态总览，不执行")
    ap.add_argument("--interactive", action="store_true", help="概览后暂停询问再执行")
    ap.add_argument("--report", action="store_true", help="阶段B生成 HTML 报告")
    args = ap.parse_args()

    units = discover_units()
    if not units:
        print("未找到可处理的单元（input 下需有 plan.png）")
        return

    # 同步 manifest：扫描 input，把新增单元写入 manifest（保留已有状态、精简字段）。
    # 这样每次"检查 input"都会让 manifest 反映最新内容，不再手持旧数据。
    try:
        import gen_manifest as gm
        mrows, _rrows = gm.build_rows()
        gm.write_manifest(mrows)
    except Exception as e:
        print(f"  [提示] manifest 同步跳过: {e}")

    if args.unit:
        want = set(args.unit.split(","))
        units = [u for u in units if "/".join(u) in want]
    if not units:
        print("未找到可处理的单元（input 下需有 plan.png）")
        return

    print("=" * 70)
    print(f"共享办公空间分析管道  |  阶段: {args.phase}  |  单元: {len(units)} 个")
    print("=" * 70)

    plans, a_done, b_done = plan_units(units, args.phase, args.force)
    total = len(units)
    will_a = sum(1 for p in plans if p["need_a"])
    will_b = sum(1 for p in plans if p["need_b"])

    # 聚合概览
    print("-" * 70)
    print(f"[概览] 共 {total} 个单元")
    print(f"  阶段A: 完成 {a_done} / 待处理 {total - a_done}   (本批将执行 {will_a})")
    print(f"  阶段B: 完成 {b_done} / 待处理 {total - b_done}   (本批将执行 {will_b})")
    print("-" * 70)

    if args.dry_run:
        print("\n[dry-run] 未做任何分析。确认后用 --phase a / --phase b 或 --interactive。")
        return

    if args.interactive:
        if will_a + will_b == 0:
            print("所有单元已处理完成，无需执行。")
            return
        resp = input("是否开始处理未完成内容? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("已取消，未执行任何分析。")
            return

    done_map = {}
    for p in plans:
        proj, unit = p["proj"], p["unit"]
        try:
            if p["need_a"]:
                run_stage_a(proj, unit)
        except Exception as e:
            print(f"  [失败] {proj}/{unit} 阶段A: {str(e)[:120]}")
        a_check = os.path.isfile(os.path.join(p["out"], "llm_understanding.json"))
        if a_check and p["need_b"]:
            try:
                run_stage_b(proj, unit, args.report)
            except Exception as e:
                print(f"  [失败] {proj}/{unit} 阶段B: {str(e)[:120]}")
        # 按实际产物回写状态（阶段A 失败停留在待分析，阶段B 失败停留阶段A完成）
        _, a2, b2 = unit_status(proj, unit)
        if b2:
            done_map[(proj, unit)] = "阶段B完成"
        elif a2:
            done_map[(proj, unit)] = "阶段A完成"
        else:
            done_map[(proj, unit)] = "待分析"

    update_manifest(load_manifest(), done_map)
    print("\n[完成] 本批增量处理结束。")


if __name__ == "__main__":
    main()
