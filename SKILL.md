---
name: space-feature-extractor
description: >
  共享办公空间特征提取工具。输入平面图+透视照，输出56个标准化空间特征（JSON/CSV）及可视化图片。
  分两阶段：阶段A由LLM看图生成结构化空间数据（尺度/围护/家具/色彩/光/感知），
  阶段B由本地CV管线（OpenCV+Mask2Former）补充像素级分析。
  当用户提到"分析空间"、"提取空间特征"、"跑空间分析"、"空间特征提取"、"批量分析案例"、
  "共享办公分析"、"空间数据采集"、"space analysis"、"空间分析管线"时使用。
  也适用于用户给出平面图/透视照并说"帮我分析这个空间"、"提取这个空间的数据"的场景。
---

# 共享办公空间特征提取管线

## 概述

本 skill 用于从共享办公空间的平面图和透视照中提取 56 个标准化特征维度，包含真实物理单位（米、平方米、K、lux、RAL 色号等）。整个流程分两个阶段自动执行。

## 前置条件

运行阶段 B 需要以下 Python 依赖（仅首次需安装）：

```bash
pip3 install opencv-python-headless torch torchvision transformers numpy Pillow
```

Mask2Former 模型首次运行会自动下载（约200MB），后续使用缓存。支持 Apple Silicon MPS 加速。

## 工作流程

### Step 0: 确认输入

确认用户提供了以下输入：
- **平面图**：1 张俯视平面图或 CAD 草图（jpg/png）
- **透视照**：至少 1 张人视角室内照片（jpg/png）
- **工作空间路径**：input/output 的根目录（默认当前工作目录）
- **案例名称**：如"案例01_WeWork"

如果用户要批量处理，确认 input 文件夹路径，里面应该已按 `案例XX_名称/` 组织好子文件夹，每个子文件夹包含 `plan.*` 和 `photo_*.*`。

### Step 1: 组织目录结构

所有数据统一存放在 skill 目录下的 `input/` 和 `output/` 中，便于整体迁移：

```
~/.catpaw/skills/space-feature-extractor/
├── input/                          ← 所有案例的输入素材
│   └── {案例名称}/
│       ├── plan.jpg                ← 平面图（必须）
│       ├── photo_01.png            ← 透视照（必须，可多张）
│       └── llm_understanding.json  ← 阶段A产出（Step 2 生成）
├── output/                         ← 所有案例的分析产出（自动创建）
│   └── {案例名称}/
├── scripts/
├── references/
└── SKILL.md
```

如果用户给的图片不在标准目录下，帮他们复制/移动到 `input/{案例名称}/` 下并按规范重命名。

可参考已有的示例案例 `input/案例01_WeWork/` 了解文件命名规范。

### Step 2: 阶段 A — LLM 多模态空间理解

**这一步由你（LLM）自己完成。** 读取 `references/llm_prompt_template.md` 获取完整的 prompt 模板和 JSON Schema。

核心流程：
1. 读取平面图和透视照（用视觉能力看图）
2. 按 prompt 模板中的 JSON Schema 结构化输出空间数据
3. 关键技术：**家具标定法** — 识别图中标准尺寸家具（如单人椅约0.72m），测量像素，反推 px-to-meter 比例，再推算空间真实尺寸
4. 将输出保存为 `input/{案例名称}/llm_understanding.json`（与原始图片放在一起，供阶段 B 读取）

产出 38 个 LLM 来源特征（空间尺度、围护、比例、家具、色彩材质、光环境、感知评分）。

### Step 3: 阶段 B — 本地 CV 管线

调用 `scripts/space_analyzer.py` 自动完成：

```bash
SKILL="~/.catpaw/skills/space-feature-extractor"

python3 $SKILL/scripts/space_analyzer.py \
  --plan "$SKILL/input/{案例名称}/plan.jpg" \
  --photos "$SKILL/input/{案例名称}/photo_01.png" \
  --llm-json "$SKILL/input/{案例名称}/llm_understanding.json" \
  --name "{案例名称}" \
  --out "$SKILL/output/{案例名称}"
```

加 `--report` 可额外生成 HTML 报告。

该脚本会：
- OpenCV 分析平面图 → 5 个几何形状指标 + `plan_binary.png`
- Mask2Former 分析透视照 → 8 个语义面积占比 + `seg_semantic.png` + `seg_overlay.png`
- OpenCV 分析透视照 → 6 个感知指标
- 合并所有特征 → `features.json` + `features.csv`

### Step 4: 确认产出

检查 `output/{案例名称}/` 下产出完整：

| 文件 | 说明 |
|------|------|
| `features.json` | 56 个特征（核心） |
| `features.csv` | 同样数据的表格版 |
| `input/{案例}/llm_understanding.json` | 阶段 A 的 LLM 理解原始数据（存在 input 侧） |
| `plan_binary.png` | 平面图二值化 |
| `seg_semantic.png` | 语义分割纯色图 |
| `seg_overlay.png` | 语义分割叠加图 |

向用户汇报特征数量和关键数值（面积、座位数、主色调等），确认数据合理。

## 批量处理

当用户要批量处理时：

```bash
SKILL="~/.catpaw/skills/space-feature-extractor"

python3 $SKILL/scripts/batch_analyze.py \
  --input-dir "$SKILL/input" \
  --output-dir "$SKILL/output"
```

只跑单个案例：加 `--case 案例01_WeWork`

该脚本遍历 `input/` 下所有子文件夹，依次执行阶段 B。阶段 A 需要 LLM 看图，批量模式下每个案例的 `llm_understanding.json` 需要提前生成好（可以逐个跑，也可以让用户分批喂图）。

## 字段参考

完整的 56 个字段的中英文对照表和基准值说明，见 `references/feature_dictionary.json`。

## 注意事项

- 家具标定法精度约 ±10%，需要至少用 2 个不同家具交叉验证
- Mask2Former 使用 ADE20K 150 类语义，合并为 8 组；识别精度受图片清晰度和拍摄角度影响
- 色温的 LLM 判读值和 CV 计算值可能有差异（LLM 综合理解 vs CV 纯像素），两个都保留供对比
- 建议透视照拍摄时覆盖空间全貌，避免局部特写
