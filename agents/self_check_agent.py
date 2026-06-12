"""
自检 Agent — 对生成的答案进行数字回溯验证和来源相关性检查。

State: states.self_check_state.SelfCheckState
"""
import logging
from typing import List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from states.self_check_state import SelfCheckState
from tools.self_check_tools import check_numbers_in_sources, check_source_relevance
from config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

SELF_CHECK_SYSTEM = """你是一个严格的答案审核专家。请检查以下答案的质量:

1. 答案是否完全基于提供的文档内容？
2. 是否有编造的数据或事实？
3. 答案是否完整回答了问题？
4. 财务数字和单位是否正确？

输出 JSON 格式:
{
  "is_accurate": true/false,
  "has_hallucination": true/false,
  "completeness": 0-10,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1", "建议2"]
}"""


class AnswerChecker:
    """答案自检器 — 数字验证 + LLM 审核"""

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None and OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL,
                model=LLM_MODEL,
                temperature=0,
            )
        return self._llm

    def check(self, answer: str, sources_text: str) -> dict:
        """对答案进行全面检查"""
        # 1. 数字回溯验证
        number_check = check_numbers_in_sources(answer, sources_text)

        # 2. 来源相关性
        relevance = check_source_relevance(answer, sources_text)

        result = {
            "numbers_in_answer": number_check.get("numbers_in_answer", []),
            "verified": number_check.get("verified", []),
            "unverified": number_check.get("unverified", []),
            "all_verified": number_check.get("all_verified", False),
            "relevance_score": relevance,
            "issues": [],
            "suggestions": [],
        }

        # 3. 数字未回溯标记
        if number_check.get("unverified"):
            result["issues"].append(
                f"以下数字未在文档中找到: {', '.join(number_check['unverified'])}"
            )
            result["suggestions"].append("请核实这些数字的来源或移除")

        if relevance < 0.3:
            result["issues"].append("答案与来源文档相关性低，可能偏离原文")
            result["suggestions"].append("请更密切地基于文档内容回答")

        # 4. LLM 审核
        llm = self._get_llm()
        if llm:
            try:
                import json
                prompt = f"""请审查以下答案:

## 来源文档
{sources_text[:2000]}

## 待审查答案
{answer}"""
                msg = llm.invoke([
                    SystemMessage(content=SELF_CHECK_SYSTEM),
                    HumanMessage(content=prompt),
                ])
                llm_result = json.loads(msg.content)
                if not llm_result.get("is_accurate", True):
                    result["issues"].extend(llm_result.get("issues", []))
                result["suggestions"].extend(llm_result.get("suggestions", []))
                result["llm_accurate"] = llm_result.get("is_accurate", True)
                result["llm_completeness"] = llm_result.get("completeness", 10)
            except Exception as e:
                logger.warning(f"LLM 审核失败: {e}")

        return result
