#!/usr/bin/env python
"""
智能文档问答 Agent

用法:
    python main.py ask              # 交互问答
    python main.py ask "问题"        # 单次问答
    python test.py                  # 运行测试评估 (结果保存到 test_data_result/)
    python test.py --skip-api       # 仅验证模块导入 (免API)
"""
import sys
import logging

from config import LOG_LEVEL
from tools.retriever import load_retriever
from tools.document_tools import format_orchestrator_result
from agents.orchestrator import Orchestrator

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def interactive_qa(agent):
    print("\n" + "=" * 60)
    print("  智能文档问答 Agent")
    print("  Gateway → Retrieve → Answer → RedTeam → Quality → Final")
    print("  输入 'quit' 退出")
    print("=" * 60)
    count = 0
    while True:
        try:
            q = input(f"\n[?] 问题 [{count+1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            print("再见")
            break
        try:
            result = agent.ask(q)
            print("\n" + format_orchestrator_result(result))
            count += 1
        except Exception as e:
            logger.error(f"失败: {e}")
            print(f"[ERROR] {e}")


def run_ask(args):
    r = load_retriever()
    if not r:
        print("[!] 未找到知识库，请先运行: python build.py")
        return
    agent = Orchestrator(r)

    if len(args) > 1:
        question = " ".join(args[1:])
        result = agent.ask(question)
        print(format_orchestrator_result(result))
    else:
        interactive_qa(agent)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]
    if cmd == "ask":
        run_ask(args)
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
