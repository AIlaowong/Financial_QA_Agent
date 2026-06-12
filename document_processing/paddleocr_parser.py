"""
PaddleOCR-VL API 解析模块 - 调用百度智能云 PaddleOCR-VL 异步接口解析 PDF。
流程: 获取 access_token → 提交任务 → 轮询结果 → 下载结构化 JSON
支持: 文本提取、表格识别(Markdown)、版式分析
"""
import os
import time
import base64
import logging
from typing import List

import requests

from document_processing.pdf_parser import PageContent, PDFDocument
from config import PADDLEOCR_API_KEY, PADDLEOCR_SECRET_KEY

logger = logging.getLogger(__name__)

# API 端点
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
TASK_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task"
QUERY_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task/query"


class PaddleOCRParser:
    """PaddleOCR-VL API 解析器 - 适配 PDFDocument 输出接口"""

    def __init__(self, api_key: str = None, secret_key: str = None):
        self.api_key = api_key or PADDLEOCR_API_KEY
        self.secret_key = secret_key or PADDLEOCR_SECRET_KEY
        self._token = None

    def parse(self, file_path: str) -> PDFDocument:
        logger.info(f"PaddleOCR-VL 解析 PDF: {file_path}")

        # Step 1: 获取 token
        token = self._get_token()

        # Step 2: 提交任务
        task_id = self._submit_task(token, file_path)

        # Step 3: 轮询结果
        result_url = self._poll_task(token, task_id)

        # Step 4: 下载解析结果
        parse_data = self._download_result(result_url)

        # Step 5: 转 PDFDocument
        pages = self._convert_to_pages(parse_data)

        pdf_doc = PDFDocument(
            file_path=file_path,
            total_pages=len(pages),
            pages=pages,
            meta={"parser": "paddleocr-vl"}
        )
        logger.info(f"PaddleOCR-VL 解析完成: {len(pages)} 页")
        return pdf_doc

    def _get_token(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }
        resp = requests.post(TOKEN_URL, params=params, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if "access_token" not in result:
            raise RuntimeError(f"获取 token 失败: {result}")
        return result["access_token"]

    def _submit_task(self, token: str, file_path: str) -> str:
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode("utf-8")

        url = f"{TASK_URL}?access_token={token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"file_data": file_data, "file_name": file_name}

        resp = requests.post(url, headers=headers, data=data, timeout=120)
        result = resp.json()

        if result.get("error_code") != 0:
            raise RuntimeError(
                f"提交任务失败: [{result.get('error_code')}] {result.get('error_msg')}"
            )
        return result["result"]["task_id"]

    def _poll_task(self, token: str, task_id: str, max_wait: int = 300) -> str:
        url = f"{QUERY_URL}?access_token={token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        for i in range(max_wait // 3):
            time.sleep(3)
            resp = requests.post(
                url, headers=headers, data={"task_id": task_id}, timeout=30
            )
            result = resp.json()

            if result.get("error_code") != 0:
                continue

            status = result["result"]["status"]
            if status == "success":
                return result["result"].get("parse_result_url", "")
            elif status == "failed":
                raise RuntimeError(
                    f"任务失败: {result['result'].get('task_error', '')}"
                )
        raise TimeoutError(f"轮询超时 ({max_wait}s)")

    def _download_result(self, url: str) -> dict:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _convert_to_pages(self, parse_data: dict) -> List[PageContent]:
        pages = []
        for page_data in parse_data.get("pages", []):
            page_num = page_data.get("page_num", 0) + 1
            text = page_data.get("text", "")

            # 提取表格 (markdown 格式)
            tables = []
            for t in page_data.get("tables", []):
                md = t.get("markdown", "")
                if md.strip():
                    tables.append(md.strip())

            pages.append(PageContent(
                page_num=page_num,
                text=text,
                tables=tables,
                is_scanned=False,
                has_table=len(tables) > 0,
            ))
        return pages
