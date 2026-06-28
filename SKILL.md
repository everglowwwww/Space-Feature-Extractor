---
name: space-feature-extractor
description: >
  共享办公空间特征提取工具。输入平面图+透视照+DXF文件，输出56个标准化空间特征（JSON/CSV）及可视化图片。
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
pip3 install opencv-python-headless torch torchvision transformers numpy Pillow ezdxf
```

Mask2Former 模型首次运行会自动下载（约200MB），后续使用缓存。支持 Apple Silicon MPS 加速。

**重要**：运行阶段 B 时请添加环境变量 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，避免 HuggingFace 联网检查导致超时等待（可将运行时间从 ~17 分钟缩短至 ~4 分钟）。

## 工作流程

### Step 0: 确认输入素材

当用户触发本 skill 时，**首先向用户确认并引导准备以下输入素材**：

> 为了完成空间特征提取，我需要你提供以下素材：
>
> **必须提供（缺一不可）：**
> 1. **平面图 PNG/JPG** — 标准化的俯视平面图（白底黑线，包含家具布局）
> 2. **人视角照片** — 至少 1 张室内透视照片（建议 2 张不同角度，覆盖更多空间信息）
>
> **强烈推荐（显著提升精度）：**
> 3. **DXF 文件** — 从 CAD 软件导出的 DXF 格式图纸（提供精确尺寸，误差±0；若无 DXF 则退回"家具标定法"估算，精度约±10-20%）
>
> **其他信息：**
> 4. **案例名称** — 如"北京 盈科中心-5"
>
> ⚠️ 注意：仅支持 DXF 格式的 CAD 文件，不支持 DWG（二进制私有格式）。如果你只有 DWG 文件，请在 CAD 软件中"另存为 → DXF"格式导出。

等用户提供素材后再继续后续步骤。如果用户只提供了部分素材，明确告知哪些是缺少的以及影响。

### Step 1: 组织目录结构

所有数据统一存放在 skill 目录下的 `input/` 和 `output/` 中，便于整体迁移：

```
~/.catpaw/skills/space-feature-extractor/
├── input/                          ← 所有案例的输入素材
│   └── {案例名称}/
│       ├── plan.png                ← 平面图（必须）
│       ├── photo_01.jpg            ← 人视角照片 1（必须）
│       ├── photo_02.jpg            ← 人视角照片 2（推荐）
│       ├── xxx.dxf                 ← DXF 图纸（推荐，精确尺度来源）
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
2. **如果有 DXF 文件**：用 `ezdxf` 库解析 DXF，提取精确几何尺寸（空间长宽、家具尺寸、围合度等），作为尺度数据的权威来源；LLM 视觉分析仅负责语义数据（色彩、材质、光环境、感知评分）
3. **如果没有 DXF 文件**：使用**家具标定法** — 识别图中标准尺寸家具（如单人椅约0.45m），测量像素，反推 px-to-meter 比例，再推算空间真实尺寸（精度约±10-20%）
4. 按 prompt 模板中的 JSON Schema 结构化输出空间数据
5. 将输出保存为 `input/{案例名称}/llm_understanding.json`（与原始图片放在一起，供阶段 B 读取）

DXF 解析要点：
- 使用 `ezdxf` 库读取，注意检查 `$INSUNITS` 确定单位（6=米）
- 关注图层名称（如"墙体""桌子""椅子""柜子""虚线"等）来分类几何体
- 围合度 = 墙体层总长 / 空间总周长
- 在 `llm_understanding.json` 的 `_meta.source` 中标明数据来源（DXF 精确解析 vs 家具标定法）

产出 38 个 LLM 来源特征（空间尺度、围护、比例、家具、色彩材质、光环境、感知评分）。

### Step 3: 阶段 B — 本地 CV 管线

调用 `scripts/space_analyzer.py` 自动完成：

```bash
SKILL="~/.catpaw/skills/space-feature-extractor"

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python3 $SKILL/scripts/space_analyzer.py \
  --plan "$SKILL/input/{案例名称}/plan.png" \
  --photos "$SKILL/input/{案例名称}/photo_01.jpg" "$SKILL/input/{案例名称}/photo_02.jpg" \
  --llm-json "$SKILL/input/{案例名称}/llm_understanding.json" \
  --name "{案例名称}" \
  --out "$SKILL/output/{案例名称}"
```

加 `--report` 可额外生成 HTML 报告。

该脚本会：
- OpenCV 分析平面图 → 5 个几何形状指标 + `plan_binary.png`
- Mask2Former 分析透视照 → 8 个语义面积占比 + 分割可视化（带图例标注的叠加图）
- OpenCV 分析透视照 → 6 个感知指标
- 合并所有特征 → `features.json` + `features_cn.json` + `features.csv`

### Step 4: 确认产出

检查 `output/{案例名称}/` 下产出完整：

| 文件 | 说明 |
|------|------|
| `features.json` | 56 个特征，英文 key（核心，程序读取） |
| `features_cn.json` | 56 个特征，中文 key + 单位（人类阅读） |
| `features.csv` | 同样数据的表格版（Excel 友好） |
| `plan_binary.png` | 平面图二值化（白底黑线） |
| `seg_semantic_01.png` | 人视角 1 语义分割纯色图 |
| `seg_overlay_01.png` | 人视角 1 语义分割叠加图（带图例标注） |
| `seg_semantic_02.png` | 人视角 2 语义分割纯色图（如有第二张照片） |
| `seg_overlay_02.png` | 人视角 2 语义分割叠加图（带图例标注） |

**输入侧保留：**

| 文件 | 说明 |
|------|------|
| `input/{案例}/llm_understanding.json` | 阶段 A 的 LLM 理解原始数据 |

向用户汇报特征数量和关键数值（面积、座位数、围合度、主色调等），确认数据合理。

## 批量处理

当用户要批量处理时：

```bash
SKILL="~/.catpaw/skills/space-feature-extractor"

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir "$SKILL/input" \
  --output-dir "$SKILL/output"
```

只跑单个案例：加 `--case 案例01_WeWork`

该脚本遍历 `input/` 下所有子文件夹，依次执行阶段 B。阶段 A 需要 LLM 看图，批量模式下每个案例的 `llm_understanding.json` 需要提前生成好（可以逐个跑，也可以让用户分批喂图）。

## 字段参考

完整的 56 个字段的中英文对照表和基准值说明，见 `references/feature_dictionary.json`。

## 注意事项

- **DXF vs 家具标定法**：DXF 精确解析误差±0，家具标定法约±10-20%。强烈建议提供 DXF 文件
- **DWG 不可用**：仅支持 DXF 格式。DWG 是 Autodesk 私有二进制格式，macOS 上无可靠的开源解析工具。用户需在 CAD 软件中"另存为 → DXF"
- **HuggingFace 离线模式**：运行时务必设置 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，否则模型加载会尝试联网检查更新，在网络不通时会卡在超时等待上（可能多等 10+ 分钟）
- **平面图格式**：应为标准化白底黑线工程图，脚本会自动检测底色方向并正确处理
- Mask2Former 使用 ADE20K 150 类语义，合并为 8 组；识别精度受图片清晰度和拍摄角度影响
- 色温的 LLM 判读值和 CV 计算值可能有差异（LLM 综合理解 vs CV 纯像素），两个都保留供对比
- 建议透视照从两个不同角度拍摄，覆盖空间全貌，避免局部特写
