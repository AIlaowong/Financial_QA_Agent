"""
测试评估脚本 — 并发运行全部测试问题，捕获每个 Agent 的中间状态，生成结构化结果。
用法: python tests/run_evaluation.py [--concurrency N]
输出: test_data_result/test_results_{timestamp}.json
"""
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)
_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def load_test_dataset() -> List[Dict]:
    path = Path(__file__).parent / "test_dataset.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def capture_agent_states(state: Dict, question: Dict) -> Dict:
    """从 Orchestrator 全量状态中提取每个 Agent 的关键输出"""
    docs = state.get("documents", [])
    check_pts = question.get("check_points", [])
    answer = state.get("final_answer", "") or state.get("answer", "")

    return {
        "gateway": {
            "is_securities": state.get("is_securities"),
            "reason": state.get("gateway_reason", ""),
        },
        "retrieve": {
            "document_count": len(docs),
            "best_score": max((s for _, s in docs), default=0),
            "documents": [
                {
                    "page": doc.metadata.get("page", "?"),
                    "score": round(score, 4),
                    "type": doc.metadata.get("type", doc.metadata.get("source", "?")),
                    "preview": doc.page_content.replace("\n", " "),
                }
                for doc, score in docs
            ],
        },
        "answer": {
            "answer": answer,
            "check_point_hits": {cp: cp in answer for cp in check_pts},
            "hit_count": sum(1 for cp in check_pts if cp in answer),
            "total_checks": len(check_pts),
        },
        "red_team": {
            "verdict": state.get("red_team_verdict", ""),
            "has_evidence": state.get("red_team_result", {}).get("has_evidence"),
            "possible_hallucination": state.get("red_team_result", {}).get("possible_hallucination"),
            "issues": state.get("red_team_result", {}).get("issues", []),
            "suggestions": state.get("red_team_result", {}).get("suggestions", []),
            "strengths": state.get("red_team_result", {}).get("strengths", []),
        },
        "quality": {
            "score": state.get("quality_score", 0),
            "reason": state.get("quality_reason", ""),
        },
        "refine": {
            "count": state.get("refine_count", 0),
            "history": [
                {"round": h.get("round"), "score": h.get("score")}
                for h in state.get("refine_history", [])
            ],
        },
        "final": {
            "defects": state.get("final_defects", ""),
        },
    }


def evaluate_agent_metrics(agent_states: Dict, metrics: Dict) -> List[Dict]:
    """根据每个 Agent 的预期指标评估通过/失败"""
    results = []

    # Gateway
    gw = metrics.get("gateway", {})
    if "expect_securities" in gw:
        actual = agent_states["gateway"]["is_securities"]
        results.append({
            "agent": "gateway",
            "metric": "is_securities",
            "expected": gw["expect_securities"],
            "actual": actual,
            "passed": actual == gw["expect_securities"],
        })

    # Retrieve
    rt = metrics.get("retrieve", {})
    if "expect_min_docs" in rt:
        actual = agent_states["retrieve"]["document_count"]
        passed = actual >= rt["expect_min_docs"] if rt["expect_min_docs"] > 0 else actual >= 0
        results.append({
            "agent": "retrieve",
            "metric": "min_docs",
            "expected": f">= {rt['expect_min_docs']}",
            "actual": actual,
            "passed": passed,
        })
    if rt.get("expect_sql"):
        has_sql = any(d["type"] == "sql_agent" for d in agent_states["retrieve"]["documents"])
        results.append({
            "agent": "retrieve",
            "metric": "sql_hit",
            "expected": True,
            "actual": has_sql,
            "passed": has_sql,
        })

    # Answer: Gateway 拒答时 answer 为空，视为拒绝
    ans = metrics.get("answer", {})
    if "expect_refuse" in ans:
        answer_text = agent_states["answer"]["answer"]
        is_gateway_reject = agent_states["gateway"]["is_securities"] is False
        is_refusing = is_gateway_reject or any(w in answer_text for w in ["无法回答", "未找到", "没有相关", "不包含"])
        results.append({
            "agent": "answer",
            "metric": "refuse",
            "expected": ans["expect_refuse"],
            "actual": is_refusing,
            "passed": is_refusing == ans["expect_refuse"],
        })

    # Red Team
    rtm = metrics.get("red_team", {})
    if "expect_evidence" in rtm:
        results.append({
            "agent": "red_team",
            "metric": "has_evidence",
            "expected": rtm["expect_evidence"],
            "actual": agent_states["red_team"]["has_evidence"],
            "passed": agent_states["red_team"]["has_evidence"] == rtm["expect_evidence"],
        })

    # Quality
    qm = metrics.get("quality", {})
    if "expect_min_score" in qm:
        actual = agent_states["quality"]["score"]
        results.append({
            "agent": "quality",
            "metric": "min_score",
            "expected": f">= {qm['expect_min_score']}",
            "actual": actual,
            "passed": actual >= qm["expect_min_score"],
        })

    return results


def run_one_question(agent, q: Dict, idx: int, total: int) -> Dict:
    """运行单个测试问题（线程安全）"""
    safe_print(f"\n[{'─' * 48}]")
    safe_print(f"[{idx}/{total}] {q['category']}: {q['question']}...")
    start = time.time()

    try:
        state = agent.ask(q["question"])
    except Exception as e:
        elapsed = time.time() - start
        safe_print(f"  [ERROR] {e} ({elapsed:.1f}s)")
        return {
            "test_id": q["id"], "category": q["category"],
            "question": q["question"], "passed": False,
            "error": str(e), "agents": {},
            "elapsed_sec": round(elapsed, 1),
            "per_agent_metrics": [],
        }

    elapsed = time.time() - start

    agent_states = capture_agent_states(state, q)
    metrics_eval = evaluate_agent_metrics(agent_states, q.get("agent_metrics", {}))

    all_metrics_pass = all(m["passed"] for m in metrics_eval)
    check_hits = agent_states["answer"]["hit_count"]
    check_total = agent_states["answer"]["total_checks"]
    checks_pass = check_total == 0 or check_hits >= check_total * 0.5
    overall_pass = all_metrics_pass and checks_pass

    status = "[OK] PASS" if overall_pass else "[FAIL]"
    safe_print(f"  {status} ({elapsed:.1f}s)")
    for m in metrics_eval:
        flag = "[v]" if m["passed"] else "[x]"
        safe_print(f"    {flag} {m['agent']}.{m['metric']}: "
                   f"expect={m['expected']} actual={m['actual']}")

    return {
        "test_id": q["id"],
        "category": q["category"],
        "question": q["question"],
        "expected_type": q["expected_type"],
        "check_points": q["check_points"],
        "elapsed_sec": round(elapsed, 1),
        "passed": overall_pass,
        "per_agent_metrics": metrics_eval,
        "agents": agent_states,
    }


def run_evaluation(agent_factory, concurrency: int = 8) -> None:
    """并发运行完整评估，保存包含所有 Agent 中间状态的测试结果"""
    questions = load_test_dataset()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("\n" + "=" * 60)
    print(f"  Agent 全链路测试评估 — {len(questions)} 题 (并发数: {concurrency})")
    print("=" * 60)

    total_start = time.time()
    results_by_id = {}
    total = len(questions)

    with ThreadPoolExecutor(max_workers=min(concurrency, total)) as pool:
        futures = {}
        for i, q in enumerate(questions, 1):
            agent = agent_factory()
            future = pool.submit(run_one_question, agent, q, i, total)
            futures[future] = q["id"]

        for future in as_completed(futures):
            result = future.result()
            results_by_id[result["test_id"]] = result

    total_elapsed = time.time() - total_start

    # 按 test_id 排序
    results = [results_by_id[q["id"]] for q in questions]

    passed_count = sum(1 for r in results if r["passed"])

    # ── 汇总报告 ──
    print("\n" + "=" * 60)
    print("  汇总报告")
    print("=" * 60)
    print(f"  总题数:          {total}")
    print(f"  通过:            {passed_count}")
    print(f"  失败:            {total - passed_count}")
    print(f"  通过率:          {passed_count / total * 100:.1f}%")
    print(f"  总耗时(并发):    {total_elapsed:.1f}s")
    avg_serial = sum(r.get("elapsed_sec", 0) for r in results)
    print(f"  串行等效耗时:    {avg_serial:.1f}s")
    print(f"  加速比:          {avg_serial / total_elapsed:.1f}x")

    # 按 Agent 汇总
    agent_stats = {}
    for r in results:
        for m in r.get("per_agent_metrics", []):
            agent = m["agent"]
            if agent not in agent_stats:
                agent_stats[agent] = {"total": 0, "passed": 0}
            agent_stats[agent]["total"] += 1
            if m["passed"]:
                agent_stats[agent]["passed"] += 1

    print("\n  Agent 维度统计:")
    for agent, stats in agent_stats.items():
        rate = stats["passed"] / stats["total"] * 100
        print(f"    {agent}: {stats['passed']}/{stats['total']} ({rate:.0f}%)")

    # 按类别
    cat_stats = {}
    for r in results:
        cat = r["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "passed": 0}
        cat_stats[cat]["total"] += 1
        if r["passed"]:
            cat_stats[cat]["passed"] += 1

    print("\n  类别统计:")
    for cat, stats in cat_stats.items():
        print(f"    {cat}: {stats['passed']}/{stats['total']}")

    # 保存结果
    from config import TEST_RESULT_DIR
    TEST_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = TEST_RESULT_DIR / f"test_results_{timestamp}.json"

    report = {
        "timestamp": timestamp,
        "concurrency": concurrency,
        "summary": {
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": f"{passed_count / total * 100:.1f}%",
            "total_time_sec": round(total_elapsed, 1),
            "serial_equivalent_sec": round(avg_serial, 1),
            "speedup": round(avg_serial / total_elapsed, 1),
            "agent_stats": agent_stats,
            "category_stats": {cat: {"passed": s["passed"], "total": s["total"]}
                              for cat, s in cat_stats.items()},
        },
        "results": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 列出 badcase
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\n  [!] Badcase ({len(failures)} 题):")
        for f in failures:
            failed_agents = [m["agent"] for m in f.get("per_agent_metrics", [])
                            if not m["passed"]]
            print(f"    #{f['test_id']} {f['category']}: "
                  f"失败 Agent = {failed_agents}")

    print(f"\n  完整结果已保存: {output_path}")
    print(f"  评估指南: tests/EVALUATION_GUIDE.md")
