#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段A：调用 DeepSeek 多模态视觉模型（deepseek-v4-flash-vision-exp），
对单个案例（平面图 + 透视照）做空间理解，输出 llm_understanding.json。

零第三方依赖（仅 Python 标准库）。

用法：
  # 连通性测试（纯文本，几乎不花钱）
  python scripts/llm_phase_a.py --ping

  # 单案例分析（结果写入案例目录下 llm_understanding.json）
  python scripts/llm_phase_a.py --case-dir "input/北京 盈科中心-5"

  # 输出到指定文件（如对照实验，不覆盖已有结果）
  python scripts/llm_phase_a.py --case-dir "input/北京 盈科中心-5" \
      --out "input/北京 盈科中心-5/llm_understanding.deepseek.json"

  # 仅打印请求信息，不真正调用（调试用）
  python scripts/llm_phase_a.py --case-dir "..." --dry-run
"""

import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "config" / "deepseek.json"
PROMPT_TEMPLATE = SKILL_ROOT / "references" / "llm_prompt_template.md"

PLAN_NAMES = ["plan.png", "plan.jpg", "plan.jpeg"]
PHOTO_GLOBS = ["photo_*.jpg", "photo_*.jpeg", "photo_*.png", "photo_*.JPG", "photo_*.PNG"]


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[错误] 配置文件不存在：{path}\n请参照 config/deepseek.example.json 创建。")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_case_images(case_dir: Path):
    """在案例目录中定位平面图和透视照。"""
    plan = None
    for name in PLAN_NAMES:
        p = case_dir / name
        if p.exists():
            plan = p
            break
    if plan is None:
        for pat in ("plan.*", "*plan*.png", "*平面*"):
            hits = sorted(case_dir.glob(pat))
            if hits:
                plan = hits[0]
                break

    photos = []
    for pat in PHOTO_GLOBS:
        photos.extend(case_dir.glob(pat))
    photos = sorted(set(photos))

    return plan, photos


def encode_image(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_messages(prompt: str, plan: Path, photos: list, case_name: str, detail: str):
    """构建多模态消息：完整指令文本在前，图片集中附加在后。

    注意：deepseek-v4-flash-vision-exp 是推理型视觉模型，实测中
    “文本-图片交错排列”会让其推理过程误判为未收到图片，
    因此所有图片统一附在文本之后，不插入分隔性文本块。
    """
    image_list = []
    if plan is not None:
        image_list.append(f"  - 第1张：平面图 {plan.name}（可能为手绘草图，请按平面图识别规范解读）")
    for i, ph in enumerate(photos, start=1):
        image_list.append(f"  - 第{len(image_list) + 1}张：现场透视照 {ph.name}")

    text = (
        f"请对共享办公空间案例「{case_name}」进行空间理解分析。\n\n"
        f"以下 {len(image_list)} 张图片已成功附加在本条消息末尾，你能够直接看到它们，"
        "请务必逐张仔细观察后再作答：\n"
        + "\n".join(image_list)
        + f"\n\n{prompt}\n\n"
        "请同时结合平面图与全部透视照，严格按照上述 JSON Schema 输出，"
        "只输出 JSON 本体，不要输出任何其他文字或解释。"
    )
    content = [{"type": "text", "text": text}]
    if plan is not None:
        content.append({
            "type": "image_url",
            "image_url": {"url": encode_image(plan), "detail": detail},
        })
    for ph in photos:
        content.append({
            "type": "image_url",
            "image_url": {"url": encode_image(ph), "detail": detail},
        })
    return [{"role": "user", "content": content}]


def call_api(cfg: dict, messages: list, stream: bool = False):
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.2),
        "max_tokens": cfg.get("max_tokens", 8192),
        "stream": stream,
    }
    # 推理控制：实验版思维模型默认会消耗大量 token 思考，可关闭以快速得到完整 JSON
    if cfg.get("thinking_disabled"):
        body["thinking"] = {"type": "disabled"}
    if cfg.get("reasoning_effort"):
        body["reasoning_effort"] = cfg["reasoning_effort"]
    if stream:
        return call_api_stream(url, headers, body, cfg.get("timeout_s", 600))
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=cfg.get("timeout_s", 600)) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_api_stream(url, headers, body, timeout):
    """SSE 流式调用，逐块拼接 content，用于长输出的实时观察。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    collected = []
    reasoning = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
            if delta.get("content"):
                collected.append(delta["content"])
                sys.stdout.write(delta["content"])
                sys.stdout.flush()
    sys.stdout.write("\n")
    return {
        "choices": [{
            "message": {
                "content": "".join(collected),
                "reasoning_content": "".join(reasoning),
            }
        }]
    }


def extract_json(text: str) -> dict:
    """从模型回复中提取 JSON（容忍 markdown 代码块、前后杂文字）。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 围栏
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型回复中未找到 JSON 对象")
    return json.loads(text[start:end + 1])


def api_call_with_retry(cfg, messages, stream=False):
    retries = cfg.get("max_retries", 3)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return call_api(cfg, messages, stream=stream)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            last_err = f"HTTP {e.code}: {body}"
            # 4xx 客户端错误（除429限流）重试无意义
            if 400 <= e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = str(e)
        print(f"[重试 {attempt}/{retries}] {last_err}", file=sys.stderr)
        time.sleep(3 * attempt)
    sys.exit(f"[错误] API 调用失败：{last_err}")


def is_degenerate(data: dict, raw_content: str) -> bool:
    """检测模型是否声称未收到图片（视觉输入失效的典型表现）。"""
    signals = ["未能", "无法访问", "未获得图像", "看不到", "没有收到图片", "未提供图片", "无法查看"]
    meta_note = json.dumps(data.get("_meta", {}), ensure_ascii=False)
    if any(s in meta_note or s in raw_content[:800] for s in signals):
        scale = data.get("空间绝对尺度", {})
        # 只有当关键视觉字段也全部失效时才判定退化
        if all(v in (-1, None) for v in scale.values() if isinstance(v, (int, float))):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description="阶段A：DeepSeek 视觉模型空间理解")
    ap.add_argument("--case-dir", help="案例目录（含 plan.png 与 photo_*.jpg）")
    ap.add_argument("--name", help="案例名称（默认取目录名）")
    ap.add_argument("--out", help="输出 JSON 路径（默认：<case-dir>/llm_understanding.json）")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="API 配置文件路径")
    ap.add_argument("--ping", action="store_true", help="连通性测试（纯文本）")
    ap.add_argument("--stream", action="store_true", help="流式输出（实时看到模型回复）")
    ap.add_argument("--dry-run", action="store_true", help="只构建请求并打印摘要，不调用 API")
    args = ap.parse_args()

    cfg = load_config(args.config)
    print(f"[配置] 模型: {cfg['model']} @ {cfg['base_url']}")

    if args.ping:
        messages = [{"role": "user", "content": "回复两个字：连通"}]
        t0 = time.time()
        resp = api_call_with_retry(cfg, messages)
        content = resp["choices"][0]["message"].get("content", "")
        print(f"[Ping 成功] {time.time() - t0:.1f}s 回复: {content!r}")
        usage = resp.get("usage", {})
        print(f"[用量] {usage}")
        return

    if not args.case_dir:
        ap.error("需要 --case-dir（或 --ping）")
    case_dir = Path(args.case_dir).resolve()
    if not case_dir.is_dir():
        sys.exit(f"[错误] 案例目录不存在：{case_dir}")

    plan, photos = find_case_images(case_dir)
    case_name = args.name or case_dir.name
    print(f"[案例] {case_name}")
    print(f"[平面图] {plan.name if plan else '未找到（将仅基于照片分析）'}")
    print(f"[透视照] {len(photos)} 张: {[p.name for p in photos]}")

    prompt = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    messages = build_messages(prompt, plan, photos, case_name,
                              cfg.get("image_detail", "high"))

    if args.dry_run:
        n_img = (1 if plan else 0) + len(photos)
        print(f"[Dry-run] 消息数={len(messages)} 图片数={n_img} "
              f"prompt长度={len(prompt)}字符 — 未调用 API")
        return

    print(f"[请求] 发送中（{cfg.get('max_tokens', 8192)} max_tokens, "
          f"detail={cfg.get('image_detail', 'high')}）...")
    t0 = time.time()
    resp = api_call_with_retry(cfg, messages, stream=args.stream)
    elapsed = time.time() - t0

    msg = resp["choices"][0]["message"]
    content = msg.get("content", "") or ""
    usage = resp.get("usage", {})
    print(f"[完成] {elapsed:.1f}s | tokens: "
          f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
          f"(reasoning={usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)})")

    try:
        data = extract_json(content)
    except (ValueError, json.JSONDecodeError) as e:
        err_out = case_dir / "llm_raw_response.txt"
        err_out.write_text(content, encoding="utf-8")
        sys.exit(f"[错误] JSON 解析失败：{e}\n原始回复已存至 {err_out}")

    # 退化输出检测：模型声称看不到图片 → 视觉输入未被其推理利用，自动重试一次
    if is_degenerate(data, content):
        print("[警告] 模型声称未收到图片（退化输出），加强指令后重试一次...", file=sys.stderr)
        retry_text = messages[0]["content"][0]["text"] + (
            "\n\n【重要】图片数据确实已随本消息附上（你在消息末尾可以直接看到它们）。"
            "请先在推理中逐一描述每张图片的内容，确认你已看到，然后再输出 JSON。"
            "绝对不要因为‘认为’自己看不到图片而将字段填为 -1。"
        )
        messages[0]["content"][0]["text"] = retry_text
        t0 = time.time()
        resp = api_call_with_retry(cfg, messages, stream=args.stream)
        elapsed = time.time() - t0
        msg = resp["choices"][0]["message"]
        content = msg.get("content", "") or ""
        usage = resp.get("usage", {})
        print(f"[重试完成] {elapsed:.1f}s | tokens: "
              f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
        try:
            data = extract_json(content)
        except (ValueError, json.JSONDecodeError) as e:
            err_out = case_dir / "llm_raw_response.txt"
            err_out.write_text(content, encoding="utf-8")
            sys.exit(f"[错误] 重试后 JSON 解析仍失败：{e}\n原始回复已存至 {err_out}")

    out_path = Path(args.out) if args.out else case_dir / "llm_understanding.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[保存] {out_path}")

    # 关键字段摘要
    scale = data.get("空间绝对尺度", {})
    env = data.get("围护结构", {})
    cal = data.get("_meta", {}).get("scale_calibration", {})
    print(f"[摘要] 尺寸 {scale.get('length_m')}m × {scale.get('width_m')}m, "
          f"面积 {scale.get('net_floor_area_m2')}m², "
          f"围合度 {env.get('enclosure_ratio')}, "
          f"标定物 {cal.get('reference_object')}")


if __name__ == "__main__":
    main()
