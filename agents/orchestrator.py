"""
编排器 - 多 Agent 协同工作的 LangGraph 主控。
流程: gateway → retrieve → answer → red_team → quality → [refine] → final

Agent 角色:
  Gateway  - 证券领域网关，非证券问题拒答
  Retrieve - RAG 检索召回
  Answer   - 基于检索结果生成答案
  Red Team - 审查答案质量（证据/幻觉/完整性）
  Quality  - 10分制质量评分
  Refine   - 根据反馈精修答案（最多2次循环）
"""
import json
import logging
from typing import List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from states.orchestrator_state import OrchestratorState
from prompts.orchestrator_prompts import (
    GATEWAY_SYSTEM, ANSWER_SYSTEM, ANSWER_WITH_FEEDBACK_SYSTEM,
    RED_TEAM_SYSTEM, QUALITY_SYSTEM, FINAL_ANSWER_SYSTEM,
    build_qa_prompt, build_red_team_prompt,
    build_quality_prompt, build_final_prompt,
)
from tools.retriever import BaseRetriever
from tools.document_tools import format_sources, demo_answer
from config import (
    LLM_PROVIDER, OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL,
    RED_TEAM_LLM_MODEL,
    ANTHROPIC_API_KEY, RETRIEVAL_K, MAX_REFINE_LOOPS, QUALITY_THRESHOLD
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """多 Agent 编排器 - 协调 Gateway/Retrieval/Answer/RedTeam/Quality 协作"""

    def __init__(self, retriever: BaseRetriever):
        self.retriever = retriever
        self.llm = self._init_llm(LLM_MODEL)
        self.red_team_llm = self._init_llm(RED_TEAM_LLM_MODEL)
        self.graph = self._build_graph()

    def _init_llm(self, model: str):
        """初始化 LLM，支持按模型区分实例"""
        if LLM_PROVIDER == "anthropic" and ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model or "claude-sonnet-4-6",
                anthropic_api_key=ANTHROPIC_API_KEY, temperature=0,
            )
        elif OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, openai_api_key=OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL, temperature=0,
            )
        else:
            return None

    def _call_llm(self, system: str, user: str, llm=None) -> str:
        """调用 LLM，可指定实例（默认 self.llm）"""
        llm = llm or self.llm
        if llm is None:
            return json.dumps({"error": "DEMO_MODE", "note": "未配置 LLM API Key"})
        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        return llm.invoke(msgs).content.strip()

    def _parse_json(self, text: str, default: dict) -> dict:
        """安全解析 JSON"""
        try:
            # 去除可能的 markdown 包裹
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"JSON 解析失败，使用默认值: {text[:100]}")
            return default

    # ── 构建 LangGraph ──
    def _build_graph(self):
        w = StateGraph(OrchestratorState)

        w.add_node("gateway", self._gateway)
        w.add_node("retrieve", self._retrieve)
        w.add_node("answer", self._answer)
        w.add_node("red_team", self._red_team)
        w.add_node("quality", self._quality)
        w.add_node("final_answer", self._final_answer)

        w.set_entry_point("gateway")

        # Gateway: 非证券→END, 证券→retrieve
        w.add_conditional_edges("gateway", self._route_gateway, {
            "retrieve": "retrieve", "end": END
        })

        w.add_edge("retrieve", "answer")
        w.add_edge("answer", "red_team")
        w.add_edge("red_team", "quality")

        # Quality: 达标→final, 未达标→answer(精修) 或 final(超次)
        w.add_conditional_edges("quality", self._route_quality, {
            "answer": "answer", "final_answer": "final_answer", "end": END
        })

        w.add_edge("final_answer", END)

        return w.compile()

    # ── Gateway Agent ──
    def _gateway(self, state: OrchestratorState) -> dict:
        q = state["question"]
        logger.info(f"[Gateway] 判断: {q[:60]}...")

        resp = self._call_llm(GATEWAY_SYSTEM, f"用户问题: {q}")
        result = self._parse_json(resp, {"is_securities": True, "reason": "默认接受"})

        is_sec = result.get("is_securities", True)
        reason = result.get("reason", "")
        logger.info(f"[Gateway] 判断结果: is_securities={is_sec}, reason={reason}")

        return {
            "is_securities": is_sec,
            "gateway_reason": reason,
        }

    def _route_gateway(self, state: OrchestratorState) -> str:
        if state.get("is_securities", True):
            return "retrieve"
        return "end"

    # ── Retrieve Tool ──
    def _retrieve(self, state: OrchestratorState) -> dict:
        q = state["question"]
        docs = self.retriever.retrieve(q, k=RETRIEVAL_K)
        logger.info(f"[Retrieve] 召回 {len(docs)} 条")

        sources = format_sources(docs)
        return {"documents": docs, "answer_sources_text": sources}

    # ── Answer Tool ──
    def _answer(self, state: OrchestratorState) -> dict:
        q = state["question"]
        sources = state.get("answer_sources_text", "")
        refine_count = state.get("refine_count", 0)

        if not sources.strip():
            return {"answer": "根据提供的文档，无法回答该问题。文档中未找到相关信息。"}

        # 演示模式
        if self.llm is None:
            return {"answer": demo_answer(q, state.get("documents", []))}

        # 精修模式 or 首次回答
        if refine_count > 0:
            system = ANSWER_WITH_FEEDBACK_SYSTEM
            history = state.get("refine_history", [])
            feedback = json.dumps(history[-1] if history else {}, ensure_ascii=False)
            user = (
                f"## 改进建议\n{feedback}\n\n"
                + build_qa_prompt(sources, q)
            )
        else:
            system = ANSWER_SYSTEM
            user = build_qa_prompt(sources, q)

        answer = self._call_llm(system, user)
        logger.info(f"[Answer] 生成 {len(answer)} 字符 (精修={refine_count})")
        return {"answer": answer}

    # ── Red Team Agent (使用独立 LLM: deepseek-v4-pro) ──
    def _red_team(self, state: OrchestratorState) -> dict:
        q = state["question"]
        answer = state.get("answer", "")
        sources = state.get("answer_sources_text", "")

        logger.info(f"[RedTeam] 审查答案... (模型: {RED_TEAM_LLM_MODEL})")
        user = build_red_team_prompt(q, answer, sources)
        resp = self._call_llm(RED_TEAM_SYSTEM, user, llm=self.red_team_llm)

        default = {"has_evidence": True, "possible_hallucination": False,
                   "verdict": "pass", "issues": [], "suggestions": [],
                   "strengths": ["演示模式跳过审查"]}
        result = self._parse_json(resp, default)
        logger.info(f"[RedTeam] 裁决: {result.get('verdict', '?')}")

        return {
            "red_team_result": result,
            "red_team_verdict": result.get("verdict", "pass"),
        }

    # ── Quality Agent ──
    def _quality(self, state: OrchestratorState) -> dict:
        q = state["question"]
        answer = state.get("answer", "")
        rt = state.get("red_team_result", {})
        refine_count = state.get("refine_count", 0)

        logger.info("[Quality] 质量评分...")
        user = build_quality_prompt(q, answer, rt)
        resp = self._call_llm(QUALITY_SYSTEM, user)

        default = {"score": 8, "reason": "演示模式默认评分",
                   "suggestions": ""}
        result = self._parse_json(resp, default)
        score = int(result.get("score", 8))
        logger.info(f"[Quality] 评分: {score}/10")

        # 未达标时，在此处更新精修历史（避免路由函数做状态变更）
        new_refine_count = refine_count
        history = list(state.get("refine_history", []))
        if self.llm is not None and score < QUALITY_THRESHOLD and refine_count < MAX_REFINE_LOOPS:
            new_refine_count = refine_count + 1
            history.append({
                "round": new_refine_count,
                "score": score,
                "issues": rt.get("issues", []),
                "suggestions": result.get("suggestions", ""),
            })
            logger.info(f"[Quality] 未达标，准备第 {new_refine_count} 次精修")

        return {
            "quality_score": score,
            "quality_reason": result.get("reason", ""),
            "quality_suggestions": result.get("suggestions", ""),
            "refine_count": new_refine_count,
            "refine_history": history,
            # 需要精修时清空 answer，触发重新生成
            "answer": "" if new_refine_count > refine_count else answer,
        }

    def _route_quality(self, state: OrchestratorState) -> str:
        score = state.get("quality_score", 0)
        refine_count = state.get("refine_count", 0)

        if self.llm is None:
            return "final_answer"

        if score >= QUALITY_THRESHOLD:
            logger.info(f"[Quality] 达标 ({score}>={QUALITY_THRESHOLD})，进入最终回答")
            return "final_answer"

        if refine_count < MAX_REFINE_LOOPS:
            return "answer"  # 回 Answer 节点精修

        logger.info(f"[Quality] 精修次数已达上限 ({MAX_REFINE_LOOPS})")
        return "final_answer"

    # ── Final Answer ──
    def _final_answer(self, state: OrchestratorState) -> dict:
        q = state["question"]
        answer = state.get("answer", "")
        rt = state.get("red_team_result", {})
        quality = {
            "score": state.get("quality_score", 0),
            "reason": state.get("quality_reason", ""),
        }
        sources = state.get("answer_sources_text", "")

        logger.info("[Final] 生成最终答案...")

        if self.llm is None:
            defects = "[演示模式] 请配置 LLM API Key 启用完整评估"
            return {"final_answer": answer, "final_defects": defects}

        user = build_final_prompt(q, answer, rt, quality, sources)
        final = self._call_llm(FINAL_ANSWER_SYSTEM, user)

        # 生成缺陷说明
        defects_parts = []
        if not rt.get("has_evidence", True):
            defects_parts.append("部分断言缺少文档证据支撑")
        if rt.get("possible_hallucination", False):
            defects_parts.append("可能存在幻觉，建议人工核实")
        if quality.get("score", 10) < 8:
            defects_parts.append(f"质量评分 {quality.get('score')}/10，建议人工复核")
        defects = "; ".join(defects_parts) or "无重大缺陷"

        return {"final_answer": final, "final_defects": defects}

    # ── 对外接口 ──
    def ask(self, question: str) -> dict:
        logger.info(f"开始处理: {question[:80]}")
        state = self.graph.invoke({
            "question": question,
            "is_securities": True,
            "gateway_reason": "",
            "documents": [],
            "answer": "",
            "answer_sources_text": "",
            "red_team_result": {},
            "red_team_verdict": "",
            "quality_score": 0,
            "quality_reason": "",
            "quality_suggestions": "",
            "refine_count": 0,
            "refine_history": [],
            "final_answer": "",
            "final_defects": "",
        })
        return state
