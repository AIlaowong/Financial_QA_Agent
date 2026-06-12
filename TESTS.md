# 测试说明

## 运行测试

```bash
# 默认 8 线程并发
python test.py

# 指定并发数
python test.py --concurrency 4

# 仅验证模块导入（免 API）
python test.py --skip-api
```

结果输出到 `test_data_result/test_results_{timestamp}.json`。

## 测试问题覆盖（`tests/test_dataset.json`）

| 类别 | 示例 | 验证点 |
|------|------|--------|
| 正文理解 | 财务数据覆盖哪个时间段？ | 关键日期命中 |
| 表格查询 | Sino-Ocean 账面价值？ | 数字精确匹配 |
| 综合收益 | 归属于母公司的综合收益期末余额？ | 财务指标命中 |
| 金融风险 | 3个月内到期的金融负债金额？ | 表项定位准确 |
| 无答案 | 员工总数是多少？ | 是否正确拒答 |
| 模糊问题 | 投资情况怎么样？ | 概括回答 + 来源 |
| Gateway 拒答 | 今天天气怎么样？ | 非证券问题拒答 |
| 精修循环 | 质量评分 < 8 时自动触发 | 验证循环次数 ≤ 2 |

## 评估维度

每个 Agent 环节的评估指标：

| Agent | 评估方案 | 指标 |
|-------|----------|------|
| Gateway | 测试集含证券/非证券各半 | 召回率/精确率 |
| Retrieve | min_docs + sql_hit | 最佳得分 ≥ 0.1，表格题有 SQL 命中 |
| Answer | 关键点命中 + 拒答判断 | check_points 命中率 ≥ 50% |
| Red Team | 证据判定 | has_evidence 与预期一致 |
| Quality | 评分阈值 | score ≥ expect_min_score |
| Refine | 循环次数 | ≤ 2 且评分递增 |

## 测试结果 JSON 结构

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
    "agent_stats": {"gateway": {"total": 8, "passed": 8}},
    "category_stats": {"正文理解": {"passed": 1, "total": 1}}
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
        "gateway": {"is_securities": true, "reason": "涉及公司账面价值查询..."},
        "retrieve": {
          "document_count": 5, "best_score": 0.8674,
          "documents": [{"page": 0, "score": 1.0, "type": "sql_agent", "preview": "..."}]
        },
        "answer": {"answer": "...", "check_point_hits": {"7.16": true}, "hit_count": 1, "total_checks": 1},
        "red_team": {"verdict": "pass", "has_evidence": true, "possible_hallucination": false, "issues": [], "suggestions": [], "strengths": []},
        "quality": {"score": 8, "reason": "答案准确..."},
        "refine": {"count": 0, "history": []},
        "final": {"defects": "金额单位未明确标注"}
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
| `summary` | object | 汇总报告 |
| `results` | array | 每道题的详细测试结果 |

### summary 汇总报告

| 字段 | 说明 |
|------|------|
| `total` | 总题数 |
| `passed` | 通过数 |
| `failed` | 失败数 |
| `pass_rate` | 通过率 (百分比字符串) |
| `total_time_sec` | 并发总耗时 (秒) |
| `serial_equivalent_sec` | 串行等效耗时 (秒) |
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
| `per_agent_metrics` | array | 每个 Agent 的指标评估结果 |
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

#### Gateway

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_securities` | bool | 是否证券领域问题 |
| `reason` | string | 判断理由 |

#### Retrieve

| 字段 | 类型 | 说明 |
|------|------|------|
| `document_count` | int | 召回文档总数 |
| `best_score` | float | 最佳相关度得分 |
| `documents` | array | 召回文档列表，每项含 `page` / `score` / `type` / `preview` |

#### Answer

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer` | string | 最终生成的答案文本 |
| `check_point_hits` | object | 各检查点是否命中 `{"关键词": true/false}` |
| `hit_count` | int | 命中的检查点数 |
| `total_checks` | int | 检查点总数 |

#### Red Team

| 字段 | 类型 | 说明 |
|------|------|------|
| `verdict` | string | 裁决：`pass` / `needs_improvement` / `fail` |
| `has_evidence` | bool | 答案是否有文档证据支撑 |
| `possible_hallucination` | bool | 是否存在可能的幻觉 |
| `issues` | string[] | 发现的问题列表 |
| `suggestions` | string[] | 改进建议列表 |
| `strengths` | string[] | 红队认可的答案优点 |

#### Quality

| 字段 | 类型 | 说明 |
|------|------|------|
| `score` | int | 质量评分 (1-10) |
| `reason` | string | 评分理由 |

#### Refine

| 字段 | 类型 | 说明 |
|------|------|------|
| `count` | int | 精修次数 |
| `history` | array | 精修历史 `[{"round": N, "score": S}]` |

#### Final

| 字段 | 类型 | 说明 |
|------|------|------|
| `defects` | string | 需人工确认的缺陷说明 |

## 如何定位 Badcase

### Step 1：按 passed 过滤

```bash
# 只看失败的
cat test_data_result/test_results_xxx.json | jq '.results[] | select(.passed == false)'
```

### Step 2：逐 Agent 排查

从上往下查 Agent 链路：
1. **Gateway 误拒？** → `agents.gateway.is_securities`
2. **检索没召回？** → `agents.retrieve.document_count == 0` 或 `best_score < 0.1`
3. **答案缺关键点？** → 对比 `agents.answer.check_point_hits`
4. **SQL 没命中？** → `per_agent_metrics` 中 `sql_hit.passed`
5. **红队误判？** → `agents.red_team.verdict == "fail"` 但实际答案正确
6. **评分过低？** → `agents.quality.score < 5`

### Step 3：定位根因

```
答案缺关键点 → 检索没召回 → 关键词不匹配？
  → 检查 BM25 tokenization / embedding 模型覆盖

红队误判 → prompt 太严格？
  → 调整 RED_TEAM_SYSTEM 评估原则

评分和红队矛盾 → 标准不一致？
  → 对齐 QUALITY_SYSTEM 和 RED_TEAM_SYSTEM

精修无效 → feedback 没注入关键信息？
  → 检查 _answer 中 feedback 拼接逻辑
```

## Agent 优化速查

| Agent | 优化手段 |
|-------|----------|
| **Gateway** | 调整 `GATEWAY_SYSTEM` 判断边界；增加模糊词容忍度 |
| **Retrieve** | 调大 `RECALL_PER_PATH`；调整 `RRF_K`；换 embedding 模型；BM25 调权 |
| **Answer** | 优化 `ANSWER_SYSTEM` 指令；增加 few-shot 示例；增大 `CHUNK_OVERLAP` |
| **Red Team** | 调整审查严格度；增加/减少检查维度；优化 `RED_TEAM_SYSTEM` |
| **Quality** | 对齐评分标准；明确各分数段含义；与 Red Team 裁决一致 |
| **Reranker** | 换模型 (qwen3-rerank)；调 `top_n`；检查 DashScope 返回分数分布 |
