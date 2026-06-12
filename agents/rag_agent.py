"""
简易 RAG Agent — 检索 → 生成 → 自检 三步流程。
作为备选方案保留，当前主流程使用 agents.orchestrator.Orchestrator。

State: states.rag_state.RAGState
Prompts: prompts.rag_prompts.SYSTEM_PROMPT, build_qa_prompt
SelfCheck: agents.self_check_agent.AnswerChecker
"""
import logging
from typing import List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from states.rag_state import RAGState
from prompts.rag_prompts import SYSTEM_PROMPT, build_qa_prompt
from agents.self_check_agent import AnswerChecker
from config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)


class RAGAgent:
    """简易 RAG Agent — 替代方案，不依赖多 Agent 编排"""

    def __init__(self, retriever):
        self.retriever = retriever
        self._llm = None
        self.checker = AnswerChecker()

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

    def ask(self, question: str) -> dict:
        """完整 QA 流程"""
        from langgraph.graph import StateGraph, END

        workflow = StateGraph(RAGState)

        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("generate", self._generate)
        workflow.add_node("self_check", self._do_self_check)

        workflow.set_entry_point("retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "self_check")
        workflow.add_edge("self_check", END)

        app = workflow.compile()
        state = app.invoke({"question": question, "documents": [], "answer": "", "self_check": {}})

        return {
            "question": question,
            "answer": state.get("answer", ""),
            "documents": state.get("documents", []),
            "self_check": state.get("self_check", {}),
        }

    def _retrieve(self, state: RAGState) -> dict:
        """检索召回"""
        docs = self.retriever.retrieve(state["question"])
        return {"documents": docs}

    def _generate(self, state: RAGState) -> dict:
        """生成答案"""
        llm = self._get_llm()
        docs = state.get("documents", [])

        sources_text = "\n---\n".join(doc.page_content for doc, _ in docs) if docs else "(无相关文档)"

        if not llm:
            # 演示模式
            return {"answer": f"[演示模式] 检索到 {len(docs)} 条文档片段，配置 API Key 后启用 LLM 生成"}

        prompt = build_qa_prompt(state["question"], sources_text)
        msg = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return {"answer": msg.content}

    def _do_self_check(self, state: RAGState) -> dict:
        """自检验证"""
        answer = state.get("answer", "")
        docs = state.get("documents", [])
        sources_text = "\n---\n".join(doc.page_content for doc, _ in docs)

        check_result = self.checker.check(answer, sources_text)
        return {"self_check": check_result}
