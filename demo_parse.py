#!/usr/bin/env python
"""展示数据库中已解析的文档内容 — 文本块 + 结构化表格"""
import pickle
import sqlite3
from pathlib import Path

from config import DATA_DB_DIR

DB_PATH = DATA_DB_DIR / "tables.db"
BM25_PATH = DATA_DB_DIR / "hybrid_index_bm25.pkl"


def show_chunks():
    """展示解析后的文本块"""
    if not BM25_PATH.exists():
        print("[!] 未找到 BM25 索引，请先运行 python build.py")
        return

    with open(BM25_PATH, "rb") as f:
        documents, _ = pickle.load(f)

    print("=" * 60)
    print(f"  文本块 (chunks): {len(documents)} 个")
    print("=" * 60)

    for i, doc in enumerate(documents, 1):
        meta = doc.metadata
        page = meta.get("page", "?")
        chunk_type = meta.get("type", meta.get("source", "text"))
        parser = meta.get("parser", "")

        print(f"\n── Chunk {i}/{len(documents)}  第{page}页  type={chunk_type}"
              f"{'  parser=' + parser if parser else ''}")

        text = doc.page_content.strip()
        if len(text) > 600:
            text = text[:600] + "..."
        print(text)


def show_tables():
    """展示 SQLite 中的结构化表格"""
    if not DB_PATH.exists():
        print("\n[!] 未找到 SQLite 数据库，请先运行 python build.py")
        return

    db = sqlite3.connect(str(DB_PATH))
    cur = db.cursor()

    # 表元信息
    cur.execute("SELECT sql_table_name, page_num, table_index, row_count, col_count, "
                "context_json FROM _table_meta ORDER BY page_num, table_index")
    metas = cur.fetchall()

    print("\n" + "=" * 60)
    print(f"  结构化表格 (SQLite): {len(metas)} 张")
    print("=" * 60)

    for name, page, idx, row_cnt, col_cnt, ctx in metas:
        print(f"\n── 表: {name}  第{page}页  表{idx}  {row_cnt}行 x {col_cnt}列")
        if ctx:
            import json
            try:
                ctx_obj = json.loads(ctx)
                for k in ["footer", "header", "time_period"]:
                    if ctx_obj.get(k):
                        print(f"   {k}: {str(ctx_obj[k])[:200]}")
            except json.JSONDecodeError:
                pass

        # 数据行
        try:
            cur.execute(f'SELECT * FROM "{name}" LIMIT 8')
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            print(f"   列: {cols}")
            for row in rows:
                display = [str(v)[:50] for v in row]
                print(f"   {display}")
            if row_cnt > 8:
                print(f"   ... (共 {row_cnt} 行)")
        except sqlite3.OperationalError as e:
            print(f"   [跳过] {e}")

    db.close()


def main():
    print("数据库内容展示")
    print(f"数据目录: {DATA_DB_DIR}")
    show_chunks()
    show_tables()


if __name__ == "__main__":
    main()
