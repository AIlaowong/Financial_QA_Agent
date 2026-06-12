"""
SQL 召回校验脚本 — 验证 SQL Agent 生成的查询质量和结果合理性。
"""
import sqlite3
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple


class SQLValidator:
    """SQL 召回校验器"""

    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)

    def validate_sql_syntax(self, sql: str) -> Dict:
        """校验 SQL 语法安全性"""
        result = {"valid": True, "issues": []}

        # 1. 危险操作检测
        dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                     "ATTACH", "DETACH", "VACUUM", "REINDEX"]
        for w in dangerous:
            if w in sql.upper().split():
                result["valid"] = False
                result["issues"].append(f"DANGER: 包含 {w}")

        # 2. SELECT 语句检查
        if not re.match(r'\s*SELECT\s', sql, re.IGNORECASE):
            result["valid"] = False
            result["issues"].append("不是 SELECT 语句")

        # 3. EXPLAIN 预执行
        try:
            self.db.execute(f"EXPLAIN {sql}")
        except Exception as e:
            result["valid"] = False
            result["issues"].append(f"SQL 语法错误: {e}")

        return result

    def validate_result(self, sql: str) -> Dict:
        """校验查询结果的合理性"""
        result = {"valid": True, "issues": [], "stats": {}}
        try:
            cursor = self.db.execute(sql)
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            result["stats"]["row_count"] = len(rows)
            result["stats"]["col_count"] = len(cols)

            # 1. 行数检查
            if len(rows) == 0:
                result["issues"].append("查询无结果")
            elif len(rows) > 1000:
                result["issues"].append("结果行数过多(>1000)")

            # 2. NULL 比例检查
            if rows:
                null_counts = [0] * len(cols)
                for row in rows:
                    for i, val in enumerate(row):
                        if val is None or str(val).strip() == "":
                            null_counts[i] += 1
                high_null_cols = [
                    cols[i] for i, c in enumerate(null_counts)
                    if c / len(rows) > 0.8
                ]
                if high_null_cols:
                    result["issues"].append(
                        f"高NULL列: {', '.join(high_null_cols[:3])}"
                    )

            # 3. 数字列合理性
            for i, col in enumerate(cols):
                values = [str(r[i]) for r in rows if r[i] is not None]
                numeric_count = sum(
                    1 for v in values
                    if re.match(r'^[\d,.-]+$', v.replace(" ", ""))
                )
                result["stats"][f"{col}_numeric_pct"] = (
                    numeric_count / len(values) * 100 if values else 0
                )

        except Exception as e:
            result["valid"] = False
            result["issues"].append(f"执行失败: {e}")

        return result

    def cross_validate(self, sql_results: List[Tuple], text_results: List[str]) -> Dict:
        """
        交叉验证：SQL 查出的关键数字是否在文本检索结果中出现。
        """
        result = {"consistent": True, "mismatches": []}
        if not sql_results or not text_results:
            return result

        # 提取 SQL 结果中的数字
        sql_numbers = set()
        for row in sql_results:
            for val in row:
                if val and re.match(r'^[\d,.-]+$', str(val).replace(" ", "")):
                    sql_numbers.add(str(val).replace(",", "").replace(" ", ""))

        # 检查是否在文本中出现
        text_blob = " ".join(text_results).replace(",", "").replace(" ", "")
        for num in sql_numbers:
            if len(num) < 3:  # 跳过太短的
                continue
            if num not in text_blob:
                result["consistent"] = False
                result["mismatches"].append(num)

        return result

    def run_golden_tests(self, golden_set: List[Dict]) -> Dict:
        """运行 Golden Query 测试集"""
        results = []
        for test in golden_set:
            sql = test["sql"]
            expected_rows = test.get("expected_rows", None)

            syntax = self.validate_sql_syntax(sql)
            if not syntax["valid"]:
                results.append({"test": test["name"], "passed": False,
                                "error": syntax["issues"]})
                continue

            exec_result = self.validate_result(sql)
            passed = exec_result["valid"]
            if expected_rows is not None:
                actual = exec_result["stats"].get("row_count", -1)
                if actual != expected_rows:
                    passed = False
                    exec_result["issues"].append(
                        f"预期{expected_rows}行, 实际{actual}行"
                    )

            results.append({"test": test["name"], "passed": passed,
                            "stats": exec_result.get("stats", {}),
                            "issues": exec_result.get("issues", [])})

        passed = sum(1 for r in results if r["passed"])
        return {"total": len(results), "passed": passed, "details": results}


def main():
    db_path = str(Path(__file__).parent.parent / "data_db" / "tables.db")
    validator = SQLValidator(db_path)

    print("=" * 60)
    print("SQL 召回校验")
    print("=" * 60)

    # 获取所有表
    tables = validator.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name!='_table_meta'"
    ).fetchall()
    print(f"数据表: {len(tables)} 个")

    # 测试查询
    test_queries = [
        "SELECT * FROM t_0 LIMIT 3",
        "SELECT COUNT(*) FROM t_1",
        "SELECT * FROM t_0 WHERE col_0 LIKE '%Sino%'",
        "DROP TABLE t_0",  # 应被拒绝
    ]
    print("\n语法校验:")
    for sql in test_queries:
        r = validator.validate_sql_syntax(sql)
        status = "[OK]" if r["valid"] else "[FAIL]"
        print(f"  {status} {sql[:50]}... {r.get('issues', '')}")

    # 结果合理性
    print("\n结果合理性:")
    for table in tables[:5]:
        sql = f"SELECT * FROM {table[0]}"
        r = validator.validate_result(sql)
        print(f"  {table[0]}: {r['stats']} {'[!]' if r['issues'] else ''}")
        for issue in r["issues"]:
            print(f"    - {issue}")

    print("\n[OK] 校验完成")


if __name__ == "__main__":
    main()
