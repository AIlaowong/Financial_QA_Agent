"""
Reranker 精排 Prompt 模板。
"""
RERANKER_SYSTEM = "You are a relevance scorer. Output only a JSON with a 'score' field (0.0 to 1.0)."

RERANKER_USER_TEMPLATE = """Query: {query}

Document: {document}

Rate the relevance of this document to the query on a scale of 0.0 to 1.0."""
