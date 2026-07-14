"""迭代式文本切片：按段落→句子→硬切逐级降级，贪心打包，无递归"""

from .schema import Chunk

# 分隔符按粒度从粗到细
_PARAGRAPH_SEPS = ("\n\n", "\n")
_SENTENCE_SEPS = ("。", "！", "？", "！", "?", ".", "!?", "?!")
_WORD_SEP = " "


def recursive_split(text: str, max_size: int = 500, overlap: int = 100) -> list[Chunk]:
    """将长文本切分为若干 Chunk，每片不超过 max_size 字，片间有 overlap 字重叠

    名字保留以兼容调用方，内部为迭代实现（无递归栈风险）。
    """
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= max_size:
        return [Chunk(seq=0, content=text, token_count=len(text))]

    pieces = _split_to_pieces(text, max_size)
    # 贪心打包：预留 overlap 空间，打包后追加前片尾部不会超 max_size
    budget = max(1, max_size - overlap)
    packed = _pack(pieces, budget)
    # 加重叠
    _apply_overlap(packed, overlap)

    return [Chunk(seq=i, content=c, token_count=len(c)) for i, c in enumerate(packed)]


def _split_to_pieces(text: str, max_size: int) -> list[str]:
    """把文本切成不超过 max_size 的小片段（迭代降级）"""
    # 先按段落切
    pieces: list[str] = []
    _split_level(text, _PARAGRAPH_SEPS, max_size, pieces)
    # 仍超长的再按句子切
    refined: list[str] = []
    for p in pieces:
        if len(p) <= max_size:
            refined.append(p)
        else:
            _split_level(p, _SENTENCE_SEPS, max_size, refined)
    # 仍超长的硬切
    final: list[str] = []
    for p in refined:
        if len(p) <= max_size:
            final.append(p)
        else:
            for i in range(0, len(p), max_size):
                final.append(p[i : i + max_size])
    return final


def _split_level(text: str, seps: tuple[str, ...], max_size: int, out: list[str]) -> None:
    """按给定分隔符集合切分，仍超长的原样保留（留给下一级处理）"""
    if len(text) <= max_size:
        out.append(text)
        return

    # 选第一个存在于文本中的分隔符
    sep = next((s for s in seps if s and s in text), None)
    if sep is None:
        out.append(text)  # 无法切，交给下一级
        return

    buf = ""
    for part in text.split(sep):
        piece = part + sep
        if len(piece) > max_size:
            if buf:
                out.append(buf)
                buf = ""
            out.append(piece)  # 超长片段留给下一级
            continue
        if len(buf) + len(piece) <= max_size:
            buf += piece
        else:
            if buf:
                out.append(buf)
            buf = piece
    if buf:
        out.append(buf)


def _pack(pieces: list[str], max_size: int) -> list[str]:
    """把相邻小片段贪心合并到不超过 max_size"""
    packed: list[str] = []
    buf = ""
    for p in pieces:
        if len(buf) + len(p) <= max_size:
            buf += p
        else:
            if buf:
                packed.append(buf)
            buf = p
    if buf:
        packed.append(buf)
    # 兜底：合并后仍超长的（理论上不该出现）硬切
    safe: list[str] = []
    for c in packed:
        if len(c) <= max_size:
            safe.append(c)
        else:
            for i in range(0, len(c), max_size):
                safe.append(c[i : i + max_size])
    return safe


def _apply_overlap(chunks: list[str], overlap: int) -> None:
    """给相邻切片加上前一片尾部的重叠（原地修改）"""
    if overlap <= 0 or len(chunks) < 2:
        return
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap:]
        if not chunks[i].startswith(prev_tail):
            chunks[i] = prev_tail + chunks[i]