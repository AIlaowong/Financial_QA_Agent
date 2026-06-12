"""
RAG Agent 状态 — 简易 RAG 流程的状态定义。
"""
from typing import List, Tuple, Optional
from typing_extensions import TypedDict

from langchain_core.documents import Document


class RAGState(TypedDict):
    """简易 RAG Agent 工作状态"""
    question: str
    documents: List[Tuple[Document, float]]
    answer: str
    self_check: dict
    is_securities: Optional[bool]
    gateway_reason: str
