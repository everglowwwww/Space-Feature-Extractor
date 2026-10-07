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

# 共享办公空间特征提取管线（Space-Feature-Extractor）

## 一、定位

从共享办公空间的**平面图 + 人视角照片 + DXF** 提取 **56 个标准化特征**（含真实物理单位：米/㎡/K/lux/RAL 色号），并生成可视化图片。流程分两阶段：

- **阶段 A（语义 + 几何）**：LLM 看图提供语义（色彩/材质/光/感知）；DXF 提供权威几何（长宽/净面积/围合度/家具）。
- **阶段 B（像素级 CV）**：OpenCV + Mask2Former 补充平面几何、语义面积占比、画面感知指标。

> 本技能是一个**可复现、增量、幂等**的标准化流程。日常以 `run_pipeline.py` 为单一入口。

## 二、目录结构（所有路径相对 `$SKILL_DIR` 解析）

`$SKILL_DIR` = 本 skill 所在目录（含以下子内容），不写死机器绝对路径。

```
$SKILL_DIR/
├── input/{项目}/{单元}/        ← 纯人工素材
│   ├── plan.png              平面图
│   ├── photo_01.jpg ...      人视角照片（按序）
│   └── unit.dxf              CAD 图纸（DXF）
├── output/{项目}/{单元}/       ← 全部生成内容（镜像 input）
│   ├── llm_understanding.json  阶段A产物
│   ├── features.json / features_cn.json / features.csv
│   └── plan_binary.png / seg_semantic_0N.png / seg_overlay_0N.png
├── scripts/                    ← 全部脚本（见下）
├── references/                 ← 特征字典 / 命名规范 / prompt 模板
├── manifest.csv                ← ★ 唯一管理文件：单元清单 + 已/未处理状态（自动更新）
└── SKILL.md
```

> 说明：`input_rename_map.csv`（input 侧改名映射）是**派生工具产物**，重命名完成后归档到 `_legacy/`；以后新增单元时由 `gen_manifest.py` 自动重新生成，不作为管理文件。

**命名规则**：项目夹 `{序号}-{项目中文名}`（如 `1-北京盈科中心`）；单元夹 `{项目中文名}-{NN}`（如 `北京盈科中心-01`）；全路径**无空格**。详见 `references/目录结构与命名规范.md`。

## 三、脚本清单

| 脚本 | 作用 | 依赖 |
|------|------|------|
| `scripts/run_pipeline.py` | **统一增量编排入口**（推荐，日常只用它） | 调下面三个 |
| `scripts/llm_phase_a.py` | 阶段A-视觉：DeepSeek 看图 → JSON | 仅标准库 |
| `scripts/dxf_parser.py` | 阶段A-几何：DXF 精确尺度 + 净面积 + 围合度 | ezdxf（+numpy/cv2 可选） |
| `scripts/space_analyzer.py` | 阶段B：OpenCV + Mask2Former → 56 特征 + 图 | cv2/torch/transformers |
| `scripts/gen_manifest.py` | 扫 input → 更新 manifest.csv + input_rename_map.csv | 标准库 |
| `scripts/apply_restructure.py` | 改名/标准化/建占位/建 output 骨架/归档（幂等） | 标准库 |
| `scripts/cluster_spaces.py` | **聚类 → 典型原型**（M7，mode 可插拔：shell/furnishing/function/style） | sklearn + matplotlib + pandas |
| `scripts/make_cluster_report.py` | 聚类汇报 + 高级可视化（读 cluster_summary.json） | matplotlib |
| `scripts/git_sync.py` | **一键提交并同步到 GitHub**（含数据强制入库 + 密钥安全检查） | git |
| `scripts/batch_analyze.py` | 一次性全量跑阶段B（旧方式，次要） | 同 space_analyzer |

## 三-b、聚类与原型提取（M7）

把 30 个空间单元按不同特征子集聚类，提取典型原型。脚本 `cluster_spaces.py` 可复用、mode 可插拔，方法一致（标准化/One-Hot → K-means + Ward → 轮廓系数定 k → 簇心 + 归属 + 可视化 + CSV）。

```bash
python scripts/cluster_spaces.py --mode shell      # 空间原型（壳子，默认 k=3）
python scripts/cluster_spaces.py --mode furnishing # 陈设配置（密度/复杂度，自动 k）
python scripts/cluster_spaces.py --mode function   # 功能类型（语义占比，自动 k）
python scripts/cluster_spaces.py --mode style      # 视觉风格（含文本 One-Hot，自动 k）
python scripts/cluster_spaces.py --mode <m> --k 4  # 指定 k
python scripts/cluster_spaces.py --mode <m> --out output/cluster
```

- **输入子集**：`shell`=壳子5字段；`furnishing`=家具密度/座位密度/座位数+语义构成(座/台/储/植/照)+主色占比；`function`=语义功能占比+家具密度；`style`=色彩/材质/光/感知(数值+文本One-Hot)。
- **方法**：K-means（+ Ward 层次对照）；`--k` 优先，否则模式默认 k，否则轮廓系数选优（30 样本 k 上限 5）。
- **输出**（`output/cluster/{mode}/`）：`prototypes.csv`（簇心）、`cluster_assignments.csv`（归属+备注=单例异常）、`pca_scatter.png`、`centroid_radar.png`、`silhouette_vs_k.png`、`dendrogram.png`。
- **四类聚类结果**（均为过程性文件，供汇报/建模）：
  | 聚类 | k | 轮廓系数 | 结构 | 结果 |
  |------|:--:|:--:|:--:|------|
  | shell 空间原型 | 3 | **0.47** | 强 | 小型封闭(17)/大型开放(12)/狭长(1异常=盈科中心-08) |
  | furnishing 陈设配置 | 4 | 0.16 | 弱 | （修复数据前曾被 15.47 假值拉到 0.50，实为弱结构）|
  | function 功能类型 | 4 | 0.21 | 弱 | 办公主导，趋同 |
  | style 视觉风格 | 3 | 0.17 | 弱 | 趋同 |
- **关键结论**：仅**壳子维度**结构强（0.47）；**陈设配置/功能/风格**都弱（0.16-0.21）——30 个共享办公样本在这些维度上**高度同质**（都是办公/会议导向，陈设/风格相近）。这是样本集的真实特征（可作"样本同质"发现，或提示实验需人为制造陈设多样性）。
- **数据口径**：净面积=内圈孔洞多边形（排除凹口/墙厚），围合度=墙/(墙+虚线) 恒 0-1；异常单元（净面积<家具占地）自动退回到外包矩形并标记 `bbox`。
- **异常标注**：单例簇自动标 `异常(单例)`（如盈科中心-08、望京03 等）。
- **复用扩展**：在脚本 `MODES` 加新 mode 即可复用同一套聚类/可视化逻辑。

## 四、环境与路径（通用 + 本机）

### 通用（任何机器都要）
- Python 3.10~3.12；依赖：`ezdxf numpy opencv-python-headless torch torchvision transformers Pillow`（+可选 `shapely`）。
- **阶段 B 必须设**离线变量，否则 HuggingFace 联网检查会卡十几分钟：
  ```
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  ```
- **Mask2Former 模型路径**：用 `M2F_MODEL_DIR` 指向本地缓存（`facebook/mask2former-swin-tiny-ade-semantic`），避免联网下载。
- **中文路径坑（重要）**：`cv2.imread` / `cv2.imwrite` 对含中文路径会静默失败。本项目用 `_imread_unicode()`（读）与 `_imwrite_unicode()`（写）替代；**新增图像 I/O 请复用这两个函数**。本项目目录全为中文，务必遵守。
- 环境变量在 PowerShell 用 `$env:VAR="1"`，bash 用 `export VAR=1`。

### 本机（Windows / E:\毕业论文）备注
- venv：`E:\毕业论文\.venv`（Python 3.12.10，含 torch cu128 / RTX 5060 / shapely）。
- 阶段B模型缓存：`E:\毕业论文\.venv\hf_cache\model_download`。
- 阶段A API：`config/deepseek.json`（`deepseek-v4-flash-vision-exp`，`max_tokens=16384`，`thinking_disabled=true`）。
- 运行示例（PowerShell）：
  ```powershell
  $env:HF_HUB_OFFLINE="1"; $env:TRANSFORMERS_OFFLINE="1"; $env:M2F_MODEL_DIR="E:\毕业论文\.venv\hf_cache\model_download"
  & "E:\毕业论文\.venv\Scripts\python.exe" scripts\run_pipeline.py --dry-run
  ```

## 五、启动流程（交互预览，每次触发都走这套）

**规范的首次交互**——自动检测状态，先给用户概览，经确认再动手：

1. **打印引导词**：如「空间特征提取管线启动，正在检测 input 下所有空间单元的处理状态…」。
2. **运行概览**（只读、不执行）：
   ```bash
   python scripts/run_pipeline.py --dry-run
   ```
   它会输出：全体单元状态表（`阶段A=√/× 阶段B=√/× → 需阶段A/阶段B/已完成`）+ **聚合汇总**（共 N 单元，A 完成 X/B 完成 Y，各阶段缺口）。
3. **呈现给用户**：以上述表格 + 汇总的形式展示"哪些已处理、哪些未处理"。
4. **询问确认**：是否开始处理未完成内容？默认只处理新增/缺漏（增量幂等）。
   - 也可直接用 `--interactive` 让管道自己暂停询问：
     ```bash
     python scripts/run_pipeline.py --interactive
     ```
5. **执行**：确认后运行 `run_pipeline.py`（默认 all，或 `--phase a` / `--phase b` / `--unit {项目}/{单元}`）。完成后向用户汇报特征数量与关键数值。

## 六、标准执行流程（run_pipeline.py 为主线）

```bash
python scripts/run_pipeline.py --dry-run         # 概览（状态表 + 汇总）
python scripts/run_pipeline.py --phase a          # 只补跑缺阶段A的单元
python scripts/run_pipeline.py --phase b          # 只补跑已有阶段A、缺阶段B的单元
python scripts/run_pipeline.py                     # all：缺什么补什么（默认）
python scripts/run_pipeline.py --interactive      # 概览后暂停询问再执行
python scripts/run_pipeline.py --unit 1-北京盈科中心/北京盈科中心-05   # 指定单元
python scripts/run_pipeline.py --force            # 忽略已完成，强制重跑
python scripts/run_pipeline.py --report           # 阶段B额外生成 HTML 报告
```

管道自动：扫 `input/{项目}/{单元}` → 检查 `output/.../llm_understanding.json`（阶段A）与 `features.json`（阶段B）是否存在 → 缺则调对应脚本补跑 → 写结果到 `output/{项目}/{单元}/` → 回写 `manifest.csv` 状态。**重复运行只处理新增，流程恒定。**

### 两个阶段到底做什么（供理解，不用手动跑）
- **阶段 A** = `llm_phase_a.py`（DeepSeek 看图 → 38 语义特征）+ `dxf_parser.py`（DXF 精确几何：长宽/净面积/围合度/家具，覆盖进 JSON）。
- **阶段 B** = `space_analyzer.py`（OpenCV 平面几何 5 特征 + Mask2Former 8 语义面积 + OpenCV 感知 6 特征，共 56 特征）。

## 七、数据管理（新增单元 / 状态追踪）

- **input 只放人工素材**；**output 放全部生成内容**，两者严格镜像。
- **`manifest.csv` 是唯一管理文件**：记录每单元 `状态(待分析/阶段A完成/阶段B完成)`。`run_pipeline.py` 每次跑完**自动回写**状态；`gen_manifest.py` 重跑时**保留已有状态**（不会重置）。
- 状态语义：`待分析`=未处理；`阶段A完成`=语义+几何就绪；`阶段B完成`=全流程完成（数据就绪）。
- `input_rename_map.csv` 为派生工具产物（重命名阶段用，已归档；新增单元时由 `gen_manifest.py` 重生成）。
- **新增单元素材三步**（幂等、可反复）：
  ```bash
  python scripts/gen_manifest.py       # ① 扫 input，更新 manifest（保留状态）+ 重生成改名映射
  python scripts/apply_restructure.py  # ② 标准化命名 + 补 output 骨架（可 --dry-run 预览）
  python scripts/run_pipeline.py       # ③ 增量分析新增
  ```

## 七-b、版本管理（同步到 GitHub）

仓库：`https://github.com/everglowwwww/Space-Feature-Extractor.git`（本 skill 目录即 git 仓库根）。

```bash
python scripts/git_sync.py --dry-run                 # 先看将要提交什么（只预览）
python scripts/git_sync.py -m "说明" --push           # 提交并推送（推荐）
python scripts/git_sync.py -m "说明" --push --no-data # 只提交代码/文档，不含数据
```

- **自动处理数据**：`input/`、`output/` 在 `.gitignore` 中被忽略，本脚本会自动 `git add -f input output` 强制入库——**不必手动记这一步**。
- **安全检查**：`config/deepseek.json`（API 密钥）与 `_restore_backup/`（冗余备份）若被误暂存，脚本会**中止并不提交**。
- 提交前会打印 `新增/修改/删除/重命名` 统计；推送后打印 `领先/落后`（`0 0`=完全同步）。
- 说明：`_legacy/`（旧示例归档）与 `manifest.csv`、汇报产物会一并入库；`_restore_backup/` 不入库。

## 八、字段参考

- 完整字段总表（按分析维度分组，含单位/来源/所属聚类维度，**重点**）：`references/特征字段总表.md`
- 中英文对照与基准值：`references/feature_dictionary.json`。
- 命名/目录规范：`references/目录结构与命名规范.md`。阶段A prompt 模板：`references/llm_prompt_template.md`。

## 九、注意事项

- **DXF vs 家具标定法**：DXF 精确（净面积经"内圈孔洞多边形"排除凹口/墙厚，围合度基于 墙/(墙+虚线) 恒 0-1）；无 DXF 时 LLM 目测误差 ±10-20%。
- **净面积口径**：采用"围合墙体面域"（排除 L 形凹口），见 `dxf_parser.compute_enclosed_area`；`_meta.area_method` 标记 `enclosed`/`outer`（开放空间兜底）。
- **围合度口径**：`wall_len/(wall_len+虚线_len)`，恒 ∈[0,1]。
- **DWG 不支持**：仅 DXF（CAD 中"另存为 DXF"）。
- **HuggingFace 离线**：阶段B前务必设 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。
- **推荐**不同角度多张透视照，覆盖空间全貌；平面图应为白底黑线标准工程图。
