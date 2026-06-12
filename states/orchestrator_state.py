"""
编排器状态 - 贯穿整个多 Agent 流程的 Pydantic State。
流程: gateway → retrieve → answer → red_team → quality → [refine] → final
"""
from typing import List, Tuple
from typing_extensions import TypedDict

from langchain_core.documents import Document


class OrchestratorState(TypedDict):
    """多 Agent 编排器状态"""
    # 输入
    question: str

    # Gateway
    is_securities: bool
    gateway_reason: str

    # 检索
    documents: List[Tuple[Document, float]]

    # 回答
    answer: str
    answer_sources_text: str

    # 红队评估
    red_team_result: dict       # {has_evidence, possible_hallucination, suggestions, issues}
    red_team_verdict: str       # pass / fail / needs_improvement

    # 质量评估
    quality_score: int          # 1-10
    quality_reason: str
    quality_suggestions: str

    # 精修循环
    refine_count: int           # 当前精修次数
    refine_history: List[dict]  # 精修历史

    # 最终输出
    final_answer: str
    final_defects: str          # 已知缺陷/需要人工确认的地方
