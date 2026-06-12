# 测试评估指南

## 测试数据

**测试集**: `tests/test_dataset.json` — 8 道问题，覆盖 6 类场景
**测试结果**: `test_data_result/test_results_{timestamp}.json` — 每次运行自动生成

## 测试结果 JSON 结构

每次运行测试后，结果文件包含以下完整链路：

```json
{
  "timestamp": "20260613_012649",
  "concurrency": 8,
  "summary": {
    "total": 8,
    "passed": 7,
    "failed": 1,
    "pass_rate": "87.5%",
    "total_time_sec": 109.6,
    "serial_equivalent_sec": 444.6,
    "speedup": 4.1,
    "agent_stats": {
      "gateway":    {"total": 8, "passed": 8},
      "retrieve":   {"total": 11, "passed": 11},
      "answer":     {"total": 8, "passed": 8},
      "red_team":   {"total": 7, "passed": 6},
      "quality":    {"total": 7, "passed": 7}
    },
    "category_stats": {
      "正文理解": {"passed": 1, "total": 1},
      "表格-长期股权投资": {"passed": 1, "total": 1}
    }
  },
  "results": [
    {
      "test_id": 1,
      "category": "表格-长期股权投资",
      "question": "Sino-Ocean...",
      "expected_type": "有答案",
      "check_points": ["7.16"],
      "elapsed_sec": 81.7,
      "passed": true,
      "error": "异常信息(仅失败时存在)",
      "per_agent_metrics": [
        {"agent": "gateway",  "metric": "is_securities", "expected": true, "actual": true, "passed": true},
        {"agent": "retrieve", "metric": "min_docs",      "expected": ">= 1", "actual": 5,    "passed": true},
        {"agent": "retrieve", "metric": "sql_hit",       "expected": true,    "actual": true, "passed": true},
        {"agent": "answer",   "metric": "refuse",        "expected": false,   "actual": false,"passed": true},
        {"agent": "red_team", "metric": "has_evidence",  "expected": true,    "actual": true, "passed": true},
        {"agent": "quality",  "metric": "min_score",     "expected": ">= 7",  "actual": 10,   "passed": true}
      ],
      "agents": {
        "gateway": {
          "is_securities": true,
          "reason": "涉及公司账面价值查询..."
        },
        "retrieve": {
          "document_count": 5,
          "best_score": 0.8674,
          "documents": [
            {"page": 0, "score": 1.0, "type": "sql_agent", "preview": "[SQL Agent] ..."},
            {"page": 2, "score": 0.95, "type": "table_context", "preview": "..."},
            {"page": 5, "score": 0.91, "type": "text", "preview": "..."}
          ]
        },
        "answer": {
          "answer": "根据文档第44页...",
          "check_point_hits": {"7.16": true},
          "hit_count": 1,
          "total_checks": 1
        },
        "red_team": {
          "verdict": "pass",
          "has_evidence": true,
          "possible_hallucination": false,
          "issues": [],
          "suggestions": ["建议注明金额单位"],
          "strengths": ["答案精确回应问题"]
        },
        "quality": {
          "score": 8,
          "reason": "答案准确，引用具体..."
        },
        "refine": {
          "count": 0,
          "history": []
        },
        "final": {
          "defects": "金额单位未明确标注"
        }
      }
    }
  ]
}
```

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | string | 运行时间戳 `YYYYmmdd_HHMMSS` |
| `concurrency` | int | 并发线程数 |
| `summary` | object | 汇总报告，见下方 |
| `results` | array | 每道题的详细测试结果 |

### summary 汇总报告

| 字段 | 说明 |
|------|------|
| `total` | 总题数 |
| `passed` | 通过数 |
| `failed` | 失败数 |
| `pass_rate` | 通过率 (百分比字符串) |
| `total_time_sec` | 并发总耗时 (秒) |
| `serial_equivalent_sec` | 串行等效耗时 (秒)，各题耗时之和 |
| `speedup` | 加速比 = serial_equivalent / total_time |
| `agent_stats` | 按 Agent 维度统计 `{agent: {total, passed}}` |
| `category_stats` | 按测试类别统计 `{category: {total, passed}}` |

### results[] 每题结果

| 字段 | 类型 | 说明 |
|------|------|------|
| `test_id` | int | 测试编号 (1-8) |
| `category` | string | 测试类别 |
| `question` | string | 测试问题原文 |
| `expected_type` | string | 预期答案类型：`有答案` / `无答案/拒答` / `Gateway拒答` |
| `check_points` | string[] | 答案中期望出现的关键词 |
| `elapsed_sec` | float | 单题耗时 (秒) |
| `passed` | bool | 综合判定是否通过 |
| `error` | string | 异常信息 (仅 `passed=false` 时出现) |
| `per_agent_metrics` | array | 每个 Agent 的各指标评估结果 |
| `agents` | object | 各 Agent 的中间状态输出 |

### per_agent_metrics[] 指标评估

| 字段 | 说明 |
|------|------|
| `agent` | Agent 名称：`gateway` / `retrieve` / `answer` / `red_team` / `quality` |
| `metric` | 指标名：`is_securities` / `min_docs` / `sql_hit` / `refuse` / `has_evidence` / `min_score` |
| `expected` | 期望值 |
| `actual` | 实际值 |
| `passed` | 该项是否通过 |

### agents 各 Agent 中间状态

#### agents.gateway — 证券域网关

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_securities` | bool | 是否证券领域问题 |
| `reason` | string | 判断理由 |

#### agents.retrieve — 检索召回

| 字段 | 类型 | 说明 |
|------|------|------|
| `document_count` | int | 召回文档总数 |
| `best_score` | float | 最佳相关度得分 |
| `documents` | array | 召回文档列表 |

**documents[] 每项：**

| 字段 | 说明 |
|------|------|
| `page` | 页码 |
| `score` | 相关度得分 (0-1) |
| `type` | 来源类型：`sql_agent` / `table_context` / `text` |
| `preview` | 文档内容前 150 字符 |

#### agents.answer — 答案生成

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer` | string | 最终生成的答案文本 |
| `check_point_hits` | object | 各检查点是否命中 `{"关键词": true/false}` |
| `hit_count` | int | 命中的检查点数 |
| `total_checks` | int | 检查点总数 |

#### agents.red_team — 红队审查

| 字段 | 类型 | 说明 |
|------|------|------|
| `verdict` | string | 裁决：`pass` / `needs_improvement` / `fail` |
| `has_evidence` | bool | 答案是否有文档证据支撑 |
| `possible_hallucination` | bool | 是否存在可能的幻觉 |
| `issues` | string[] | 发现的问题列表 |
| `suggestions` | string[] | 改进建议列表 |
| `strengths` | string[] | 红队认可的答案优点 |

#### agents.quality — 质量评分

| 字段 | 类型 | 说明 |
|------|------|------|
| `score` | int | 质量评分 (1-10) |
| `reason` | string | 评分理由 |

#### agents.refine — 精修循环

| 字段 | 类型 | 说明 |
|------|------|------|
| `count` | int | 精修次数 |
| `history` | array | 精修历史 `[{"round": N, "score": S}]` |

#### agents.final — 最终输出

| 字段 | 类型 | 说明 |
|------|------|------|
| `defects` | string | 需人工确认的缺陷说明 |

## 每个 Agent 的评估指标

### Gateway（证券域网关）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 证券问题接受率 | 7/7 证券题 `is_securities=true` | 证券题必须接受 |
| 非证券拒答率 | 1/1 非证券题 `is_securities=false` | 非证券题必须拒答 |
| 延迟 | 单次 LLM 调用耗时 | ~2s |

**怎么看 Gateway badcase?**
→ 找到 `per_agent_metrics` 中 `"agent": "gateway"`，检查 `actual` 字段。如果证券题返回 `false` → Gateway prompt 判断边界需调整。

### Retrieve（检索召回）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 召回文档数 | `document_count` | 正常 3-5 条 |
| 最佳相关度 | `best_score` | 应 > 0.5 |
| SQL 召回命中 | `documents` 中出现 `type=sql_agent` | 结构化数据覆盖 |
| 表格上下文命中 | `documents` 中出现 `type=table_context` | 表格语义覆盖 |

**怎么看 Retrieve badcase?**
→ 找到 `"agent": "retrieve"`，查看 `documents` 列表。如果 `best_score < 0.3` 或表格题没有 `sql_agent` 来源 → 调参：增大 `RETRIEVAL_K`、调整 `RRF_K`、检查 embedding 模型。

### Answer（答案生成）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 关键点命中率 | `hit_count / total_checks` | 核心事实准确度 |
| 拒答正确率 | 无答案题中 `refuse=true` | 不编造 |
| Gateway 拒答 | `is_securities=false` 时自动视为拒答 | 非证券问题不应生成答案 |

**怎么看 Answer badcase?**
→ 找到 `"agent": "answer"`，对比 `answer` 和 `check_points`。缺失关键点 → 检索没召回关键信息；误拒答 → prompt 过于保守。

### Red Team（红队审查）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 裁决分布 | pass / needs_improvement / fail 比例 | 正常 pass > 80% |
| 证据判定 | `has_evidence` 比例 | 应与检索质量一致 |
| 优势数量 | `strengths` 数组长度 | 应有具体优点 |
| 建议质量 | `suggestions` 非空且具体 | 不能是空数组或泛泛而谈 |

**怎么看 Red Team badcase?**
→ 找到 `"agent": "red_team"`：
- `verdict=fail` 但答案实际正确 → 红队过于严格，调整 `RED_TEAM_SYSTEM` prompt
- `has_evidence=false` 但 `documents` 非空 → 红队未看到关键片段，增加传给红队的文本量
- `issues` 为空但答案有问题 → 红队漏检，增强审查维度

### Quality（质量评估）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 平均评分 | 所有问题 `score` 平均值 | 正常 7-9 |
| 评分分布 | 各分数段占比 | 无极端值 |
| 红队一致性 | `verdict=pass` 且 `score >= 7` | 不自相矛盾 |
| 阈值触发 | `score < 8` 时触发 `refine` | 精修触发准确率 |

**怎么看 Quality badcase?**
→ 找到 `"agent": "quality"`：
- `score >= 8` 但答案实际有错 → 评分规则需更严格
- `score < 5` 且 `verdict=pass` → 评分和红队裁决矛盾，对齐 `QUALITY_SYSTEM` 和 `RED_TEAM_SYSTEM`

### Refine（精修循环）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 精修触发率 | `count > 0` 的比例 | 正常 < 30% |
| 评分改善 | 精修后评分 - 精修前评分 | 应 > 0 |
| 循环上限 | `count <= 2` | 100% 应遵守 |

**怎么看 Refine badcase?**
→ 找到 `"agent": "refine"`，查看 `history`：
- `count=2` 且最终 `score < 8` → 精修无效，检查 `_answer` 的 `refine_feedback` 注入逻辑
- `history` 中评分递减 → refine 破坏了答案，检查反馈措辞

### Final（最终输出）

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| 缺陷标注 | `defects` 非空时有实质内容 | 需人工确认的事项 |
| 精修体现 | 精修后答案是否包含改进 | 可对比各轮次 |

## 如何定位 Badcase / Hardcase

### Step 1：按 passed 过滤

```bash
# 只看失败的
cat test_data_result/test_results_xxx.json | jq '.results[] | select(.passed == false)'
```

### Step 2：逐 Agent 排查

失败的题，从上往下查 Agent 链路：

1. **Gateway 误拒？** → `agents.gateway.is_securities`
2. **检索没召回？** → `agents.retrieve.document_count == 0` 或 `best_score < 0.1`
3. **答案缺关键点？** → 对比 `agents.answer.check_point_hits`
4. **SQL 没命中？** → `per_agent_metrics` 中 `sql_hit.passed`
5. **红队误判？** → `agents.red_team.verdict == "fail"` 但实际答案正确
6. **评分过低？** → `agents.quality.score < 5`

### Step 3：定位根因

```
答案缺关键点 → 检索没召回 → 关键词不匹配？
  → 检查 BM25 tokenization
  → 检查 embedding 模型对财务术语的覆盖

红队误判 → prompt 太严格？
  → 调整 RED_TEAM_SYSTEM 中的评估原则

评分和红队矛盾 → 两个 agent 的评分标准不一致？
  → 对齐 QUALITY_SYSTEM 和 RED_TEAM_SYSTEM

精修无效 → refine_feedback 没有注入关键信息？
  → 检查 _answer 中 feedback 文本的拼接逻辑
```

## 如何优化对应 Agent

| Agent | 优化手段 |
|-------|----------|
| **Gateway** | 调整 `GATEWAY_SYSTEM` 判断边界；增加模糊词容忍度 |
| **Retrieve** | 调大 `RECALL_PER_PATH`；调整 `RRF_K`；换 embedding 模型；BM25 调权 |
| **Answer** | 优化 `ANSWER_SYSTEM` 指令；增加 few-shot 示例；增大 `CHUNK_OVERLAP` |
| **Red Team** | 调整审查严格度；增加/减少检查维度；优化 `RED_TEAM_SYSTEM` |
| **Quality** | 对齐评分标准；明确各分数段含义；与 Red Team 裁决一致 |
| **Reranker** | 换模型 (qwen3-rerank)；调 `top_n`；检查 DashScope 返回分数分布 |
