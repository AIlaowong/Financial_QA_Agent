#!/usr/bin/env python
"""
测试评估脚本 — Agent 全链路并发测试。

用法:
    python test.py                   # 运行测试评估 (8 线程并发，结果保存到 test_data_result/)
    python test.py --concurrency 4   # 4 线程并发
    python test.py --skip-api        # 仅验证模块导入 (免API)
"""
import sys
import logging

from config import LOG_LEVEL
from tools.retriever import load_retriever
from agents.orchestrator import Orchestrator

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test")


def main():
    args = sys.argv[1:]

    if "--skip-api" in args:
        print("[OK] 模块导入验证通过")
        return

    r = load_retriever()
    if not r:
        print("[!] 未找到知识库，请先运行: python build.py")
        return

    # 解析并发数
    concurrency = 8
    for i, arg in enumerate(args):
        if arg == "--concurrency" and i + 1 < len(args):
            concurrency = int(args[i + 1])

    def agent_factory():
        """每个线程创建独立的 Orchestrator 实例"""
        retriever = load_retriever()
        return Orchestrator(retriever)

    from tests.run_evaluation import run_evaluation
    run_evaluation(agent_factory, concurrency=concurrency)


if __name__ == "__main__":
    main()
