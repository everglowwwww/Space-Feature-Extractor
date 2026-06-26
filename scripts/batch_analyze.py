#!/usr/bin/env python3
"""
批量空间分析器 — 遍历 input/ 下所有案例文件夹，逐一调用 space_analyzer
=======================================================================
目录约定:
  project_root/
    input/
      案例01_WeWork/
        plan.jpg          (必需)
        photo_01.png      (可选,可多张)
        llm_understanding.json  (可选)
      案例02_SOHO/
        plan.png
        ...
    output/
      案例01_WeWork/      (自动创建)
        features.json
        features.csv
        plan_binary.png
        seg_semantic.png
        seg_overlay.png
      案例02_SOHO/
        ...

用法:
  python3 batch_analyze.py --input-dir ./input --output-dir ./output
  python3 batch_analyze.py --input-dir ./input --output-dir ./output --report
  python3 batch_analyze.py --input-dir ./input --output-dir ./output --case 案例01_WeWork
"""

import os, sys, argparse, time, json, csv

# 同目录下的 space_analyzer + card_generator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from space_analyzer import run as analyze_one
from card_generator import generate_all_visuals, batch_generate_cards

PLAN_PATTERNS = ["plan.jpg", "plan.jpeg", "plan.png", "plan.bmp",
                 "plan.tif", "plan.tiff", "平面图.jpg", "平面图.png"]
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
LLM_JSON_NAMES = ["llm_understanding.json", "llm_spatial_understanding.json",
                   "llm.json", "llm_input.json"]


def find_plan(case_dir):
    """在案例文件夹中查找平面图."""
    for name in PLAN_PATTERNS:
        p = os.path.join(case_dir, name)
        if os.path.isfile(p):
            return p
    # 回退: 任何以 plan 开头的图片
    for f in sorted(os.listdir(case_dir)):
        if f.lower().startswith("plan") and os.path.splitext(f)[1].lower() in PHOTO_EXTS:
            return os.path.join(case_dir, f)
    return None


def find_photos(case_dir, plan_path):
    """找到所有非平面图的照片."""
    plan_base = os.path.basename(plan_path) if plan_path else ""
    photos = []
    for f in sorted(os.listdir(case_dir)):
        if f == plan_base:
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in PHOTO_EXTS and not f.lower().startswith("plan"):
            photos.append(os.path.join(case_dir, f))
    return photos


def find_llm_json(case_dir):
    """查找 LLM JSON 文件."""
    for name in LLM_JSON_NAMES:
        p = os.path.join(case_dir, name)
        if os.path.isfile(p):
            return p
    return None


def run_batch(input_dir, output_dir, gen_report=False, target_case=None):
    input_dir = os.path.abspath(input_dir)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 收集案例
    cases = []
    for name in sorted(os.listdir(input_dir)):
        case_dir = os.path.join(input_dir, name)
        if not os.path.isdir(case_dir):
            continue
        if target_case and name != target_case:
            continue
        plan = find_plan(case_dir)
        if not plan:
            print("[SKIP] {}: 未找到平面图 (plan.*)".format(name))
            continue
        photos = find_photos(case_dir, plan)
        llm = find_llm_json(case_dir)
        cases.append({
            "name": name,
            "plan": plan,
            "photos": photos,
            "llm_json": llm,
            "out": os.path.join(output_dir, name),
        })

    if not cases:
        print("未找到可处理的案例 (input_dir={})".format(input_dir))
        return

    total = len(cases)
    print("\n" + "#" * 65)
    print("  Batch Analyzer — {} case(s) to process".format(total))
    print("#" * 65)

    results = []
    for i, c in enumerate(cases):
        t0 = time.time()
        print("\n>>> [{}/{}] {}".format(i + 1, total, c["name"]))
        try:
            row = analyze_one(c["plan"], c["photos"], c["name"], c["out"],
                              llm_json=c["llm_json"], gen_report=gen_report)
            elapsed = round(time.time() - t0, 1)
            results.append({"case": c["name"], "status": "OK",
                            "features": len([k for k in row if k != "case_name"]),
                            "time_s": elapsed})
        except Exception as e:
            elapsed = round(time.time() - t0, 1)
            results.append({"case": c["name"], "status": "ERROR: {}".format(str(e)[:80]),
                            "features": 0, "time_s": elapsed})
            import traceback; traceback.print_exc()

    # 汇总报告
    summary_path = os.path.join(output_dir, "batch_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, indent=2, ensure_ascii=False)

    summary_csv = os.path.join(output_dir, "batch_summary.csv")
    with open(summary_csv, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=["case", "status", "features", "time_s"])
        writer.writeheader()
        writer.writerows(results)

    ok = sum(1 for r in results if r["status"] == "OK")
    err = total - ok
    print("\n" + "#" * 65)
    print("  Batch analysis complete: {}/{} OK, {} errors".format(ok, total, err))
    print("  Summary: {}".format(summary_path))
    print("#" * 65)

    # 生成增强可视化 + 案例卡片
    print("\n  Generating visualization cards...")
    batch_generate_cards(output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch Space Analyzer — 批量处理 input/ 下所有案例")
    parser.add_argument("--input-dir", required=True, help="输入根目录 (含案例子文件夹)")
    parser.add_argument("--output-dir", required=True, help="输出根目录")
    parser.add_argument("--report", action="store_true", help="是否生成 HTML 报告")
    parser.add_argument("--case", default=None, help="只处理指定案例 (文件夹名)")
    parser.add_argument("--cards-only", action="store_true",
                        help="跳过分析，只重新生成卡片 (需 features.json 已存在)")
    args = parser.parse_args()
    if args.cards_only:
        # 仅重新生成卡片，不重跑分析
        batch_generate_cards(args.output_dir)
    else:
        run_batch(args.input_dir, args.output_dir,
                  gen_report=args.report, target_case=args.case)
