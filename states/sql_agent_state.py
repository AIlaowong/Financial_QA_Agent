"""
SQL Agent 状态 — SQL 查询与结果状态。
"""
from typing import List, Optional
from typing_extensions import TypedDict


class SQLAgentState(TypedDict):
    """SQL Agent 的工作状态"""
    query: str
    sql_statement: str
    sql_result: str
    answer_text: str
    error: str
    tables: List[str]
