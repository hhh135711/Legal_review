"""答案生成：基于检索到的父块做抽取式生成（模板拼接 + 关键句抽取）。

生产环境此处调用商用LLM（强约束Prompt：必须依据检索内容、必须引用来源）；
demo采用抽取式策略，天然零幻觉，且保证每条结论可溯源。
"""
import re
from .retriever import tokenize


def extract_key_sentences(query: str, text: str, max_sents: int = 3) -> list[str]:
    qtoks = set(tokenize(query))
    sents = [s.strip() for s in re.split(r"(?<=[。；])", text) if len(s.strip()) > 8]
    scored = []
    for s in sents:
        overlap = len(qtoks & set(tokenize(s)))
        if overlap:
            scored.append((overlap, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_sents]]


def generate_answer(query: str, results: list[dict]) -> dict:
    citations, bullets = [], []
    for i, r in enumerate(results, 1):
        keys = extract_key_sentences(query, r["text"])
        if keys:
            bullets.append(f"{'；'.join(keys)}［{i}］")
        citations.append({
            "id": i, "doc": r["doc"], "score": r["score"],
            "snippet": r["hit_child"], "full_text": r["text"],
        })
    if not bullets:
        answer = "根据现有知识库未检索到足够相关的依据，建议补充文档或调整问题表述。（系统拒绝无依据作答）"
    else:
        answer = "依据公司内部制度与历史审查意见：\n\n" + "\n\n".join(f"• {b}" for b in bullets) \
                 + "\n\n以上结论均来自知识库原文，点击引用编号可查看原始条款复核。"
    return {"answer": answer, "citations": citations}
