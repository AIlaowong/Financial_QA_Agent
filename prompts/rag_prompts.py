"""
简易 RAG Agent 的 Prompt 模板。
"""

SYSTEM_PROMPT = """你是一个专业的金融文档问答助手。
请根据提供的文档片段回答问题。

要求:
1. 答案必须基于提供的文档内容，不得编造
2. 如果文档中没有相关信息，请明确说"无法回答"
3. 回答时注明信息来源的页码
4. 对于财务数据，保留原始格式和单位"""


def build_qa_prompt(question: str, sources_text: str) -> str:
    """构建问答 prompt"""
    return f"""请根据以下文档内容回答问题。

## 文档内容
{sources_text}

## 问题
{question}

## 回答"""
