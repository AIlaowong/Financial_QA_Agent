#!/usr/bin/env python
"""
数据处理 — 一站式构建知识库。

用法:
    python build.py                          # 默认 pymupdf
    python build.py --parser paddleocr       # PaddleOCR 解析
    python build.py --parser mineru          # MinerU 解析
    python build.py --parser fallback        # 降级链

流程: PDF 解析 → 清洗分块 → 表格入 SQL → 4路混合索引
"""
import sys
import logging
from pathlib import Path

from config import PDF_PATH, LOG_LEVEL, PARSER_STRATEGY, DATA_DB_DIR
from document_processing import get_parser, process_pdf_document
from document_processing.table_processor import (
    process_tables_to_sql, build_table_search_index
)
from tools.retriever import HybridRetriever
from langchain_core.documents import Document as LCDocument

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build")

DEFAULT_PDF = str(Path(__file__).parent.parent / "file" / "agent开发作业样本.pdf")


def main():
    args = sys.argv[1:]
    strategy = PARSER_STRATEGY
    pdf_path = PDF_PATH or DEFAULT_PDF

    for i, arg in enumerate(args):
        if arg == "--parser" and i + 1 < len(args):
            strategy = args[i + 1]
        if arg == "--pdf" and i + 1 < len(args):
            pdf_path = args[i + 1]

    logger.info(f"开始构建: {pdf_path} (解析器: {strategy})")
    DATA_DB_DIR.mkdir(parents=True, exist_ok=True)
    db_path = str(DATA_DB_DIR / "tables.db")

    # 1. 解析 PDF
    parser = get_parser(strategy)
    pdf_doc = parser.parse(pdf_path)
    logger.info(f"PDF: {pdf_doc.total_pages} 页 (解析器: {pdf_doc.meta.get('parser', strategy)})")

    # 2. 清洗分块
    documents = process_pdf_document(pdf_doc)
    if not documents:
        logger.warning("未提取到有效文本块")
        return
    logger.info(f"分块: {len(documents)} 个")

    # 3. 表格 → SQL
    table_context_docs = []
    try:
        table_infos, _ = process_tables_to_sql(pdf_doc, db_path)
        context_texts = build_table_search_index(table_infos)
        for i, ctx_text in enumerate(context_texts):
            table_context_docs.append(LCDocument(
                page_content=ctx_text,
                metadata={"type": "table_context", "table_id": table_infos[i].table_id,
                          "page": table_infos[i].page_num}
            ))
        logger.info(f"SQL 表格: {len(table_infos)} 张")
    except Exception as e:
        logger.warning(f"表格处理跳过 (非致命): {e}")

    # 4. 构建 4 路混合索引
    retriever = HybridRetriever(db_path=db_path)
    retriever.build(documents, table_context_docs=(table_context_docs or None))
    retriever.save(str(DATA_DB_DIR / "hybrid_index.pkl"))
    logger.info("完成: BM25 + Dense + Sparse + SQL 索引已保存")


if __name__ == "__main__":
    main()
