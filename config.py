"""
配置管理模块
所有参数从 .env 文件加载，无硬编码默认值。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── LLM 配置 ──
LLM_PROVIDER = os.getenv("LLM_PROVIDER")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("DEEPSEEK_API_KEY"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
RED_TEAM_LLM_MODEL = os.getenv("RED_TEAM_LLM_MODEL", os.getenv("LLM_MODEL"))

# ── 检索模型配置 (3路召回 + RRF + Reranker) ──
DENSE_EMBEDDING_MODEL = os.getenv("DENSE_EMBEDDING_MODEL")
SPARSE_EMBEDDING_MODEL = os.getenv("SPARSE_EMBEDDING_MODEL")
RERANKER_MODEL = os.getenv("RERANKER_MODEL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
RECALL_PER_PATH = int(os.getenv("RECALL_PER_PATH"))
RRF_TOP_K = int(os.getenv("RRF_TOP_K"))
RRF_K = int(os.getenv("RRF_K"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")

# ── MinerU 精准解析 API ──
MINERU_TOKEN = os.getenv("MINERU_TOKEN")
MINERU_BASE_URL = os.getenv("MINERU_BASE_URL")

# ── PaddleOCR-VL API ──
PADDLEOCR_API_KEY = os.getenv("PADDLEOCR_API_KEY")
PADDLEOCR_SECRET_KEY = os.getenv("PADDLEOCR_SECRET_KEY")
PARSER_STRATEGY = os.getenv("PARSER_STRATEGY")

# ── Agent 循环参数 ──
MAX_REFINE_LOOPS = int(os.getenv("MAX_REFINE_LOOPS"))
QUALITY_THRESHOLD = int(os.getenv("QUALITY_THRESHOLD"))

# ── 处理参数 ──
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP"))
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K"))

# ── 路径 ──
PDF_PATH = os.getenv("PDF_PATH")
DATA_DB_DIR = Path(__file__).parent / "data_db"
TEST_RESULT_DIR = Path(__file__).parent / "test_data_result"
# ── 日志 ──
LOG_LEVEL = os.getenv("LOG_LEVEL")
