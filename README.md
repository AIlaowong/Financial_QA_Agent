# 智能文档问答 Agent — 多 Agent 编排系统

采用 harness engineering 思想实现方案。基于 LangGraph 的多 Agent RAG（检索增强生成）系统，面向证券/金融领域的扫描件 PDF 文档问答。支持多策略 PDF 解析、降级链、Gateway 域过滤、红队审查、质量评分和精修循环。

## 设计思路

### 多 Agent 编排架构

```
用户问题
  │
  ▼
┌──────────┐   非证券  ┌──────────┐
│ Gateway  │─────────►│  拒答    │
│ 证券网关 │          └──────────┘
└────┬─────┘
     │ 证券领域
     ▼
┌──────────┐
│ Retrieve │  BM25 / Dense / Sparse / SQL 混合检索
│ 检索Tool │
└────┬─────┘
     │ 文档片段
     ▼
┌──────────┐
│  Answer  │  LLM 生成答案（含来源引用）
│ 回答Tool │◄──────────────────────┐
└────┬─────┘                        │
     │ 答案                         │ 精修反馈
     ▼                              │ (最多2次)
┌──────────┐                        │
│ Red Team │  deepseek-v4-pro 审查  │
│ 红队审查 │  证据/幻觉/完整性       │
└────┬─────┘                        │
     │ 审查结果                     │
     ▼                              │
┌──────────┐   评分<8 ──────────────┘
│ Quality  │  10分制质量评分
│ 质量评估 │  评分≥8 → 通过
└────┬─────┘
     │ 最终输出
     ▼
┌──────────┐
│  Final   │  整理答案 + 来源引用
│ 最终回答 │  + 缺陷说明
└──────────┘
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **Gateway Agent** | `agents/orchestrator.py` `_gateway` | 证券领域判断，非证券问题拒答 |
| **Retrieve Tool** | `tools/retriever.py` | BM25/Dense/Sparse/SQL 混合检索 |
| **Answer Agent** | `agents/orchestrator.py` `_answer` | 基于检索结果生成答案，支持精修 |
| **Red Team Agent** | `agents/orchestrator.py` `_red_team` | 证据/幻觉/完整性审查（独立模型） |
| **Quality Agent** | `agents/orchestrator.py` `_quality` | 10 分制质量评分，触发精修循环 |
| **Final Agent** | `agents/orchestrator.py` `_final_answer` | 最终答案 + 缺陷标注 |
| **文档解析** | `document_processing/` | MinerU/PaddleOCR/PyMuPDF 三级降级 |

### 关键设计决策

**1. 降级链 PDF 解析**

```
MinerU (VLM精准) → PaddleOCR-VL (百度云API) → PyMuPDF (本地快速)
```

| 策略 | 命令 | 适用场景 | API 依赖 |
|------|------|----------|----------|
| `pymupdf` | `build` | 文本型 PDF | 无 |
| `mineru` | `build --parser mineru` | 扫描件/复杂排版 | MinerU Token |
| `paddleocr` | `build --parser paddleocr` | 扫描件/多语言 | 百度 API Key |
| `fallback` | `build --parser fallback` | 自动降级链 | 按需 |

**2. 4 路混合检索**
- 3 路文本召回: BM25 (关键词) + Dense Embedding (qwen3-embedding-8b) + Sparse Embedding (text-embedding-3-small)
- 1 路 SQL 召回: LangChain SQL Agent 查询结构化表格
- RRF 融合 + qwen3-reranker 精排
- 无 API Key → 仅 BM25 关键词检索（免 API 始终可用）

**3. 红队 Agent 独立模型**
- Gateway/Answer/Quality/Final 使用 `LLM_MODEL`（如 deepseek-v4-flash）
- Red Team 使用 `RED_TEAM_LLM_MODEL`（如 deepseek-v4-pro），提供更严格的审查

**4. 精修循环**
- Quality ≥ 8 分 → 通过
- Quality < 8 分 → 红队建议 + 质量反馈注入 Answer Tool 精修
- 最多 2 次循环，超限直接输出 + 标注缺陷

**5. 元数据富化**
- 从文档内容自动提取：日期（财务期间）、主体（公司名）、客体（金额）、关系（投资/合营/减值）
- 解析器来源标记，追踪每个 chunk 的生成工具

**6. Harness Engineering 评估**
- 每个 Agent 环节均设计独立评估方案，可量化、可回归测试

## 快速开始

### 1. 环境准备

```bash
conda activate rag_env
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入各 API Key
```

**.env 关键配置：**
```env
# LLM
LLM_MODEL=deepseek-v4-flash
RED_TEAM_LLM_MODEL=deepseek-v4-pro    # 红队独立模型

# 文档解析
PARSER_STRATEGY=pymupdf                # pymupdf | mineru | paddleocr | fallback
MINERU_TOKEN=                          # MinerU API Token
PADDLEOCR_API_KEY=                     # 百度 PaddleOCR API Key
PADDLEOCR_SECRET_KEY=                  # 百度 PaddleOCR Secret Key

# Agent 参数
MAX_REFINE_LOOPS=2                     # 最大精修次数
QUALITY_THRESHOLD=8                    # 质量评分阈值
```

### 3. 构建知识库

```bash
python build.py --parser fallback       # 降级链
```

![构建知识库](pic/构建知识库.png)

### 4. 交互问答

```bash
python main.py ask
```

![交互问答](pic/对话.png)

### 5. 运行测试

```bash
python test.py                   # 8 线程并发测试
python test.py --concurrency 4   # 4 线程
```

![测试](pic/测试.png)

详见 [`TESTS.md`](TESTS.md)

## 业务场景扩展

| 场景 | 适配策略 |
|------|----------|
| 金融合规文档 | 切换 Gateway 为合规域，增加法规条文校验 |
| 合同审查 | 增加关键条款提取（违约金、保密、知识产权）Agent |
| 产品手册 | PaddleOCR 处理多语言 + 示意图理解 |
| 标准文件 | 增加标准编号索引 + 技术指标范围验证 |
| 审计底稿 | 增加交叉引用检查 + 勾稽关系验证 |

## 项目结构

```
project/
├── main.py                         # 入口：ask (交互/单次问答)
├── build.py                        # 入口：构建知识库
├── test.py                         # 入口：运行测试评估
├── config.py                       # 配置管理 (.env 加载)
├── .env.example                    # 配置模板（无密钥）
├── README.md
├── requirements.txt
├── agents/                         # Agent 定义
│   ├── orchestrator.py             #   多 Agent 编排器 (Gateway/Retrieve/Answer/RedTeam/Quality/Final)
│   └── sql_agent.py                #   SQL Agent
├── states/                         # Pydantic States
│   └── orchestrator_state.py       #   编排器状态
├── prompts/                        # Prompt 模板
│   ├── orchestrator_prompts.py     #   6 个 Agent 的 System/User Prompt
│   └── sql_agent_prompts.py        #   SQL Agent prompts
├── tools/                          # 工具
│   ├── retriever.py                #   BM25 / Dense / Sparse / SQL 混合检索器
│   └── document_tools.py           #   格式化 + 编排器输出
├── document_processing/            # 文档处理
│   ├── pdf_parser.py               #   PyMuPDF 解析器
│   ├── mineru_parser.py            #   MinerU API 解析器
│   ├── paddleocr_parser.py         #   PaddleOCR-VL API 解析器
│   ├── parser_factory.py           #   解析器工厂 + 降级链
│   ├── table_processor.py          #   表格处理 -> SQL
│   └── chunker.py                  #   清洗/分块/元数据富化
├── tests/
│   ├── test_dataset.json           #   8 个测试问题 (含 agent_metrics)
│   ├── run_evaluation.py           #   自动化评估
│   ├── validate_sql_recall.py      #   SQL 召回校验
│   └── EVALUATION_GUIDE.md         #   评估指南
└── data_db/                        # 生成数据 (gitignore)
```


## AI 工具使用说明

本项目使用 Claude Code 辅助开发：
- **架构设计**：描述需求，Claude Code 生成多 Agent 编排框架
- **代码生成**：逐模块生成，人工审查接口一致性和逻辑正确性
- **验证**：每个模块通过 `python build.py` / `python test.py` 验证
- **修正**：发现问题后迭代修正 prompt，确保结果可控

所有代码经人工审查确认，非直接复制粘贴。

## 项目状态
### 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| PDF 解析降级链 | ✅ | MinerU → PaddleOCR → PyMuPDF，出错自动降级 |
| 知识库构建 | ✅ | `build.py`，39 chunks + 表入 SQLite |
| 4 路混合检索 | ✅ | BM25 + Dense + Sparse + SQL，RRF 融合 + Reranker |
| Gateway 网关 | ✅ | 证券/非证券二分类，准确率 100% (8/8) |
| 检索召回 | ✅ | 召回率 100% (10/11，一次偶发 API 错误) |
| 答案生成 | ✅ | LLM 生成 + 来源引用，拒答正确率 100% |
| 红队审查 | ✅ | 独立模型 deepseek-v4-pro，证据/幻觉/完整性检查 |
| 质量评分 | ✅ | 10 分制，阈值触发准确率 100% |
| 精修循环 | ✅ | 最多 2 次，评分不达标时自动触发 |
| 并发测试 | ✅ | `test.py --concurrency N`，8 线程 ~2.8x 加速 |
| SQL Agent | ✅ | LangChain create_sql_agent，结构化表格查询 |

### 未完成
1、智能体的长短期记忆  
2、部分agent可以升级为skills范式  
3、对表格文档的多模态理解召回、表格转文字再进行语义召回  


