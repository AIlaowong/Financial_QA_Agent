"""
自检 Agent 状态 — 数字验证与相关性检查的状态。
"""
from typing import List, Optional
from typing_extensions import TypedDict


class SelfCheckState(TypedDict):
    """自检查状态"""
    answer: str
    sources_text: str
    numbers_in_answer: List[str]
    numbers_verified: bool
    relevance_score: float
    issues: List[str]
    suggestions: List[str]
