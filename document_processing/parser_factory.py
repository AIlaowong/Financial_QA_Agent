"""
解析器工厂 - 实现降级策略: MinerU → PaddleOCR → PyMuPDF
"""
import logging
from document_processing.pdf_parser import PDFDocument, PDFParser, AutoParser
from document_processing.mineru_parser import MinerUParser
from document_processing.paddleocr_parser import PaddleOCRParser
from config import PARSER_STRATEGY, MINERU_TOKEN, PADDLEOCR_API_KEY

logger = logging.getLogger(__name__)

FALLBACK_CHAIN = ["mineru", "paddleocr", "pymupdf"]


def get_parser(strategy: str = None) -> object:
    """
    解析器工厂 - 支持 fallback 降级链。
    策略: pymupdf | mineru | paddleocr | auto | fallback
    """
    strategy = strategy or PARSER_STRATEGY

    if strategy == "pymupdf":
        return PDFParser()

    if strategy == "mineru":
        if not MINERU_TOKEN:
            raise RuntimeError("使用 MinerU 需要配置 MINERU_TOKEN")
        return MinerUParser()

    if strategy == "paddleocr":
        return PaddleOCRParser()

    if strategy == "auto":
        return AutoParser()

    if strategy == "fallback":
        return FallbackParser()

    return PDFParser()


class FallbackParser:
    """
    降级解析器 - 按优先级链依次尝试:
    MinerU → PaddleOCR → PyMuPDF
    当前级失败时自动降级到下一级。
    """

    def parse(self, file_path: str) -> PDFDocument:
        errors = []

        for name in FALLBACK_CHAIN:
            try:
                logger.info(f"尝试 {name} 解析...")
                parser = self._create_parser(name)
                doc = parser.parse(file_path)
                doc.meta["parser"] = name
                logger.info(f"{name} 解析成功: {doc.total_pages} 页")
                return doc
            except Exception as e:
                err = f"{name}: {e}"
                errors.append(err)
                logger.warning(f"{name} 解析失败: {e}")

        raise RuntimeError(
            f"所有解析器均失败! 错误详情: {'; '.join(errors)}"
        )

    def _create_parser(self, name: str):
        if name == "mineru" and MINERU_TOKEN:
            return MinerUParser()
        elif name == "paddleocr" and PADDLEOCR_API_KEY:
            return PaddleOCRParser()
        elif name == "pymupdf":
            return PDFParser()
        raise RuntimeError(f"解析器 {name} 不可用（缺少凭证）")
