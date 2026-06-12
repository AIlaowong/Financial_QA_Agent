"""
PDF 解析模块 - 智能识别 PDF 类型并选择解析策略。
支持策略:
  - pymupdf: 文本层提取 + 表格识别 (快速，适合文本型 PDF)
  - mineru:   MinerU VLM 精准解析 (适合扫描件/复杂排版)
  - auto:     先尝试 pymupdf，扫描页自动用 mineru
"""
import logging
from typing import List, Dict
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from config import MINERU_TOKEN

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    """单页内容"""
    page_num: int
    text: str = ""
    tables: List[str] = field(default_factory=list)
    is_scanned: bool = False
    has_table: bool = False


@dataclass
class PDFDocument:
    """解析后的 PDF 文档"""
    file_path: str
    total_pages: int
    pages: List[PageContent] = field(default_factory=list)
    meta: Dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def scanned_pages(self) -> List[int]:
        return [p.page_num for p in self.pages if p.is_scanned]


class PDFParser:
    """PDF 解析器 - 自动检测类型并选择策略 (PyMuPDF 后端)"""

    TEXT_THRESHOLD = 50  # 少于 50 字符视为扫描页

    def parse(self, file_path: str) -> PDFDocument:
        """解析 PDF，自动选择策略"""
        logger.info(f"解析 PDF: {file_path}")
        doc = fitz.open(file_path)
        pdf_doc = PDFDocument(
            file_path=file_path,
            total_pages=len(doc),
            meta={"format": doc.metadata.get("format", "PDF"),
                  "encrypted": doc.is_encrypted, "parser": "pymupdf"}
        )

        for i in range(len(doc)):
            page = doc[i]
            content = self._parse_page(page, i)
            pdf_doc.pages.append(content)

        doc.close()

        scanned = pdf_doc.scanned_pages
        logger.info(f"解析完成: {pdf_doc.total_pages} 页, "
                    f"扫描页: {scanned if scanned else '无'}, "
                    f"文本页: {pdf_doc.total_pages - len(scanned)}")
        return pdf_doc

    def _parse_page(self, page, page_num: int) -> PageContent:
        """解析单页"""
        content = PageContent(page_num=page_num + 1)

        text = page.get_text("text").strip()
        if text and len(text) > self.TEXT_THRESHOLD:
            content.text = text
            content.is_scanned = False
            logger.debug(f"第{page_num+1}页: 文本层提取 ({len(text)} 字符)")
        else:
            content.is_scanned = True
            logger.debug(f"第{page_num+1}页: 扫描件 (文本不足)")

        tables = self._extract_tables(page)
        if tables:
            content.tables = tables
            content.has_table = True
            logger.debug(f"第{page_num+1}页: 检测到 {len(tables)} 个表格")

        return content

    def _extract_tables(self, page) -> List[str]:
        """从页面提取表格（基于文本块位置分析）"""
        try:
            tables = page.find_tables()
            if tables and tables.tables:
                result = []
                for t in tables.tables:
                    df = t.extract()
                    if df and len(df) > 1:
                        result.append(self._format_table(df))
                return result
        except Exception:
            pass
        return []

    def _format_table(self, rows: List[List]) -> str:
        """格式化表格为 Markdown"""
        if not rows:
            return ""
        lines = []
        lines.append("| " + " | ".join(str(c or "") for c in rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(str(c or "") for c in row) + " |")
        return "\n".join(lines)

# ── AutoParser ──

class AutoParser:
    """
    自动解析器 - pymupdf 为主，扫描页用 mineru 补充。
    当扫描页比例 > 50% 时，全部用 mineru 重解析。
    """

    def parse(self, file_path: str) -> PDFDocument:
        pymupdf_parser = PDFParser()
        pdf_doc = pymupdf_parser.parse(file_path)

        scanned_ratio = len(pdf_doc.scanned_pages) / max(pdf_doc.total_pages, 1)

        if scanned_ratio > 0.5 and MINERU_TOKEN:
            logger.info(f"扫描页比例 {scanned_ratio:.0%}>50%，切换 MinerU 解析")
            from document_processing.mineru_parser import MinerUParser
            return MinerUParser().parse(file_path)
        elif pdf_doc.scanned_pages and MINERU_TOKEN:
            logger.info(f"扫描页: {pdf_doc.scanned_pages}，用 MinerU 补充解析")
            from document_processing.mineru_parser import MinerUParser
            mineru_doc = MinerUParser().parse(file_path)
            for i, page in enumerate(pdf_doc.pages):
                if page.is_scanned and i < len(mineru_doc.pages):
                    pdf_doc.pages[i] = mineru_doc.pages[i]
            pdf_doc.meta["parser"] = "auto (pymupdf + mineru)"
        else:
            pdf_doc.meta["parser"] = "pymupdf"

        return pdf_doc
