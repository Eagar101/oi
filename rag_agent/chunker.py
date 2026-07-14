"""递归文本切片：按段落→换行→句号逐级降级，贪心打包"""

from .schema import Chunk


def recursive_split(text: str, max_size: int = 500, overlap: int = 100) -> list[Chunk]:
    """将长文本切分为若干 Chunk，每片不超过 max_size 字，片间有 overlap 字重叠"""
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_size:
        return [Chunk(seq=0, content=text, token_count=len(text))]

    chunks: list[str] = []
    _split_recursive(text, max_size, overlap, chunks)

    result = []
    for i, c in enumerate(chunks):
        result.append(Chunk(seq=i, content=c, token_count=len(c)))
    return result


def _split_recursive(text: str, max_size: int, overlap: int, out: list[str]) -> None:
    """递归切分：尝试按分隔符切，切不出足够小的就降级到更细的分隔符"""
    if len(text) <= max_size:
        out.append(text)
        return

    # 按粒度从粗到细尝试
    for sep in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", " "):
        if sep not in text:
            continue
        parts = text.split(sep)
        if len(parts) < 2:
            continue
        buf = ""
        for p in parts:
            piece = p if sep in (" ",) else p + sep
            if len(buf) + len(piece) <= max_size:
                buf += piece
            else:
                if buf:
                    out.append(buf)
                # 单个 part 本身超长，继续递归降级
                if len(piece) > max_size:
                    _split_recursive(piece, max_size, overlap, out)
                else:
                    out.append(piece)
                buf = ""
        if buf:
            out.append(buf)
        _apply_overlap(out, overlap)
        return

    # 所有分隔符都不适用，硬切
    for i in range(0, len(text), max_size):
        out.append(text[i : i + max_size])
    _apply_overlap(out, overlap)


def _apply_overlap(chunks: list[str], overlap: int) -> None:
    """给相邻切片加上尾部/头部重叠"""
    if overlap <= 0 or len(chunks) < 2:
        return
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap:]
        if not chunks[i].startswith(prev_tail):
            chunks[i] = prev_tail + chunks[i]
