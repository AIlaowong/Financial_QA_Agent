"""
MinerU 精准解析模块 - 调用 MinerU API 解析 PDF。
流程: 获取上传 URL → 上传文件 → 轮询结果 → 下载 ZIP → 提取 Markdown
"""
import os
import time
import zipfile
import logging
import tempfile
from pathlib import Path
from typing import List

import requests

from document_processing.pdf_parser import PageContent, PDFDocument
from config import MINERU_TOKEN, MINERU_BASE_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MINERU_TOKEN}",
}


class MinerUParser:
    """MinerU API 解析器 - 适配 PDFDocument 输出接口"""

    def __init__(self, language: str = "ch",
                 enable_table: bool = True,
                 enable_formula: bool = True,
                 model_version: str = "vlm"):
        self.language = language
        self.enable_table = enable_table
        self.enable_formula = enable_formula
        self.model_version = model_version

    def parse(self, file_path: str) -> PDFDocument:
        """解析 PDF，返回统一的 PDFDocument"""
        logger.info(f"MinerU 解析 PDF: {file_path} (模型: {self.model_version})")

        # Step 1: 获取上传 URL
        batch_id, upload_url = self._get_upload_url(file_path)

        # Step 2: 上传文件
        self._upload_file(file_path, upload_url)

        # Step 3: 轮询解析结果
        zip_url = self._poll_result(batch_id)

        # Step 4: 下载并解压
        md_dir = self._download_and_extract(zip_url)

        # Step 5: 解析 Markdown 为 PageContent
        pages = self._parse_markdown_dir(md_dir)

        pdf_doc = PDFDocument(
            file_path=file_path,
            total_pages=len(pages),
            pages=pages,
            meta={"parser": "mineru", "model": self.model_version,
                  "language": self.language}
        )
        logger.info(f"MinerU 解析完成: {len(pages)} 页")
        return pdf_doc

    def _get_upload_url(self, file_path: str) -> tuple:
        """Step 1: 获取 OSS 签名上传 URL"""
        file_name = os.path.basename(file_path)
        data = {
            "files": [{"name": file_name}],
            "model_version": self.model_version,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
        }

        resp = requests.post(
            f"{MINERU_BASE_URL}/file-urls/batch",
            headers=HEADERS, json=data, timeout=30
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise RuntimeError(f"获取上传 URL 失败: {result.get('msg')}")

        batch_id = result["data"]["batch_id"]
        upload_url = result["data"].get("file_urls", [None])[0]
        logger.info(f"MinerU batch_id: {batch_id}")
        return batch_id, upload_url

    def _upload_file(self, file_path: str, upload_url: str) -> None:
        """Step 2: PUT 上传文件到 OSS"""
        with open(file_path, "rb") as f:
            resp = requests.put(upload_url, data=f, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"上传失败: HTTP {resp.status_code}")
        logger.info("MinerU 文件上传成功")

    def _poll_result(self, batch_id: str, max_wait: int = 600) -> str:
        """Step 3: 轮询批量任务结果"""
        url = f"{MINERU_BASE_URL}/extract-results/batch/{batch_id}"
        interval = 5

        for i in range(max_wait // interval):
            time.sleep(interval)

            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                logger.warning(f"查询失败: {result.get('msg')}")
                continue

            extract_results = result.get("data", {}).get("extract_result", [])
            if not extract_results:
                continue

            task = extract_results[0]
            state = task.get("state", "")

            if state == "done":
                zip_url = task.get("full_zip_url", "")
                logger.info(f"MinerU 解析完成 (第{i+1}轮)")
                return zip_url
            elif state == "failed":
                raise RuntimeError(f"解析失败: {task.get('err_msg', '')}")
            else:
                logger.debug(f"MinerU 状态: {state} (第{i+1}轮)")

        raise TimeoutError(f"MinerU 轮询超时 ({max_wait}s)")

    def _download_and_extract(self, zip_url: str) -> Path:
        """Step 4: 下载 ZIP 并解压到临时目录"""
        resp = requests.get(zip_url, stream=True, timeout=120)
        resp.raise_for_status()

        tmp_dir = Path(tempfile.mkdtemp(prefix="mineru_"))
        zip_path = tmp_dir / "result.zip"

        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # 解压
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # 查找 markdown 目录
        for item in tmp_dir.iterdir():
            if item.is_dir() and item.name.endswith("_md"):
                logger.info(f"MinerU 解压完成: {item}")
                return item

        raise FileNotFoundError(f"ZIP 中未找到 _md 目录: {tmp_dir}")

    def _parse_markdown_dir(self, md_dir: Path) -> List[PageContent]:
        """Step 5: 解析 MinerU 输出的 markdown 文件"""
        pages = []
        # MinerU 输出格式: {name}_md/{name}_page_001.md, _page_002.md, ...
        md_files = sorted(md_dir.glob("*_page_*.md"))

        if not md_files:
            # 尝试不按 page 模式匹配
            md_files = sorted(md_dir.glob("*.md"))

        for i, md_file in enumerate(md_files):
            page_num = i + 1
            text = md_file.read_text(encoding="utf-8")

            # 提取表格（MinerU 用 markdown table 格式）
            tables = self._extract_tables_from_md(text)

            # 清洗文本（去除 MinerU 的标记标签如 <br>, <p> 等）
            clean = self._clean_mineru_text(text)

            pages.append(PageContent(
                page_num=page_num,
                text=clean,
                tables=tables,
                is_scanned=False,  # MinerU VLM 已做 OCR
                has_table=len(tables) > 0,
            ))

        return pages

    def _extract_tables_from_md(self, text: str) -> List[str]:
        """从 Markdown 文本中提取表格块"""
        tables = []
        lines = text.split("\n")
        in_table = False
        table_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and "|" in stripped[1:]:
                # 表格行
                in_table = True
                table_lines.append(stripped)
            else:
                if in_table and table_lines:
                    tables.append("\n".join(table_lines))
                    table_lines = []
                in_table = False

        # 最后一段表格
        if in_table and table_lines:
            tables.append("\n".join(table_lines))

        return tables

    def _clean_mineru_text(self, text: str) -> str:
        """清洗 MinerU 输出的 Markdown 文本"""
        import re
        # 移除 HTML 标签
        text = re.sub(r"<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        # 移除多余的空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
