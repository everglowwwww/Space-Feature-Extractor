# Space-Feature-Extractor 项目记忆

> 本文件记录项目的关键决策、方法论共识和演进历程，跟随 git 同步，换电脑 clone 即可回顾。
> 最近更新: 2026-08（含目录整理 / 增量管道 / 净面积算法重构三大块）

---

## 项目概况

- **论文题目**: 《共享办公型室内空间陈设的脑认知与智能交互研究》
- **项目定位**: 硕士论文的数据采集工具，从共享办公空间的平面图+透视照中提取 56 个标准化特征
- **仓库地址**: git@github.com:everglowwwww/Space-Feature-Extractor.git
- **Skill 位置**: `~/.catpaw/skills/space-feature-extractor/`（与本仓库同一位置）

---

## 核心逻辑链条

整个研究的数据侧，遵循以下完整链条：

```
案例收集 → 平面图拆分 → 特征提取 → 壳子参数聚类 → 典型壳子原型 → VR 构建 → 陈设实验
```

每一步说明：

1. **案例收集**: 从 8-12 个共享办公项目中，通过实地考察/网络素材获取整层平面图和人视角透视照
2. **平面图拆分**: 用 `plan_splitter.py` 将整层平面图按功能区域拆分为独立空间单元（约 40 个）
3. **特征提取**: 用 space-feature-extractor skill 对每个空间单元提取 56 维特征向量
4. **壳子参数聚类**: 从 56 维中取壳子参数子集做聚类，得到几种典型壳子原型
5. **VR 构建**: 在 VR 中按原型参数建模实验空间
6. **陈设实验**: 在固定壳子内操控陈设方案，采集被试脑电/行为数据

详见 `references/研究方法论.md`。

---

## 关键方法论决策

### 决策 1: 壳子与陈设分离 (2025-06-28)

**问题**: 原型空间到底构建什么？是壳子（长宽高），还是空间特征+陈设的综合原型？

**结论**: 分离。
- **壳子（Shell）**: 面积、层高、长宽比、围合度等物理围护条件。建筑建成后基本固定。实验中作为**控制变量**。
- **陈设（Furnishing）**: 家具布局、色彩、材质、灯光等。运营方可调整。实验中作为**自变量**。
- **分离原因**: 确保实验内部效度——改变陈设时壳子不变，才能归因。

### 决策 2: 拆分依据是功能区域而非物理墙体 (2025-06-28)

**问题**: 共享办公内部很多区域之间没有实体墙，如何拆分空间单元？

**结论**: 按功能区域拆分。裁切框的边界可能对应墙，也可能是家具分界线、地面材质变化或空间布局的逻辑分区。对于同质性空间（如同层 8 个一样的小会议室），只选一个代表性单元。

### 决策 3: 非闭合空间的边界处理 (2025-06-28)

**问题**: 拆分出的子单元可能不是四面墙围合的，缺少墙体是否影响特征提取？

**结论**: 影响有限且可处理。
- **LLM 提取（38 个特征）**: 语义层面理解，能处理"三面墙一面开放"的形态。只要手绘平面图区分实墙（实线）和非墙边界（虚线/不画线），LLM 可正常工作。
- **OpenCV 平面几何（5 个特征）**: 轮廓可能不闭合影响精度，但这 5 个不是聚类核心参数，可接受。
- **Mask2Former + OpenCV 感知（13 个特征）**: 分析透视照像素，完全不受影响。

### 决策 4: 围合度与窗墙比联动 (2025-06-28)

**问题**: 如果空间围合度低（没有完整围护面），窗墙比（WWR = 窗面积/围护面总面积）的分母不成立。

**结论**: 联动规则写入 LLM prompt：
- `enclosure_ratio < 0.5` → `window_wall_ratio = -1`（无意义）
- `0.5 ≤ enclosure_ratio < 0.8` → WWR 仍提取，仅基于实际存在的围护面
- `enclosure_ratio ≥ 0.8` → WWR 完全有效

**关键认知**: 案例中的围合度描述"有没有墙"；VR 实验中的围合度描述"墙有多通透"（全实墙 vs 玻璃墙 vs 开放门洞）。VR 实验空间始终有四面围护，所以 WWR 在实验阶段始终有效。

### 决策 5: VR 还原度采用中间路线 (2025-06-28)

| 建筑元素 | 还原策略 |
|---------|---------|
| 壳子几何（长宽高） | 精确还原 |
| 窗户 | 简化模型，保留位置、大小和透光性 |
| 天花 | 保留高度感，简化造型 |
| 灯光 | 保留色温和照度，简化灯具形态 |
| 墙面/地面材质 | 使用中性统一材质，避免成为干扰变量 |

### 决策 6: 平面图绘制规范 (2025-06-28)

手绘平面图采用建筑制图惯例，并在 LLM prompt 中以文字说明嵌入（不依赖图片图例）：
- 粗实线（或双线）= 实体墙
- 弧线 = 门的开启方向
- 双线/三线（位于墙体上）= 窗户
- 细实线 = 家具轮廓
- 虚线或无线条的裁切边缘 = 非墙边界

---

## 技术管线概况

### 两阶段处理流程

```
输入图片 → [阶段A: LLM 多模态理解] → [阶段B: 本地 CV 管线] → 56 维特征向量
             (家具标定法反推尺寸)       (OpenCV + Mask2Former)
```

- **阶段 A**: LLM 看平面图+透视照，输出 38 个特征（尺度/围护/家具/色彩/光/感知），保存为 `llm_understanding.json`
- **阶段 B**: `space_analyzer.py` 跑 CV 管线，输出 18 个特征 + 可视化图片

### 壳子参数（用于聚类的核心字段）

| 参数 | 字段名 | 说明 |
|------|--------|------|
| 净使用面积 | net_area_m2 | 去除墙体后的可用地面面积 |
| 层高 | ceiling_height_m | 地面到天花板净高 |
| 长宽比 | length_width_ratio | 1.0=方正，>2.5=狭长 |
| 围合度 | enclosure_ratio | 0=全开放，1=全封闭 |
| 高宽比 | height_width_ratio | 空间纵向比例感 |

### 关键脚本

| 脚本 | 功能 |
|------|------|
| `scripts/llm_phase_a.py` | 阶段A视觉：调 DeepSeek 视觉模型看图 → `llm_understanding.json`（零第三方依赖） |
| `scripts/dxf_parser.py` | 阶段A几何：解析 DXF → 精确尺度（长宽/面积/周长/围合度/家具），覆盖进 JSON（仅依赖 ezdxf） |
| `scripts/space_analyzer.py` | 单案例阶段 B 分析 |
| `scripts/batch_analyze.py` | 批量处理（支持 `--cards-only`） |
| `scripts/plan_splitter.py` | 平面图拆分预处理（analyze→preview→split 三步） |
| `scripts/card_generator.py` | 杂志风格案例卡片生成（2x Retina） |

---

## 里程碑

| # | 内容 | 状态 |
|---|------|------|
| M1 | Demo 验证：单案例跑通完整流程（56 特征，8 秒） | ✅ |
| M2 | 特征精简：142 → 56 个 | ✅ |
| M3 | Skill 封装 + PRD + 示例数据 | ✅ |
| M4 | 平面图拆分器 plan_splitter.py | ✅ |
| M5 | 方法论文档（壳子-陈设分离、聚类原型、边界定义） | ✅ |
| M6 | 批量采集：~40 个空间单元案例 | ✅ 30 个单元全量特征提取完成 |
| M7 | 壳子参数聚类 → 提取典型原型空间 | ✅ k=3，3 典型壳子原型 + 1 异常 |
| M8 | 数据分析：统计建模与可视化 | ⏳ |

---

## 待验证事项

- [ ] LLM 对非闭合平面图的识别准确率（手绘几个测试案例验证）
- [ ] 手绘平面图的绘制一致性（不同案例间风格是否需要更严格规范）
- [ ] 40 个样本的聚类稳定性和可解释性
- [ ] 围合度联动规则在实际案例中的效果

---

## 参考文档索引

| 文档 | 定位 | 路径 |
|------|------|------|
| 研究方法论 | 研究设计层面：完整逻辑链条和方法论决策 | `references/研究方法论.md` |
| PRD | 技术实现层面：管线架构、特征定义、部署方案 | `references/PRD_空间分析管线.md` |
| LLM Prompt 模板 | 执行规范层面：LLM 看图时的具体指令 | `references/llm_prompt_template.md` |
| 特征字典 | 数据规范层面：56 个字段的定义和基准值 | `references/feature_dictionary.json` |

---

## 2026-08 会话纪要：目录整理 + 增量管道 + 净面积算法重构

> 本轮完成：环境验证、目录结构与命名规范 v1.0、统一增量管道、修复若干 bug、净面积算法重写（排除凹口）。

### 一、环境验证（全部通过）
- `.venv`：Python 3.12.10。`torch 2.11.0+cu128`（CUDA 可用，识别 **RTX 5060**）、`transformers 5.15.1`、`opencv 5.0.0`、`numpy 2.5.2`、`ezdxf 1.4.4`、`Pillow 12.3.0`、**`shapely 2.1.2`（本轮新增装）**。
- Mask2Former 模型缓存在 `E:\毕业论文\.venv\hf_cache\model_download`（`pytorch_model.bin` 181MB）。离线加载（`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 M2F_MODEL_DIR=...`），GPU 推理 ~70ms/张，结果与已验证基准（盈科中心-5）逐字段一致。**加载报告里的 swin.layernorm MISSING 是良性**（该 checkpoint 本来就没存，按恒等初始化，已验证不影响结果）。
- 阶段 A 通道：`config/deepseek.json` 有效（`deepseek-v4-flash-vision-exp`，`max_tokens=16384`，`thinking_disabled=true`），ping 0.4s。

### 二、目录结构与命名规范 v1.0（已冻结，`references/目录结构与命名规范.md`）
- **input = 纯人工素材，output = 全部生成内容，两者严格镜像**。
- 项目夹 `{序号}-{项目名}`（如 `1-北京盈科中心`）；单元夹 `{项目名}-{NN}`（**无空格**，如 `北京盈科中心-01`）。
- 单元内文件标准化：`plan.png` / `photo_0N.jpg` / `unit.dxf`（`.ai` 保留）。
- **`llm_understanding.json` 属 output 侧**（阶段A产物，不进 input）。
- 8~18 号占位项目夹（王府国际中心…酒仙桥14号）；旧平铺示例归档到 `_legacy/`。
- 所有规范 + 映射表：`manifest.csv`（30 单元状态）、`input_rename_map.csv`（131 条 input 侧改名映射）。

### 三、新增/修改脚本
- **`scripts/gen_manifest.py`**：扫 `input/` → 生成 `manifest.csv` + `input_rename_map.csv`（发现式、幂等）。
- **`scripts/apply_restructure.py`**：执行改名/标准化/建占位/建 output 骨架/归档（幂等，本次已执行）。
- **`scripts/run_pipeline.py`**：**统一增量管道入口**。`--phase a|b|all`、`--unit`（多个逗号分隔）、`--force`、`--dry-run`、`--report`。流程：扫 input → 检查 output 产物缺失 → 补阶段A/B → 写 output → 回写 manifest 状态。重复运行只处理新增。
- **`scripts/dxf_parser.py` 净面积算法重写**（见下）。

### 四、执行结果
- 结构整理完成：**30 个单元改名** + **131 个文件标准化** + **47 个 output 骨架** + `_legacy/` 归档 + `_restore_backup/` 备份。
- **盈科中心 01/02/03 已端到端跑通**（阶段A+B，每单元 9 个产物：`llm_understanding.json` + `features.json/cn/csv` + `plan_binary.png` + `seg_semantic_01/02` + `seg_overlay_01/02`）。

### 五、本轮修复的 bug
1. **`run_pipeline.py --photos` 传参**：原来 `--photos a --photos b`（重复 flag），argparse 只取最后一张 → 语义/感知特征只基于 1 张图、部分分割图缺失。改为 `--photos a b`（一次性传入）。
2. **`cv2.imwrite` 中文路径静默失败**：`plan_binary.png`、`seg_semantic_*.png` 用 cv2.imwrite，中文输出路径写不出来（PIL 的 overlay 能写）；新增 `_imwrite_unicode()`（imencode+写字节）。与既有 `_imread_unicode()`（读方向）配套。

### 六、净面积算法重构（关键方法论）
- **原问题**：`dxf_parser` 用**外包矩形面积** `length×width` 当净面积，L 形房间把凹口（右上角）算进去了（盈科中心-02 报 22.54㎡，明显偏大）。
- **试过的方案**：
  - 图像 flood-fill（读 plan_binary 黑像素）→ **在虚线开放边界/门洞处泄漏**（三里屯11号-03 直接算 0）。虚线封不住。
  - **最终方案：基于 DXF 矢量几何 + 轮廓**：栅格化「墙体+虚线」带 → 闭运算桥接 → `RETR_CCOMP` 找**内圈孔洞多边形面积**（排除凹口+墙厚）；无孔洞（开放空间）则**逐步加大桥接核取外圈足迹面积**兜底。
- **关键认识**：墙体从 **DXF「墙体」图层**（矢量 POLYLINE）+ **「虚线」图层**（开放边界）识别，**不是靠像素是否涂黑**；家具（桌椅柜）不参与边界。这使它权威（±0）、不受图像质量/虚线断口影响。
- **验证**（净面积=net_area_m2，口径=area_method）：
  | 单元 | 外包矩形(旧) | 净面积(新) | 口径 |
  |---|---|---|---|
  | 盈科中心-02 | 22.54 | **17.90** | enclosed |
  | 盈科中心-09 | 25.68 | **20.59** | enclosed |
  | 三里屯11号-03 | 86.25 | 88.17 | outer（兜底，待人工复核）|
  | 望京国际中心-04 | 137.74 | **120.93** | enclosed |

### 七、待办 / 注意
- **已跑的 01/02/03 仍是旧面积**（外包矩形）——需**重跑几何 merge（dxf_parser，零 API）+ 阶段 B** 才能用上新净面积。尚未刷新。
- **三里屯11号-03 面积待人工复核**（开放空间外圈兜底 88.17，墙段零散不成环）。
- 其余 **27 个单元未跑**（现有 phase A 需调 DeepSeek API）。
- **中文路径**：cv2.imread/imwrite 均有 Unicode 坑（已用 `_imread_unicode`/`_imwrite_unicode` 处理）；新 output 结构全是中文路径，必须走这些函数。
- **manifest.csv 在会话内可能被读取句柄占用**导致外部进程无法覆写（gen_manifest 已做容错跳过；实际非会话环境可正常写）。
- 阶段A 用 DeepSeek API（联网、按量计费）；阶段B 有 GPU（快）。

---

## 2026-08 会话纪要（二）：skill 注册 + 规范化 + 交互概览 + 围合度修复

### 一、skill 已注册为可触发的本地 skill（方案B：junction）
- 在用户级 skill 根建目录 junction：
  `C:\Users\Leo Lee\.dsh\skills\space-feature-extractor` → `E:\毕业论文\2.案例调研与数据集\.codex\skills\space-feature-extractor`
- **数据本体仍在原位**（`.codex/skills/...`），junction 只是指针；删掉即回滚。
- dsh 的 `dsh-skill-filesystem` 从 `~/.dsh/skills/<name>/SKILL.md` 发现 skill；`available_skills` 已列出 `space-feature-extractor`，`skill` 工具可正常加载。**当前会话立即生效。**
- dsh skill 机制要点：`name` 必须 kebab-case；`SKILL.md` 带 frontmatter `name/description`；provider 扫描 `.dsh/skills`、`.agents/skills`、`~/.dsh/skills`、`customSkillDirs`、`DSH_BUNDLED_SKILL_DIR`；`watchFollowSymlinks:true`。

### 二、SKILL.md 重写（Windows 适配 + 可跨 agent 调用）
- 路径全部**相对化**（用 `$SKILL_DIR`），去掉旧 `~/.catpaw/skills` 硬编码。
- 新增「环境与路径（通用+本机）」：离线变量、`M2F_MODEL_DIR`、cv2 中文路径坑（`_imread_unicode`/`_imwrite_unicode`）、PowerShell 环境变量、DeepSeek config。
- 新增「启动流程（交互预览）」章节：引导词 → `--dry-run` 概览 → 汇总 → 询问确认 → 执行。
- 统一以 `run_pipeline.py` 为主线；阶段A/B 脚本说明降为参考；`batch_analyze.py` 降为次要。

### 三、run_pipeline.py 增强（交互概览）
- `--dry-run` 新增**聚合汇总**：`[概览] 共 N 单元；阶段A 完成 X/待 Y（本批执行 Z）；阶段B 完成 X/待 Y`。
- 新增 **`--interactive`**：先出概览表+汇总，`input()` 询问「是否开始处理未完成内容? [y/N]」，确认后才执行。
- 逻辑重构出 `plan_units()`（计算 needs + 打状态行）。

### 四、dxf_parser.py 围合度修复（0-1）
- **旧公式**：`enclosure_ratio = wall_total / (2*(L+W))`（墙段长边和 ÷ 外包矩形周长）→ L/阶梯形房间 >1（盈科中心-01 曾 1.11）。
- **新公式**：`enclosure_ratio = wall_len / (wall_len + 虚线长边)`，其中虚线段用与墙体一致的 **OBB 长边口径**（新增 `virtual_bbox_length_m`）。**恒 ∈[0,1]**。
- 验证：01=0.945、02=0.956、09=0.781、望京04=0.930、三里屯03=0.745 全部落于 [0,1]。

### 五、待办更新
- 01/02/03 仍是旧净面积（外包矩形）；刷新路径：重跑 `dxf_parser --llm-json output/.../llm_understanding.json`（零 API）+ 阶段B。
- 三里屯11号-03 面积待人工复核（外圈兜底）。
- 其余 27 个单元未跑。
- 若后续 dsh config 打开 `customSkillDirs`，可彻底"就地"注册（无需 junction）；当前 junction 已够用。

### 六、SKILL.md 长度 / CSV 合并 / 状态管理
- **SKILL.md 长度**：88 行 / 6471 字符，对 skill 指令属正常范围，不会造成模型幻觉（如仍担心可再精简，但不必要）。
- **CSV 合并（只剩一个管理文件）**：
  - `file_rename_map.csv`（旧改名表，161 行）→ **已删除**（废弃重复）。
  - `input_rename_map.csv`（改名映射，131 行）→ **已归档到 `_legacy/`**（重命名已完成；`gen_manifest.py` 在新增单元时会重新生成，纯粹派生工具产物）。
  - `manifest.csv`（30 行，含状态）→ **★ 唯一管理文件**：`run_pipeline.py` 每跑完自动回写「状态」；`gen_manifest.py` 重跑**保留已有状态**（本次已修复，之前会重置为"待分析"）。
- **已/未处理自动更新**：`run_pipeline.py` 处理完写回 manifest（01/02/03 现为 `阶段B完成`）；`--dry-run` 每次显示最新概览表 + 汇总。
- **自动按序处理所有未处理**：`run_pipeline.py`（默认 all）按项目→单元固定顺序自动补跑全部待处理；`--interactive` 先概览后确认；`--phase a/b`、`--unit` 可限定范围。

### 七、manifest 精简 + 自动同步（本轮）
- **manifest.csv 已精简为 6 字段**：`项目 / 项目编号 / 项目中文名 / 单元(新名) / 新单元路径 / 状态`。去掉了旧名称（旧单元目录）和源文件名（平面图源/照片源/DXF源/AI源文件）。
- **阶段A状态**：保留 3 态枚举 `待分析 / 阶段A完成 / 阶段B完成`（B 前置 A，`阶段A完成` 即"仅 A 完成"，无需单独列）；直接看"是否阶段B完成"即知全流程是否就绪。
- **run_pipeline 自动同步 manifest**：每次启动先 `gen_manifest.build_rows()` 扫 input → 新增单元写进 manifest（状态=待分析）+ 保留已有状态 + 精简字段，再检查/处理。**这样"检查 input"时 manifest 永远反映最新内容，不再手持旧数据**（正常环境会落盘；会话句柄占用时写盘容错跳过）。
- **改名映射迁到 input_rename_map.csv**（派生工具）：新增 `旧单元目录` 列，`apply_restructure.py` 改从该表读取（不再依赖 manifest 的旧目录字段）；重命名完成后归档 `_legacy/`，`gen_manifest.py` 在新增单元时会重新生成。
- `gen_manifest.py` 抽出 `build_rows()` 供 `run_pipeline.py` 复用（同一套发现+保留状态逻辑）。
- 验证：manifest.csv = 6 字段 / 30 单元 / 状态 {阶段B完成:3, 待分析:27}。

### 八、壳子聚类（M7 完成）
- **新增可复用脚本**：`scripts/cluster_spaces.py`（mode 可插拔，`--mode shell` 默认 k=3；库 `scikit-learn`、`matplotlib` 已装）。
- **方法**：30 单元的壳子 5 字段（`net_area_m2/ceiling_height_m/length_width_ratio/height_width_ratio/enclosure_ratio`，来自 features.json）→ StandardScaler 标准化 → K-means（+Ward 层次对照）→ 轮廓系数定 k；单例簇自动标异常。
- **定 k=3**（轮廓系数 k3=0.424 vs k4=0.427 接近；k=4 有 2 个单例簇→过度拆分，故选 k=3）。
- **3 个典型壳子原型**：
  | 原型 | 单元数 | 净面积 | 层高 | 长宽比 | 围合度 | 解读 |
  |---|---|---|---|---|---|---|
  | 0 | 17 | 16.14㎡ | 2.84 | 1.43 | 0.93 | 小型封闭办公室 |
  | 1 | 12 | 123.31㎡ | 3.33 | 1.47 | 0.83 | 大型开放协作区 |
  | 2 | 1 | 54.83㎡ | 3.20 | 3.10 | 0.62 | 狭长走廊型（**盈科中心-08，异常待复核**）|
- **产出**（`output/cluster/shell/`）：`prototypes.csv`、`cluster_assignments.csv`（含**备注=单例异常**列）、`pca_scatter.png`、`centroid_radar.png`、`silhouette_vs_k.png`、`dendrogram.png`。
- **已沉淀进 SKILL.md**（"三-b、聚类与原型提取"节）。

### 八-b、功能类型 + 视觉风格聚类（M7 扩展，已完成）
- `cluster_spaces.py` 已支持 3 个 mode（`shell/function/style`），`MODES` 定义特征子集；功能/风格需 `pandas`（One-Hot）。
- **风格**：`--mode style`（色彩/材质/光/感知，文本字段 One-Hot + 数值 StandardScaler）→ k=3，轮廓 0.16（弱）。
  - 原型0=暖亮开放(6)；原型1=私密明亮(14)；原型2=高密度开放(10)。
- **功能**：`--mode function`（语义功能占比 7 字段）→ k=5，轮廓 0.19（弱）。
  - 原型0=办公混合(15)；原型1=高门窗通透(12)；原型2/3/4=单例异常。
- **重要发现**：功能/风格聚类**轮廓系数偏低**（数据本身分离度不高，共享办公空间功能/风格趋同）；且个别单元**家具密度异常**（如 15.47、2.1，正常为 ~0.2-0.4）→ 需数据复核。单例簇自动标 `异常(单例)`。
- **过程性文件**（可复用，供其他软件汇报/建模）：`output/cluster/{shell,function,style}/` 下 `prototypes.csv` + `cluster_assignments.csv` + 4 张可视化图。
- 依赖：新增 `scikit-learn`、`matplotlib`、`pandas`（已装）。

### 八-c、陈设配置聚类 + 数据修复（重要）
- **新增 mode** `furnishing`（家具密度/座位密度/座位数 + 语义构成 + 主色占比）——论文的实验自变量维度。
- **揪出并修掉 2 个数据 bug**（都是净面积算错 → 家具密度假高）：
  1. **互联网金融中心-03**：`compute_enclosed_area` 误把 3.91㎡ 小内腔当封闭区（房间实际 16.69×10.13m，~150㎡）。→ 给 `compute_enclosed_area` 加**合理性校验**（封闭区 < 外包 30% 判为未闭合 → 回退 outer 足迹），修复后净面积 150.2㎡、密度 0.4。
  2. **望京国际中心-03**：outer 兜底给 19.87㎡（15×9.55 房间），家具占地 57.92㎡ → 密度 2.92。→ 在 `compute_metrics` 加**安全网**（净面积 < 家具占地 → 退回外包矩形并标 `bbox`），修复后净面积 143.31㎡、密度 0.4。
- **修复后的真实聚类结构**（之前的"强结构"是假象）：
  | 聚类 | k | 轮廓系数 | 结构 |
  |------|:--:|:--:|:--:|
  | shell 空间原型 | 3 | **0.47** | 强 |
  | furnishing 陈设配置 | 4 | 0.16 | 弱（之前 0.503 是数据假象）|
  | function 功能类型 | 4 | 0.21 | 弱 |
  | style 视觉风格 | 3 | 0.17 | 弱 |
- **关键结论**：**仅壳子维度结构强**；陈设配置/功能/风格都弱（0.16-0.21）——30 个共享办公样本在"陈设配置/功能/风格"上**高度同质**。这是样本集的真实特征（"样本同质"发现 / 提示实验需人为制造陈设多样性）。
- 剩余高密度但不违规的单元：望京05（0.72）、互联网金融04（0.93）——数学成立（家具≤净面积），属"高密度"而非错误。

### 九、聚类分析汇报（今日收尾）
- **新增 `scripts/make_cluster_report.py`**：从 `output/cluster/{mode}/`（prototypes.csv + cluster_assignments.csv + cluster_summary.json）一键生成**汇报文档 + 高级可视化图**。依赖 matplotlib。
- **`cluster_spaces.py` 现在会写 `cluster_summary.json`**（k + 轮廓系数），供汇报脚本/其他软件读取权威值。
- **汇报产物**（`output/cluster/report/`）：
  - `聚类分析汇报.md`：方法 + 四类聚类汇总 + **4 个方向的原型明细表**（参数+解读+单元数）+ 可视化 + 发现意义。
  - 5 张高级图：`fig_overview_dashboard.png`（2×2 PCA + 簇椭圆 + X簇心 + 标签 + 方差解释率）、`fig_shell_heatmap.png`（壳子特征热力图按簇排序）、`fig_prototype_profiles.png`（原型平行坐标）、`fig_silhouette_compare.png`（四类轮廓系数对比）、`fig_shell_silhouette.png`（逐样本轮廓图）。
  - 修正过：轮廓对比图曾因"报告用简化字段重算轮廓系数"而数值错误，已改为读 `cluster_summary.json` 权威值；单元对齐按 cluster_assignments 的"单元"字段。
- **四类聚类原型明细**（单元数）：
  - 壳子 k=3：小型封闭(17)/大型开放(12)/狭长(1=盈科中心-08)
  - 陈设配置 k=4：高座多台面(5)/低座小密集(16)/高座中台面(8)/高储物(1)
  - 功能 k=4：综合办公(16)/高绿植(1)/高门窗通透(10)/高密度混合(3)
  - 视觉风格 k=3：暖调高饱和开放(4)/明亮中性开放(12)/私密明亮(14)
- **关键结论**：仅壳子维度结构清晰（轮廓 0.47）；陈设/功能/风格趋同（0.16-0.21）。数据经修复后更可靠；聚类过程主动揪出并修掉 2 个净面积计算 bug。
- **待办**：组会/论文第三章可用 `聚类分析汇报.md` + 图；若需可导出 HTML/PDF 版。
