"""
自检工具 — 数字回溯验证、来源相关性检查、自检结果格式化。
"""
import re
from typing import List, Tuple


def check_numbers_in_sources(answer: str, sources_text: str) -> dict:
    """检查答案中的数字是否在来源文档中出现"""
    numbers = re.findall(r'[\d,]+\.?\d*', answer)
    verified = []
    unverified = []

    for num in numbers:
        num_clean = num.replace(",", "")
        if num_clean in sources_text.replace(",", ""):
            verified.append(num)
        else:
            unverified.append(num)

    return {
        "numbers_in_answer": numbers,
        "verified": verified,
        "unverified": unverified,
        "all_verified": len(unverified) == 0,
    }


def check_source_relevance(answer: str, sources_text: str) -> float:
    """检查答案与来源文档的相关性（基于关键词重叠）"""
    answer_words = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', answer.lower()))
    source_words = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', sources_text.lower()))

    if not answer_words:
        return 0.0

    overlap = answer_words & source_words
    return len(overlap) / len(answer_words)


def format_self_check_result(check_result: dict) -> str:
    """格式化自检结果为可读文本"""
    lines = ["[SelfCheck] 自检验证:"]

    nums = check_result.get("numbers_in_answer", [])
    verified = check_result.get("verified", [])
    unverified = check_result.get("unverified", [])

    if nums:
        lines.append(f"  数字验证: {len(verified)}/{len(nums)} 已回溯")
        if unverified:
            lines.append(f"  未回溯数字: {', '.join(unverified)}")

    relevance = check_result.get("relevance_score")
    if relevance is not None:
        lines.append(f"  来源相关性: {relevance:.2f}")

    issues = check_result.get("issues", [])
    if issues:
        lines.append(f"  问题: {'; '.join(issues)}")

    return "\n".join(lines)
