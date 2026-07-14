"""文档解析：txt 直读，md 取纯文本"""

import re


def parse_file(filename: str, raw: bytes) -> str:
    """根据扩展名解析上传文件，返回纯文本"""
    name = filename.lower()
    if name.endswith(".txt"):
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return raw.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()

    if name.endswith(".md") or name.endswith(".markdown"):
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        return _strip_markdown(text).strip()

    # 未知扩展名按文本兜底
    return raw.decode("utf-8", errors="replace").strip()


def _strip_markdown(text: str) -> str:
    """去掉 markdown 语法噪声，保留正文"""
    # 去掉代码块（围栏）
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("` \n"), text)
    # 去掉图片
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # 链接保留文本
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # 去掉标题标记符
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 去掉行首引用符
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # 去掉无序列表标记
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    # 去掉行内代码反引号
    text = text.replace("`", "")
    return text
