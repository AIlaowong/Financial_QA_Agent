"""
文档分块模块 - 文本清洗、分块、结构化、元数据富化。
从文档内容中提取日期、主体、客体、关系等关键信息，存入 metadata。
"""
import logging
import re
from typing import List, Dict

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from config import CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger(__name__)

# ── 元数据提取正则 ──
DATE_PATTERNS = [
    (r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", "full_date"),   # 2025年6月30日
    (r"(\d{4})\s*年\s*(\d{1,2})\s*月", "year_month"),                    # 2025年6月
    (r"(\d{4})[一-鿿]{0,2}年度", "fiscal_year"),                 # 2024年度
    (r"(\d{4})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[至|到|-]\s*(\d{4})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", "date_range"),
]

ENTITY_PATTERNS = [
    # 公司/机构名（中文，以"有限公司/股份有限公司/合伙企业"等结尾）
    (r"([一-鿿（）()a-zA-Z&\s]{4,60}(?:有限公司|股份有限公司|有限责任公司|合伙企业|基金管理|投资中心|俱乐部|交易中心))", "company_cn"),
    # 英文公司名
    (r"([A-Z][A-Za-z&\s]+(?:Limited|L\.P\.|LP|LLC|Inc\.|Ltd\.))", "company_en"),
    # 金额 (数字+逗号+小数点)
    (r"([\d,]+\.\d{2})", "amount"),
]


def _extract_dates(text: str) -> Dict[str, List[str]]:
    """从文本中提取日期信息"""
    dates = {}
    for pattern, key in DATE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            dates[key] = list(set(matches))[:5]  # 去重，每种最多5个
    return dates


def _extract_entities(text: str) -> Dict[str, List[str]]:
    """从文本中提取关键实体（主体/客体）"""
    entities = {}
    for pattern, key in ENTITY_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            unique = list(set(matches))[:10]  # 去重，每种最多10个
            entities[key] = unique
    return entities


def _detect_relations(text: str) -> List[str]:
    """检测文本中的关键关系（如投资、控股、合营等）"""
    relation_keywords = {
        "长期股权投资": "equity_investment",
        "合营企业": "joint_venture",
        "联营企业": "associate",
        "其他综合收益": "other_comprehensive_income",
        "金融负债": "financial_liability",
        "账面价值": "book_value",
        "减值准备": "impairment",
        "公允价值": "fair_value",
        "短期借款": "short_term_borrowing",
        "应付债券": "bonds_payable",
    }
    found = []
    for keyword, rel_type in relation_keywords.items():
        if keyword in text:
            found.append(rel_type)
    return found


def _enrich_metadata(page_meta: Dict, text: str) -> Dict:
    """富化元数据：日期 + 实体 + 关系（工具信息已在 page_meta 中）"""
    enriched = dict(page_meta)

    # 日期
    dates = _extract_dates(text)
    if dates:
        enriched["dates"] = dates

    # 实体（主体/客体）
    entities = _extract_entities(text)
    if entities:
        enriched["entities"] = entities

    # 关系
    relations = _detect_relations(text)
    if relations:
        enriched["relations"] = relations

    return enriched


def clean_text(text: str) -> str:
    """清洗文本：去除多余空白、修复常见 OCR 错误"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)
    return text.strip()


def chunk_documents(full_text: str, tables: List[str],
                    metadata: Dict) -> List[Document]:
    """将文本和表格分块为 LangChain Document 对象（含富化元数据）"""
    documents = []

    # 正文分块
    if full_text:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", ".", "，", ",", " ", ""],
            length_function=len,
        )
        text_chunks = splitter.split_text(full_text)
        for i, chunk in enumerate(text_chunks):
            chunk = clean_text(chunk)
            if len(chunk) < 20:
                continue
            enriched = _enrich_metadata(metadata, chunk)
            documents.append(Document(
                page_content=chunk,
                metadata={"chunk_id": i, "type": "text", **enriched}
            ))
        logger.info(f"正文分块: {len(text_chunks)} 块 -> {len(documents)} 有效块")

    # 表格分块（每个表格作为独立块，标记 type=table）
    for i, table in enumerate(tables):
        table = clean_text(table)
        if len(table) < 20:
            continue
        enriched = _enrich_metadata(metadata, table)
        documents.append(Document(
            page_content=table,
            metadata={"chunk_id": f"table_{i}", "type": "table", **enriched}
        ))
    logger.info(f"表格分块: {len(tables)} 个")

    return documents


def process_pdf_document(pdf_doc) -> List[Document]:
    """处理解析后的 PDF 文档，生成 Document 列表"""
    parser_name = pdf_doc.meta.get("parser", "unknown")
    all_docs = []

    for page in pdf_doc.pages:
        page_meta = {
            "page": page.page_num,
            "is_scanned": page.is_scanned,
            "has_table": page.has_table,
            "parser_tool": parser_name,
        }

        if page.is_scanned:
            logger.info(f"第{page.page_num}页为扫描页，跳过文本分块（需 OCR）")
            continue

        docs = chunk_documents(
            full_text=page.text,
            tables=page.tables,
            metadata=page_meta,
        )
        all_docs.extend(docs)

    logger.info(f"文档处理完成: 共 {len(all_docs)} 个块 (解析器: {parser_name})")
    return all_docs
