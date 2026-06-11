"""检索策略路由：生产环境用LLM+提示词判断，demo用等价规则引擎，异常自动回退直接检索。"""
import re

STRATEGIES = {
    "direct": "直接检索",
    "hyde": "HyDE 假设答案检索",
    "decompose": "子问题拆分检索",
    "stepback": "回溯简化检索",
}


def choose_strategy(query: str) -> dict:
    """返回 {strategy, reason, sub_queries}。任何异常回退 direct。"""
    try:
        q = query.strip()
        # 多议题复杂问题 → 拆分
        if any(k in q for k in ("和", "以及", "同时", "哪些", "分别")) and len(q) > 18:
            subs = [s for s in re.split(r"[和及，,？?]", q) if len(s.strip()) >= 4][:3]
            if len(subs) >= 2:
                return {"strategy": "decompose", "reason": "检测到多议题复合问题，拆分为子问题分别检索",
                        "sub_queries": [s.strip() for s in subs]}
        # 假设性/开放性问题 → HyDE
        if any(k in q for k in ("如果", "假设", "怎么办", "如何处理", "风险")):
            return {"strategy": "hyde", "reason": "开放性问题，先生成假设答案扩展语义再检索",
                    "sub_queries": [q + " 法务审查意见 风险案例 红线条款"]}
        # 过于具体的细节问题 → 回溯到上位概念
        if re.search(r"\d{4}年|案例[A-Z一二三四]|第[一二三四五六七八九十]+条", q):
            general = re.sub(r"\d{4}年|案例[A-Z一二三四]|第[一二三四五六七八九十]+条", "", q)
            return {"strategy": "stepback", "reason": "细节型问题，抽象为上位概念后检索",
                    "sub_queries": [general.strip() or q]}
        return {"strategy": "direct", "reason": "标准事实型问题，直接检索", "sub_queries": [q]}
    except Exception:
        # 兜底：策略异常回退直接检索
        return {"strategy": "direct", "reason": "策略路由异常，回退直接检索（兜底）", "sub_queries": [query]}
