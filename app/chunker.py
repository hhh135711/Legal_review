"""父子切块模块：父块保留完整条款上下文，子块用于细粒度检索。"""
from dataclasses import dataclass, field
from typing import List
import itertools

_id_counter = itertools.count(1)

PARENT_SIZE = 600   # demo语料较短，按字符近似token；生产为1200 token
CHILD_SIZE = 150    # 生产为300 token


@dataclass
class Chunk:
    chunk_id: int
    doc_name: str
    text: str
    parent_id: int | None = None      # 子块指向父块
    children: List[int] = field(default_factory=list)


def split_parents(text: str, size: int = PARENT_SIZE) -> List[str]:
    """按空行（条款边界）切分，超长段落继续按size硬切。"""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                out.append(buf)
            while len(p) > size:
                out.append(p[:size])
                p = p[size:]
            buf = p
    if buf:
        out.append(buf)
    return out


def split_children(parent_text: str, size: int = CHILD_SIZE) -> List[str]:
    """子块优先按句号/分号边界切。"""
    import re
    sents = [s for s in re.split(r"(?<=[。；])", parent_text) if s.strip()]
    out, buf = [], ""
    for s in sents:
        if len(buf) + len(s) <= size:
            buf += s
        else:
            if buf:
                out.append(buf.strip())
            buf = s
    if buf.strip():
        out.append(buf.strip())
    return out


def build_chunks(doc_name: str, text: str) -> tuple[List[Chunk], List[Chunk]]:
    """返回 (父块列表, 子块列表)。"""
    parents, children = [], []
    for ptext in split_parents(text):
        parent = Chunk(next(_id_counter), doc_name, ptext)
        for ctext in split_children(ptext):
            child = Chunk(next(_id_counter), doc_name, ctext, parent_id=parent.chunk_id)
            parent.children.append(child.chunk_id)
            children.append(child)
        parents.append(parent)
    return parents, children
