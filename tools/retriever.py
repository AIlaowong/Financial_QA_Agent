"""
检索模块 — 3路召回 + RRF 融合 + Reranker 精排。

召回通路:
  1. BM25          (关键词, 免API)
  2. Dense Embed   (qwen3-embedding-8b, 稠密向量)
  3. Sparse Embed  (text-embedding-3-small, 稀疏向量)

融合: RRF (Reciprocal Rank Fusion)
精排: qwen3-reranker-8b
"""
import json
import logging
import pickle
import time
from typing import List, Tuple, Dict
from abc import ABC, abstractmethod

import numpy as np
from langchain_core.documents import Document
from sklearn.metrics.pairwise import cosine_similarity

from config import (
    OPENAI_API_KEY, OPENAI_BASE_URL, DATA_DB_DIR,
    DENSE_EMBEDDING_MODEL, SPARSE_EMBEDDING_MODEL, RERANKER_MODEL,
    RECALL_PER_PATH, RRF_TOP_K, RRF_K, RERANK_TOP_K, RETRIEVAL_K,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# 分词工具
# ═══════════════════════════════════════════

def _jieba_tokenize(text: str) -> List[str]:
    """结巴分词"""
    import jieba
    return [t.strip() for t in jieba.lcut(text) if t.strip()]


def _call_embedding_api(texts: List[str], model: str) -> np.ndarray:
    """调用 OpenAI 兼容的 embedding API，返回 numpy 矩阵"""
    from openai import OpenAI as OpenAIClient
    client = OpenAIClient(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    resp = client.embeddings.create(model=model, input=texts)
    return np.array([e.embedding for e in resp.data], dtype=np.float32)


def _call_reranker_api(query: str, docs: List[str], model: str) -> List[float]:
    """
    调用阿里云 DashScope Reranker API 对 (query, doc) 批量打分。
    API: https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
    """
    import requests
    from config import DASHSCOPE_API_KEY

    if not DASHSCOPE_API_KEY:
        logger.warning("无 DASHSCOPE_API_KEY，Reranker 不可用")
        return [0.5] * len(docs)

    url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "input": {
            "query": query,
            "documents": docs,
        },
        "parameters": {
            "top_n": len(docs),
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        # DashScope 返回结构: {"output": {"results": [{"index": 0, "relevance_score": 0.9}, ...]}}
        results = result.get("output", {}).get("results", [])
        if not results:
            return [0.5] * len(docs)

        # 按 index 排序，确保与输入 docs 顺序一致
        score_map = {r["index"]: r.get("relevance_score", 0.5) for r in results}
        scores = [score_map.get(i, 0.5) for i in range(len(docs))]
        return scores

    except Exception as e:
        logger.warning(f"DashScope Reranker 失败: {e}")
        return [0.5] * len(docs)


# ═══════════════════════════════════════════
# 检索器基类
# ═══════════════════════════════════════════

class BaseRetriever(ABC):
    @abstractmethod
    def build(self, documents: List[Document]) -> None: ...

    @abstractmethod
    def retrieve(self, query: str, k: int = RETRIEVAL_K) -> List[Tuple[Document, float]]: ...


# ═══════════════════════════════════════════
# 1. BM25 检索器 (关键词, 免API)
# ═══════════════════════════════════════════

class BM25Retriever(BaseRetriever):
    """基于 BM25 的关键词检索（免 API，中文分词）"""

    def __init__(self):
        self.documents: List[Document] = []
        self.bm25 = None
        self.tokenized_corpus: List[List[str]] = []

    def build(self, documents: List[Document]) -> None:
        from rank_bm25 import BM25Okapi
        self.documents = documents
        self.tokenized_corpus = [_jieba_tokenize(d.page_content) for d in documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        logger.info(f"BM25 索引构建完成: {len(documents)} 文档")

    def retrieve(self, query: str, k: int = RECALL_PER_PATH) -> List[Tuple[Document, float]]:
        if not self.bm25:
            return []
        tokenized_query = _jieba_tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        # 归一化到 [0, 1]
        max_score = scores.max()
        if max_score > 0:
            scores = scores / max_score
        top_idx = np.argsort(scores)[::-1][:k]
        return [(self.documents[i], float(scores[i]))
                for i in top_idx if scores[i] > 0]

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump((self.documents, self.tokenized_corpus), f)

    def load(self, path: str) -> None:
        from rank_bm25 import BM25Okapi
        with open(path, "rb") as f:
            self.documents, self.tokenized_corpus = pickle.load(f)
        self.bm25 = BM25Okapi(self.tokenized_corpus)


# ═══════════════════════════════════════════
# 2. Embedding 检索器 (Dense / Sparse)
# ═══════════════════════════════════════════

class EmbeddingRetriever(BaseRetriever):
    """基于 Embedding 的语义检索，支持任意 OpenAI 兼容模型"""

    def __init__(self, model: str, label: str = "embed"):
        self.model = model
        self.label = label
        self.documents: List[Document] = []
        self.embeddings: np.ndarray = None  # shape: (n_docs, dim)

    def build(self, documents: List[Document]) -> None:
        self.documents = documents
        if not OPENAI_API_KEY:
            logger.warning(f"[{self.label}] 无 API Key，跳过 embedding 构建")
            return

        texts = [d.page_content for d in documents]
        batch_size = 20
        all_embs = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                embs = _call_embedding_api(batch, self.model)
                all_embs.append(embs)
            except Exception as e:
                logger.warning(f"[{self.label}] Embedding 失败 (batch {i}): {e}")
                # 失败时填充零向量
                dim = all_embs[0].shape[1] if all_embs else 1024
                all_embs.append(np.zeros((len(batch), dim), dtype=np.float32))

        if all_embs:
            self.embeddings = np.vstack(all_embs)
            logger.info(f"[{self.label}] Embedding 构建完成: {len(documents)} 文档, "
                        f"维度={self.embeddings.shape[1]}")
        else:
            self.embeddings = np.zeros((len(documents), 1), dtype=np.float32)

    def retrieve(self, query: str, k: int = RECALL_PER_PATH) -> List[Tuple[Document, float]]:
        if self.embeddings is None or self.embeddings.shape[1] <= 1:
            return []

        try:
            q_emb = _call_embedding_api([query], self.model)
            scores = cosine_similarity(q_emb, self.embeddings).flatten()
            top_idx = np.argsort(scores)[::-1][:k]
            return [(self.documents[i], float(scores[i]))
                    for i in top_idx if scores[i] > 0]
        except Exception as e:
            logger.warning(f"[{self.label}] 检索失败: {e}")
            return []

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump((self.documents, self.embeddings), f)

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            self.documents, self.embeddings = pickle.load(f)


# ═══════════════════════════════════════════
# 3. RRF 融合
# ═══════════════════════════════════════════

def _rrf_fusion(results_per_path: List[List[Tuple[Document, float]]],
                k: int = RRF_K, top_k: int = RRF_TOP_K) -> List[Tuple[Document, float]]:
    """
    Reciprocal Rank Fusion — 融合多路检索结果。
    RRF_score(d) = sum( 1 / (k + rank_i(d)) ) 对所有路径 i
    """
    doc_scores: Dict[str, float] = {}    # key = doc unique id (page_content[:80])
    doc_map: Dict[str, Document] = {}

    for path_results in results_per_path:
        for rank, (doc, _) in enumerate(path_results, start=1):
            key = doc.page_content[:80]  # 用前80字符作为唯一标识
            doc_map[key] = doc
            doc_scores[key] = doc_scores.get(key, 0.0) + 1.0 / (k + rank)

    # 按 RRF 得分排序
    sorted_items = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    return [(doc_map[key], score) for key, score in sorted_items[:top_k]]


# ═══════════════════════════════════════════
# 4. Reranker 精排
# ═══════════════════════════════════════════

class Reranker:
    """使用 qwen3-reranker-8b 对候选文档精排"""

    def __init__(self, model: str = None):
        self.model = model or RERANKER_MODEL

    def rerank(self, query: str,
               candidates: List[Tuple[Document, float]],
               top_k: int = RERANK_TOP_K) -> List[Tuple[Document, float]]:
        """对候选文档重排序"""
        if not OPENAI_API_KEY or len(candidates) <= 1:
            return candidates[:top_k]

        docs = [doc.page_content for doc, _ in candidates]
        try:
            start = time.time()
            scores = _call_reranker_api(query, docs, self.model)
            elapsed = time.time() - start
            logger.info(f"Reranker 完成 ({len(candidates)} 文档, {elapsed:.1f}s)")

            # 组合新分数
            reranked = [(candidates[i][0], scores[i])
                        for i in range(len(candidates))]
            reranked.sort(key=lambda x: x[1], reverse=True)
            return reranked[:top_k]
        except Exception as e:
            logger.warning(f"Reranker 失败: {e}，返回原始排序")
            return candidates[:top_k]


# ═══════════════════════════════════════════
# 5. 混合检索器 (3路召回 + RRF + Reranker)
# ═══════════════════════════════════════════

class HybridRetriever(BaseRetriever):
    """
    混合检索器 — 4路召回 + RRF 融合 + Reranker 精排。

    召回通路:
      1. BM25           (关键词，免API)
      2. Dense Embed    (qwen3-embedding-8b, 稠密向量)
      3. Sparse Embed   (text-embedding-3-small, 稀疏向量)
      4. SQL Agent      (结构化表格查询，LangChain SQL Agent)

    降级: API 不可用时，自动降级到可用通路。
    """

    def __init__(self, db_path: str = None):
        self.bm25 = BM25Retriever()
        self.dense = EmbeddingRetriever(DENSE_EMBEDDING_MODEL, "dense")
        self.sparse = EmbeddingRetriever(SPARSE_EMBEDDING_MODEL, "sparse")
        self.reranker = Reranker()
        self.sql_agent = None      # 延迟初始化
        self._db_path = db_path
        self._has_embeddings = False
        self._has_sql = False
        self.documents: List[Document] = []

    def build(self, documents: List[Document],
              table_context_docs: List[Document] = None) -> None:
        self.documents = documents

        # 如果有表格上下文描述，加入 BM25 和 embedding 索引
        all_docs = list(documents)
        if table_context_docs:
            all_docs = list(documents) + table_context_docs
            logger.info(f"加入表格上下文: {len(table_context_docs)} 条描述")
        self.documents = all_docs

        # BM25 始终可用
        self.bm25.build(all_docs)

        # Dense / Sparse 需要 API
        if OPENAI_API_KEY:
            try:
                self.dense.build(all_docs)
                self.sparse.build(all_docs)
                self._has_embeddings = True
            except Exception as e:
                logger.warning(f"Embedding 构建失败: {e}，仅使用 BM25")
                self._has_embeddings = False
        else:
            logger.warning("无 API Key，仅使用 BM25 检索")

        # SQL Agent (异步初始化)
        self._init_sql_agent()

    def _init_sql_agent(self):
        """延迟初始化 SQL Agent"""
        import os
        db = self._db_path or str(DATA_DB_DIR / "tables.db")
        if os.path.exists(db):
            try:
                from agents.sql_agent import SQLAgentRetriever
                self.sql_agent = SQLAgentRetriever(db)
                self.sql_agent.build()
                self._has_sql = True
            except Exception as e:
                logger.warning(f"SQL Agent 初始化失败: {e}")

    def retrieve(self, query: str, k: int = RETRIEVAL_K) -> List[Tuple[Document, float]]:
        text_paths = []       # 文本召回 (参与 RRF + Reranker)
        sql_results = []      # SQL 召回 (不参与 RRF/Reranker，直接保留)

        # 第1路: BM25
        bm25_results = self.bm25.retrieve(query)
        if bm25_results:
            text_paths.append(bm25_results)
            logger.debug(f"BM25 召回: {len(bm25_results)} 条")

        # 第2路: Dense
        if self._has_embeddings and self.dense.embeddings is not None:
            dense_results = self.dense.retrieve(query)
            if dense_results:
                text_paths.append(dense_results)
                logger.debug(f"Dense 召回: {len(dense_results)} 条")

        # 第3路: Sparse
        if self._has_embeddings and self.sparse.embeddings is not None:
            sparse_results = self.sparse.retrieve(query)
            if sparse_results:
                text_paths.append(sparse_results)
                logger.debug(f"Sparse 召回: {len(sparse_results)} 条")

        # 第4路: SQL Agent (结构化数据，不参与 RRF/Reranker)
        if self._has_sql and self.sql_agent is not None:
            try:
                sql_results = self.sql_agent.retrieve(query, k=2)
                if sql_results:
                    logger.info(f"SQL Agent 召回: {len(sql_results)} 条 (跳过 Reranker)")
            except Exception as e:
                logger.warning(f"SQL Agent 召回失败: {e}")

        # RRF 融合 (仅文本3路)
        if len(text_paths) >= 2:
            fused = _rrf_fusion(text_paths)
            logger.info(f"RRF 融合: {len(text_paths)}路 -> {len(fused)} 条")
        elif len(text_paths) == 1:
            fused = text_paths[0][:RRF_TOP_K]
        else:
            fused = []

        # Reranker 精排 (仅文本结果)
        if self._has_embeddings and len(fused) > 1:
            fused = self.reranker.rerank(query, fused, top_k=k)

        # SQL 结果前置 + 文本结果 (SQL 结果不受 Reranker 影响)
        final = sql_results + [r for r in fused if r not in sql_results]
        return final[:k]

    def save(self, path: str) -> None:
        base = path.replace(".pkl", "")
        self.bm25.save(f"{base}_bm25.pkl")
        if self._has_embeddings:
            self.dense.save(f"{base}_dense.pkl")
            self.sparse.save(f"{base}_sparse.pkl")

    def load(self, path: str) -> None:
        base = path.replace(".pkl", "")
        import os
        bm25_path = f"{base}_bm25.pkl"
        if os.path.exists(bm25_path):
            self.bm25.load(bm25_path)
            self.documents = self.bm25.documents

        dense_path = f"{base}_dense.pkl"
        if os.path.exists(dense_path):
            self.dense.load(dense_path)
            self.sparse.load(f"{base}_sparse.pkl")
            self._has_embeddings = True

        # 重新初始化 SQL Agent
        self._init_sql_agent()

# ═══════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════

def create_retriever(documents: List[Document],
                     prefer_api: bool = True) -> BaseRetriever:
    """工厂方法：创建 HybridRetriever"""
    retriever = HybridRetriever()
    retriever.build(documents)
    return retriever


def load_retriever():
    """从磁盘加载已构建的混合检索器"""
    import os
    bm25_path = DATA_DB_DIR / "hybrid_index_bm25.pkl"
    if os.path.exists(bm25_path):
        r = HybridRetriever(db_path=str(DATA_DB_DIR / "tables.db"))
        r.load(str(DATA_DB_DIR / "hybrid_index.pkl"))
        return r
    return None
