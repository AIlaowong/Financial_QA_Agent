"""
文档工具 - 来源格式化、答案输出格式化、演示模式答案生成。
不依赖 LLM，纯字符串 / Document 操作。
"""
from typing import List, Tuple

from langchain_core.documents import Document


def format_sources(docs_with_scores: List[Tuple[Document, float]]) -> str:
    """将检索结果格式化为 LLM 可读的来源文本"""
    if not docs_with_scores:
        return ""
    parts = []
    for i, (doc, score) in enumerate(docs_with_scores, 1):
        page = doc.metadata.get("page", "?")
        dtype = doc.metadata.get("type", "text")
        label = "[表格]" if dtype == "table" else ""
        parts.append(
            f"【来源{i} 第{page}页 相关度:{score:.3f}】{label}\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


def demo_answer(question: str,
                docs_with_scores: List[Tuple[Document, float]]) -> str:
    """演示模式：将检索结果拼接为答案（无需 LLM）"""
    lines = ["[演示模式 - 未配置 LLM API Key，以下为检索到的相关内容]\n"]
    lines.append(f"问题: {question}\n")
    lines.append("检索到的文档片段:")
    for i, (doc, score) in enumerate(docs_with_scores, 1):
        page = doc.metadata.get("page", "?")
        lines.append(
            f"\n  [{i}] 第{page}页 (相关度: {score:.3f})\n"
            f"      {doc.page_content}"
        )
    lines.append(
        "\n---\n"
        "提示: 配置 .env 中的 OPENAI_API_KEY 即可启用 LLM 智能问答。"
    )
    return "\n".join(lines)


def format_answer(result: dict) -> str:
    """格式化最终输出（问题 + 答案 + 来源 + 自检）"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"[Q] 问题: {result['question']}")
    lines.append("=" * 60)
    lines.append(f"\n[A] 答案:\n{result['answer']}\n")

    # 来源
    lines.append("-" * 60)
    lines.append("[Sources] 来源引用:")
    if result.get("documents"):
        for i, (doc, score) in enumerate(result["documents"], 1):
            page = doc.metadata.get("page", "?")
            dtype = doc.metadata.get("type", "text")
            label = "[Table]" if dtype == "table" else "[T]"
            preview = doc.page_content.replace("\n", " ")
            lines.append(f"  {label} 第{page}页 (相关度:{score:.3f}) {preview}")
    else:
        lines.append("  (无)")

    # 自检
    from tools.self_check_tools import format_self_check_result
    lines.append("\n" + format_self_check_result(result.get("self_check", {})))
    lines.append("=" * 60)
    return "\n".join(lines)


def format_orchestrator_result(state: dict) -> str:
    """格式化多 Agent 编排器的最终输出"""
    lines = []
    lines.append("=" * 60)

    # Gateway
    is_sec = state.get("is_securities", True)
    if not is_sec:
        lines.append(f"[Gateway] 问题不属于证券领域，已拒答")
        lines.append(f"  原因: {state.get('gateway_reason', '')}")
        lines.append("=" * 60)
        return "\n".join(lines)

    lines.append(f"[Q] 问题: {state['question']}")
    lines.append("=" * 60)

    # 答案
    final = state.get("final_answer", "") or state.get("answer", "")
    lines.append(f"\n[A] 答案:\n{final}\n")

    # Gateway
    lines.append(f"[Gateway] 证券领域: {is_sec}")
    lines.append(f"  理由: {state.get('gateway_reason', '')}")

    # 来源
    lines.append(f"\n[Sources] 来源引用 ({len(state.get('documents', []))} 条):")
    for i, (doc, score) in enumerate(state.get("documents", []), 1):
        page = doc.metadata.get("page", "?")
        preview = doc.page_content[:100].replace("\n", " ")
        lines.append(f"  [{i}] 第{page}页 (相关度:{score:.3f}) {preview}...")

    # 红队
    rt = state.get("red_team_result", {})
    lines.append(f"\n[RedTeam] 红队审查:")
    lines.append(f"  裁决: {state.get('red_team_verdict', '?')}")
    if rt.get("issues"):
        lines.append(f"  问题: {'; '.join(rt['issues'])}")
    if rt.get("suggestions"):
        lines.append(f"  建议: {'; '.join(rt['suggestions'])}")

    # 质量
    lines.append(f"\n[Quality] 质量评估:")
    lines.append(f"  评分: {state.get('quality_score', '?')}/10")
    lines.append(f"  原因: {state.get('quality_reason', '')}")
    lines.append(f"  精修次数: {state.get('refine_count', 0)}")

    # 缺陷
    defects = state.get("final_defects", "")
    if defects:
        lines.append(f"\n[!] 需人工确认:")
        lines.append(f"  {defects}")

    lines.append("=" * 60)
    return "\n".join(lines)
