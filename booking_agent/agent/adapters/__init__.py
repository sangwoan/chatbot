from .base import Adapter


def make_adapter(name: str, **kwargs) -> Adapter:
    if name == "nol":
        from .nol import NolAdapter

        return NolAdapter(**kwargs)
    if name == "http_json":
        from .http_json import HttpJsonAdapter

        return HttpJsonAdapter(**kwargs)
    if name == "html":
        from .html import HtmlAdapter

        return HtmlAdapter(**kwargs)
    raise ValueError(f"알 수 없는 어댑터: {name}")
