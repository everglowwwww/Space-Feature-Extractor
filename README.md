# Space Feature Extractor — 共享办公空间特征提取与聚类分析

> 硕士论文《共享办公型室内空间陈设的脑认知与智能交互研究》的数据采集与分析工具
>
> **输入**：平面图 + 人视角透视照 + DXF → **输出**：56 个标准化空间特征（真实物理单位）+ 典型原型聚类

---

## 它能做什么

对共享办公空间单元做两件事：

1. **特征提取**：从「平面图 + 透视照 + DXF」自动提取 **56 个量化特征**——空间尺度（米）、围护结构、家具配置、色彩材质（HEX/RAL）、光环境（lux/K）、空间感知，以及 CV 几何形态与语义构成。输出 JSON + CSV + 可视化图。
2. **聚类分析**：把多个空间单元按不同维度聚类，提取**典型原型**（4 个方向：空间原型/陈设配置/功能类型/视觉风格），输出原型表 + 高级可视化 + 汇报文档。

处理流程分三部分：

- **阶段 A（语义 + 几何）**：多模态大模型看图提供语义（色彩/材质/光/感知）；**DXF 提供权威几何**（长宽/净面积/围合度/家具，误差 ±0）
- **阶段 B（本地 CV）**：OpenCV 平面几何 + Mask2Former 语义分割 + OpenCV 感知指标
- **聚类分析**：K-means（+Ward 对照）按维度子集聚类 → 典型原型 + 轮廓系数 + 可视化

> 当前数据集：**30 个空间单元**（北京 6 个项目：盈科中心/国航世纪/望京国际中心/慈云寺/互联网金融中心/三里屯），全部完成特征提取。

---

## 目录结构

```
space-feature-extractor/
├── README.md                     ← 👈 本文件，项目总览
├── SKILL.md                      ← Skill 入口（AI 助手读它执行工作流）
├── manifest.csv                  ← ★ 唯一管理文件：单元清单 + 已/未处理状态
│
├── input/{项目}/{单元}/           ← 纯人工素材
│   ├── plan.png                 平面图
│   ├── photo_01.jpg ...         人视角照片
│   └── unit.dxf                 CAD 图纸（DXF）
│
├── output/{项目}/{单元}/          ← 全部生成内容（镜像 input）
│   ├── llm_understanding.json   阶段A产物（语义 + DXF 几何）
│   ├── features.json / _cn.json / .csv   56 特征
│   └── plan_binary.png / seg_semantic_0N.png / seg_overlay_0N.png
├── output/cluster/{mode}/        ← 聚类结果（prototypes.csv / cluster_assignments.csv / 可视化）
├── output/cluster/report/        ← 聚类汇报文档 + 高级可视化图
│
├── scripts/                      ← 全部脚本（见下）
├── references/                   ← 字段总表 / 命名规范 / prompt 模板 / PRD
└── _legacy/                      ← 旧版示例归档
```

**命名规则**：项目夹 `{序号}-{项目中文名}`；单元夹 `{项目中文名}-{NN}`；单元内固定为 `plan.png / photo_0N.jpg / unit.dxf`。详见 `references/目录结构与命名规范.md`。

---

## 快速开始

### 1. 安装依赖

```bash
pip install ezdxf numpy opencv-python-headless torch torchvision transformers Pillow
# 聚类分析另需：
pip install scikit-learn matplotlib pandas shapely
```

**阶段 B 运行前必须设离线变量**（否则联网检查会卡十几分钟）：

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export M2F_MODEL_DIR=/path/to/mask2former_cache   # 本地模型缓存
```

> **中文路径注意**：`cv2.imread/imwrite` 对中文路径会静默失败，本项目用 `_imread_unicode()/_imwrite_unicode()` 处理；新增图像 I/O 请复用。

### 2. 一键跑（推荐）

```bash
python scripts/run_pipeline.py --dry-run       # 概览：哪些单元已处理 / 待处理
python scripts/run_pipeline.py --interactive   # 概览后确认再执行
python scripts/run_pipeline.py                 # 增量补跑：缺阶段A/B的自动补上
```

管道自动：扫 `input/{项目}/{单元}` → 检查 `output/...` 产物 → 缺则补跑 → 回写 `manifest.csv` 状态。**重复运行只处理新增。**

### 3. 聚类分析

```bash
python scripts/cluster_spaces.py --mode shell       # 空间原型（壳子）
python scripts/cluster_spaces.py --mode furnishing  # 陈设配置
python scripts/cluster_spaces.py --mode function    # 功能类型
python scripts/cluster_spaces.py --mode style       # 视觉风格
python scripts/make_cluster_report.py               # 生成汇报文档 + 高级可视化
```

---

## 聚类分析（4 个方向）

| 聚类 | k | 轮廓系数 | 结构 | 典型原型（单元数）|
|------|:--:|:--:|:--:|------|
| **空间原型（壳子）** | 3 | **0.47** | **强** | 小型封闭(17) / 大型开放(12) / 狭长(1) |
| 陈设配置 | 4 | 0.16 | 弱 | 高座多台面(5) / 低座小密集(16) / 高座中台面(8) / 高储物(1) |
| 功能类型 | 4 | 0.21 | 弱 | 综合办公(16) / 高绿植(1) / 高门窗通透(10) / 高密度混合(3) |
| 视觉风格 | 3 | 0.17 | 弱 | 暖调高饱和开放(4) / 明亮中性开放(12) / 私密明亮(14) |

**关键结论**：仅**壳子维度**具有清晰聚类结构（轮廓系数 0.47），提取出 3 个典型的 VR 实验壳子原型；陈设配置/功能/风格维度轮廓系数均低（0.16–0.21），说明 30 个共享办公样本在陈设配置、功能构成、视觉风格上**高度同质**（以办公/会议类型为主）。

**产物**：
- `output/cluster/{mode}/`：`prototypes.csv`（簇心原型）、`cluster_assignments.csv`（每单元归属+异常标注）、`cluster_summary.json`（k/轮廓系数）、4 张可视化
- `output/cluster/report/`：`聚类分析汇报.md` + 5 张高级图（PCA 椭圆总览 / 特征热力图 / 原型平行坐标 / 轮廓系数对比 / 逐样本轮廓图）

> **数据质量说明**：聚类过程主动发现并修复了 2 个净面积计算 bug（个别开放空间被误算成过小面积），修复后数据更可靠。单例簇自动标注为「异常(单例)」。

---

## 56 个特征速览

| 类别 | 数量 | 来源 | 举例 |
|------|:--:|------|------|
| 空间尺度 | 5 | DXF/LLM | 长 9.7m、宽 4.7m、层高 2.9m、面积 45.6m² |
| 围护结构 | 5 | LLM | 窗户数、窗墙比、门数、周长、围合度 |
| 空间比例 | 2 | DXF | 高宽比、长宽比 |
| 家具配置 | 3 | LLM/DXF | 座位数、家具密度、座位密度 |
| 色彩材质 | 15 | LLM | 色温、色调方案、主色 HEX/RAL、地/墙/天花材质 |
| 光环境与感知 | 7 | LLM | 灯具类型、照度 lux、采光系数、开阔感、私密性、RT60 |
| 平面几何 | 5 | OpenCV | 紧凑度、矩形度、凸性、水平/垂直通透度 |
| 语义构成 | 8 | Mask2Former | 围护壳体/地面/门窗/座椅/台面/储物/植物/照明 占比 |
| CV 感知 | 6 | OpenCV | 亮度、对比度、色温 CV、冷暖指数、饱和度、纵深感 |

完整字段总表（按分析维度分组，含单位/来源/所属聚类维度）见 **`references/特征字段总表.md`**。

---

## 版本管理（同步到 GitHub）

仓库：`https://github.com/everglowwwww/Space-Feature-Extractor.git`

```bash
python scripts/git_sync.py --dry-run                 # 预览将要提交什么
python scripts/git_sync.py -m "说明" --push           # 提交并推送（推荐）
```

- 自动 `git add -f input output`（数据在 .gitignore 中，脚本替你强制入库）
- 安全检查：API 密钥 `config/deepseek.json` 与冗余备份 `_restore_backup/` **若被误暂存会中止**

---

## 脚本清单

| 脚本 | 作用 |
|------|------|
| `run_pipeline.py` | **统一增量编排入口**（日常只用它） |
| `llm_phase_a.py` | 阶段A-视觉：多模态模型看图 → JSON |
| `dxf_parser.py` | 阶段A-几何：DXF 精确尺度 + 净面积（内圈孔洞多边形）+ 围合度 |
| `space_analyzer.py` | 阶段B：OpenCV + Mask2Former → 56 特征 + 图 |
| `cluster_spaces.py` | 聚类（shell/furnishing/function/style，mode 可插拔） |
| `make_cluster_report.py` | 聚类汇报 + 高级可视化 |
| `gen_manifest.py` / `apply_restructure.py` | 清单生成 / 目录标准化（幂等） |
| `git_sync.py` | 一键提交并同步到 GitHub |
| `plan_splitter.py` / `batch_analyze.py` / `card_generator.py` | 平面图拆分 / 批量阶段B / 案例卡片 |

---

## 换电脑部署

把整个 `space-feature-extractor/` 文件夹复制到新机器（或 git clone），按上面「安装依赖」装好依赖、配好 `M2F_MODEL_DIR` 即可直接跑。代码、文档、数据全在一起。详见 `DEPLOYMENT.md`。

---

## 更多信息

- 完整字段总表（按维度分组）→ `references/特征字段总表.md`
- 目录结构与命名规范 → `references/目录结构与命名规范.md`
- 技术路线与架构 → `references/PRD_空间分析管线.md`
- 研究方法论（壳子-陈设分离、聚类原型）→ `references/研究方法论.md`
- 项目进展与决策记录 → `MEMORY.md`
