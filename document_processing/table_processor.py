"""
表格处理模块 — 合并单元格补全、上下文提取、SQLite 入库。
"""
import re
import json
import logging
import sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


@dataclass
class TableInfo:
    """结构化表格信息"""
    table_id: str              # 唯一 ID: "page3_table0"
    page_num: int
    table_index: int           # 该页第几个表格
    headers: List[str]         # 列名（合并单元格已展开）
    rows: List[List[str]]      # 数据行（合并单元格已补全）
    sql_table_name: str        # SQLite 中的表名
    context: Dict = field(default_factory=dict)
    # context 内容: header, footer, time_period, paragraph_title, surrounding_text


# ═══════════════════════════════════════════
# 1. HTML 表格解析（处理 rowspan/colspan）
# ═══════════════════════════════════════════

class _TableHTMLParser(HTMLParser):
    """解析 HTML <table>，提取所有单元格及 rowspan/colspan 信息"""

    def __init__(self):
        super().__init__()
        self.rows: List[List[Dict]] = []      # [[{text, rs, cs}]]
        self._current_row: List[Dict] = []
        self._current_cell = None
        self._in_cell = False
        self._text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ("tr",):
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._text = ""
            rs = int(attrs_dict.get("rowspan", 1))
            cs = int(attrs_dict.get("colspan", 1))
            self._current_cell = {"text": "", "rowspan": rs, "colspan": cs}

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
            if self._current_cell:
                self._current_cell["text"] = self._text.strip()
                self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag in ("tr",):
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data):
        if self._in_cell:
            self._text += data


def _expand_html_table(html: str) -> List[List[str]]:
    """
    解析 HTML 表格，补全 rowspan/colspan → 规整的二维数组。
    合并单元格的值会复制到每个被合并的位置。
    """
    parser = _TableHTMLParser()
    parser.feed(html)

    if not parser.rows:
        return []

    # 计算最终表格尺寸
    max_cols = max(
        sum(cell["colspan"] for cell in row)
        for row in parser.rows
    )
    num_rows = len(parser.rows)

    # 初始化网格
    grid = [["" for _ in range(max_cols)] for _ in range(num_rows)]
    occupied = [[False for _ in range(max_cols)] for _ in range(num_rows)]

    for r_idx, row in enumerate(parser.rows):
        c_idx = 0
        for cell in row:
            # 跳过已被占用的列
            while c_idx < max_cols and occupied[r_idx][c_idx]:
                c_idx += 1
            if c_idx >= max_cols:
                break

            rs, cs = cell["rowspan"], cell["colspan"]
            text = cell["text"]

            # 填充 merged cells
            for dr in range(rs):
                for dc in range(cs):
                    nr, nc = r_idx + dr, c_idx + dc
                    if nr < num_rows and nc < max_cols:
                        grid[nr][nc] = text
                        occupied[nr][nc] = True
            c_idx += cs

    return grid


# ═══════════════════════════════════════════
# 2. Markdown 表格解析
# ═══════════════════════════════════════════

def _parse_markdown_table(md: str) -> Optional[List[List[str]]]:
    """解析 Markdown 表格 → 二维数组"""
    lines = [l.strip() for l in md.strip().split("\n") if l.strip()]
    rows = []
    for line in lines:
        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # 跳过分隔行
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue
            rows.append(cells)
    return rows if rows else None


# ═══════════════════════════════════════════
# 3. 上下文提取
# ═══════════════════════════════════════════

def _extract_table_context(page_text: str, page_num: int,
                            parsers_meta: Dict) -> Dict:
    """
    从页面文本中提取表格的上下文信息：
    - header: 页眉（如公司名称、报表标题）
    - footer: 页脚（如报告名称页码）
    - time_period: 时间范围（如 2025年1月1日至6月30日）
    - paragraph_title: 段落标题（如"其他综合收益"）
    - parser_tool: 使用的解析工具
    """
    context = {"parser_tool": parsers_meta.get("parser", "unknown")}

    lines = page_text.split("\n")

    # 提取时间范围
    date_patterns = [
        r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[至到\-]\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        r"(\d{4}\s*年\d{1,2}月\d{1,2}日)",
        r"(\d{4}\s*年度)",
        r"(\d{4}\s*年\s*\d{1,2}\s*月[至到\-]\s*\d{4}\s*年\s*\d{1,2}\s*月)",
    ]
    for pattern in date_patterns:
        matches = re.findall(pattern, page_text)
        if matches:
            context["time_period"] = list(set(matches))[:5]
            break

    # 提取段落标题（表格上方最近的标题）
    title_patterns = [r"(?:[一二三四五六七八九十]+[、.．]\s*[^\n]+)",
                      r"(?:\(\s*[一二三四五六七八九十]+\s*\)[^\n]*)"]
    for pattern in title_patterns:
        matches = re.findall(pattern, page_text)
        if matches:
            context["paragraph_title"] = matches[:3]

    # 页眉（通常是前几行的公司名/报表名）
    if len(lines) >= 2:
        header_candidates = []
        for line in lines[:3]:
            line = line.strip()
            if "证券" in line or "报表" in line or "财务" in line or "报告" in line:
                header_candidates.append(line)
        if header_candidates:
            context["header"] = header_candidates

    # 页脚
    if len(lines) >= 1:
        last_lines = lines[-2:]
        footer_candidates = [l.strip() for l in last_lines
                             if ("报告" in l or "财务" in l or "页" in l)]
        if footer_candidates:
            context["footer"] = footer_candidates

    return context


# ═══════════════════════════════════════════
# 4. 主处理流程
# ═══════════════════════════════════════════

def _extract_html_tables_from_text(text: str) -> List[str]:
    """从页面文本中提取 HTML <table>...</table> 片段"""
    import re
    tables = re.findall(r'<table>.*?</table>', text, re.DOTALL)
    return tables


def process_tables_to_sql(pdf_doc, db_path: str) -> Tuple[List[TableInfo], str]:
    """
    处理 PDF 文档中的所有表格 → 补全合并单元格 → 存入 SQLite。
    返回: (TableInfo 列表, 数据库路径)
    """
    db = sqlite3.connect(db_path)
    cursor = db.cursor()

    # 元数据表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _table_meta (
            table_id TEXT PRIMARY KEY,
            page_num INTEGER,
            table_index INTEGER,
            sql_table_name TEXT,
            context_json TEXT,
            row_count INTEGER,
            col_count INTEGER
        )
    """)

    table_infos: List[TableInfo] = []
    global_idx = 0

    for page in pdf_doc.pages:
        # 合并多个来源的表格: PageContent.tables + 从 text 中提取的 HTML 表格
        all_table_strs = list(page.tables)
        html_tables = _extract_html_tables_from_text(page.text)
        all_table_strs.extend(html_tables)

        if not all_table_strs:
            continue

        # 提取该页表格上下文
        context = _extract_table_context(
            page.text, page.page_num, pdf_doc.meta
        )

        for t_idx, table_str in enumerate(all_table_strs):
            # 解析表格
            if table_str.strip().startswith("<"):
                # HTML 表格
                rows = _expand_html_table(table_str)
            else:
                # Markdown 表格
                rows = _parse_markdown_table(table_str)

            if not rows:
                continue

            # 检测并分离表头和数据行
            headers, data_rows = _split_header_and_data(rows, page.text, context)
            if not data_rows:
                continue

            # 清理列名（替换空列名）
            clean_headers = []
            for i, h in enumerate(headers):
                if not h.strip():
                    h = f"col_{i}"
                # 替换 SQL 不友好字符
                h = re.sub(r"[^\w一-鿿]", "_", h.strip())
                clean_headers.append(h)

            # 创建 SQL 表
            table_id = f"page{page.page_num}_table{t_idx}"
            sql_name = f"t_{global_idx}"
            global_idx += 1

            col_defs = ", ".join(f'"{h}" TEXT' for h in clean_headers)
            cursor.execute(f'CREATE TABLE IF NOT EXISTS "{sql_name}" ({col_defs})')

            # 插入数据
            placeholders = ", ".join("?" for _ in clean_headers)
            for row in data_rows:
                # 补齐列数
                padded = list(row) + [""] * (len(clean_headers) - len(row))
                cursor.execute(
                    f'INSERT INTO "{sql_name}" VALUES ({placeholders})',
                    padded[:len(clean_headers)]
                )

            # 记录元数据
            cursor.execute(
                "INSERT INTO _table_meta VALUES (?, ?, ?, ?, ?, ?, ?)",
                (table_id, page.page_num, t_idx, sql_name,
                 json.dumps(context, ensure_ascii=False),
                 len(data_rows), len(clean_headers))
            )

            table_infos.append(TableInfo(
                table_id=table_id,
                page_num=page.page_num,
                table_index=t_idx,
                headers=clean_headers,
                rows=data_rows,
                sql_table_name=sql_name,
                context=context,
            ))
            logger.info(f"表格入库: {table_id} → {sql_name} "
                        f"({len(data_rows)}行 x {len(clean_headers)}列)")

    db.commit()
    db.close()
    logger.info(f"表格处理完成: {len(table_infos)} 个表格 → {db_path}")
    return table_infos, db_path


def get_table_context_for_retrieval(table_info: TableInfo) -> str:
    """
    生成表格的富化描述文本，用于向量检索。
    包含：时间、标题、页眉页脚、列名、行数。
    """
    ctx = table_info.context
    parts = []
    if ctx.get("time_period"):
        parts.append(f"时间段: {', '.join(ctx['time_period'])}")
    if ctx.get("header"):
        parts.append(f"报表: {'; '.join(ctx['header'])}")
    if ctx.get("paragraph_title"):
        parts.append(f"标题: {'; '.join(ctx['paragraph_title'])}")
    if ctx.get("footer"):
        parts.append(f"页脚: {'; '.join(ctx['footer'])}")
    parts.append(f"表格位于第{table_info.page_num}页")
    parts.append(f"列名: {', '.join(table_info.headers[:10])}")
    parts.append(f"数据行数: {len(table_info.rows)}")
    parts.append(f"解析工具: {ctx.get('parser_tool', 'unknown')}")

    return "\n".join(parts)


def _split_header_and_data(rows: List[List[str]], page_text: str,
                            context: Dict) -> Tuple[List[str], List[List[str]]]:
    """分离表头和数据行。处理无表头的表格。"""
    if len(rows) < 2:
        return [f"col_{i}" for i in range(len(rows[0]))], rows

    first = rows[0]
    second = rows[1]

    # 判断第一行是否是分隔行 (|---|...|)
    is_sep = all(re.match(r'^[-:\s]+$', c) for c in first)

    if is_sep:
        # 第一行是分隔符 → 无表头，用 col_N
        data = rows[1:]  # skip separator
        return [f"col_{i}" for i in range(len(data[0]) if data else 1)], data

    # 判断第二行是否为分隔行
    is_second_sep = all(re.match(r'^[-:\s]+$', c) for c in second) if second else False

    if is_second_sep:
        # 标准格式: header, separator, data...
        return first, rows[2:] if len(rows) > 2 else []

    # 无分隔行: 第一行作为数据
    return [f"col_{i}" for i in range(len(first))], rows


def _infer_column_names(sample_row: List[str], page_text: str,
                        context: Dict) -> List[str]:
    """
    推断列名。优先从 page_text 中查找表格标题行，
    找不到则用 col_0, col_1... 占位。
    """
    # 尝试从页面文本中找到包含 "名称"/"金额"/"日期" 等关键词的行
    lines = page_text.split("\n")
    col_keywords = ["名称", "日期", "金额", "价值", "增加", "减少", "准备", "项目",
                    "Name", "Date", "Amount", "Value"]
    for line in lines:
        if any(kw in line for kw in col_keywords):
            # 尝试按空格或 tab 拆分
            parts = re.split(r'\s{2,}|\t', line.strip())
            if len(parts) >= len(sample_row) // 2:
                return [re.sub(r"[^\w一-鿿]", "_", p.strip()) for p in parts[:len(sample_row)]]

    # 回退：使用 page_text 的前几行
    first_lines = [l.strip() for l in lines[:5] if l.strip()]
    if first_lines:
        parts = re.split(r'\s{2,}|\t', first_lines[0])
        if len(parts) >= 2:
            return [f"col_{i}" for i in range(len(sample_row))]

    return [f"col_{i}" for i in range(len(sample_row))]


def build_table_search_index(table_infos: List[TableInfo]) -> List[str]:
    """
    为每个表格生成检索用的文本描述。
    这些描述将作为额外的检索目标，帮助 LLM 判断该表格是否相关。
    """
    return [get_table_context_for_retrieval(t) for t in table_infos]
