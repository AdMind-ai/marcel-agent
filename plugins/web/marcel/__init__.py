"""Normalized search results using the same Router credential as chat."""
from agent.router_services import RouterServiceError, RouterServices, router_available
from agent.web_search_provider import WebSearchProvider


class MarcelSearchProvider(WebSearchProvider):
    def __init__(self, source):
        self.source = source

    @property
    def name(self):
        return f"marcel-{self.source}"

    @property
    def display_name(self):
        return f"Marcel Router — {self.source.title()}"

    def is_available(self):
        return router_available()

    def search(self, query, limit=5):
        try:
            if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 20:
                raise RouterServiceError("Search requires a query and an integer limit from 1 to 20.", "invalid_request")
            payload = {"provider": self.source, "query": query, "max_results": limit}
            response = RouterServices().json("POST", "/tools/search", payload=payload)
            data = response.get("data", response)
            rows = data.get("results", data.get("web")) if isinstance(data, dict) else None
            if isinstance(rows, dict):
                rows = rows.get("results")
            if not isinstance(rows, list):
                raise RouterServiceError("Router returned invalid search results.", "invalid_response")
            web = [
                {"title": row.get("title", ""), "url": row["url"],
                 "description": row.get("description") or row.get("snippet") or row.get("content") or "",
                 "position": index}
                for index, row in enumerate(rows[:limit], 1)
                if isinstance(row, dict) and isinstance(row.get("url"), str)
            ]
            return {"success": True, "data": {"web": web}}
        except RouterServiceError as exc:
            return {"success": False, "error": str(exc), "error_type": exc.error_type}


def register(ctx):
    for source in ("brave", "exa", "tavily", "perplexity"):
        ctx.register_web_search_provider(MarcelSearchProvider(source))
