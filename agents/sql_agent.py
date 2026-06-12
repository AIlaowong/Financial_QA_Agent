"""
SQL Agent — 使用 LangChain 原生 create_sql_agent 查询表格数据库。

Agent 可自主:
  - 列出所有表 (sql_db_list_tables)
  - 查看表结构 (sql_db_schema)
  - 执行 SELECT 查询 (sql_db_query)
  - 查询出错时自动修正 SQL

流程: 自然语言问题 → Agent 多步探索 → SQL → 结构化结果
"""
import logging
import re
from typing import List, Tuple, Optional

from langchain_core.documents import Document
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from prompts.sql_agent_prompts import SQL_AGENT_SYSTEM
from config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL, DATA_DB_DIR

logger = logging.getLogger(__name__)


class SQLAgentRetriever:
    """LangChain SQL Agent — 使用原生 Agent 框架查询表格数据库"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DATA_DB_DIR / "tables.db")
        self.db: Optional[SQLDatabase] = None
        self.agent = None

    def build(self, table_infos: List = None) -> None:
        """初始化数据库和 Agent"""
        import os
        if not os.path.exists(self.db_path):
            logger.warning(f"数据库不存在: {self.db_path}")
            return

        self.db = SQLDatabase.from_uri(f"sqlite:///{self.db_path}")
        if not OPENAI_API_KEY:
            logger.warning("无 API Key，SQL Agent 不可用")
            return

        llm = ChatOpenAI(
            model=LLM_MODEL, openai_api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL, temperature=0,
        )

        toolkit = SQLDatabaseToolkit(db=self.db, llm=llm)
        tools = toolkit.get_tools()

        safe_tools = [t for t in tools if t.name in (
            "sql_db_list_tables", "sql_db_schema", "sql_db_query"
        )]

        self.agent = create_react_agent(
            model=llm,
            tools=safe_tools,
            prompt=SQL_AGENT_SYSTEM,
        )

        table_count = len(self.db.get_usable_table_names())
        logger.info(f"[SQL Agent] 就绪 ({table_count} 表, {len(safe_tools)} 工具)")

    def retrieve(self, query: str, k: int = 3) -> List[Tuple[Document, float]]:
        """Agent 自主探索 → 生成 SQL → 执行 → 返回结构化结果"""
        if self.agent is None or self.db is None:
            return []

        try:
            result = self.agent.invoke({
                "messages": [{"role": "user", "content": query}]
            })

            messages = result.get("messages", [])
            if not messages:
                return []

            sql_used = self._extract_sql_from_messages(messages)
            answer_text = self._extract_query_results(messages)

            if not answer_text or len(answer_text) < 10:
                return []

            doc = Document(
                page_content=f"[SQL Agent]\n问题: {query}\n"
                             f"{'SQL: ' + sql_used + chr(10) if sql_used else ''}"
                             f"结果:\n{answer_text}",
                metadata={
                    "source": "sql_agent",
                    "type": "sql_agent",
                    "sql": sql_used or "",
                    "page": self._extract_page_from_sql(sql_used or ""),
                }
            )
            logger.info(f"[SQL Agent] 命中 ({len(answer_text)} 字符)")
            return [(doc, 1.0)]

        except Exception as e:
            logger.warning(f"[SQL Agent] 查询失败: {e}")
            return []

    def _extract_query_results(self, messages) -> str:
        """从 Agent messages 中提取最终答案"""
        for msg in reversed(messages):
            type_name = type(msg).__name__
            if type_name == "AIMessage":
                content = str(msg.content) if hasattr(msg, 'content') else str(msg)
                content = content.strip()
                if content and len(content) > 20:
                    return content

        data_parts = []
        for msg in reversed(messages):
            if type(msg).__name__ == "ToolMessage":
                c = str(msg.content).strip() if hasattr(msg, 'content') else str(msg)
                if len(c) > 50:
                    data_parts.append(c)
                if len(data_parts) >= 2:
                    break
        return "\n\n".join(reversed(data_parts)) if data_parts else ""

    def _extract_sql_from_messages(self, messages) -> str:
        """从 Agent 的 messages 中提取执行的 SQL"""
        for msg in messages:
            content = msg.content if hasattr(msg, 'content') else str(msg)
            match = re.search(
                r'(SELECT\s+.*?(?:;|$))', content, re.IGNORECASE | re.DOTALL
            )
            if match:
                sql = match.group(1).strip().rstrip(";")
                if len(sql) > 20:
                    return sql
        return ""

    def _extract_page_from_sql(self, sql: str) -> int:
        """从 SQL 语句推断涉及的页码"""
        match = re.search(r't_(\d+)', sql)
        if match:
            return int(match.group(1)) + 1
        return 0

    def validate_query(self, query: str, answer: str) -> dict:
        """校验 Agent 回答质量"""
        result = {"valid": True, "issues": [], "warnings": []}
        if not answer or len(answer) < 10:
            result["valid"] = False
            result["issues"].append("Agent 未返回有效回答")
            return result
        if "error" in answer.lower() and "sql" in answer.lower():
            result["warnings"].append("回答中包含 SQL 错误信息")
        if "没有" in answer or "不存在" in answer or "未找到" in answer:
            result["warnings"].append("Agent 认为无相关数据")
        return result
