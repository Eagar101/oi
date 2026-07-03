"""网页搜索模块：使用DuckDuckGo进行公开网页搜索"""

from ddgs import DDGS

from .schema import SearchResult


def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """执行DuckDuckGo搜索，返回结构化结果。超时或异常时返回空列表"""
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as e:
        print(f"  搜索'{query}'失败: {e}")
        return []

    return [
        SearchResult(
            title=r["title"],
            url=r["href"],
            snippet=r["body"],
        )
        for r in results
    ]
