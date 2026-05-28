from pathlib import Path

from app import local_tools


def test_web_search_news_baseball_heuristics_removed():
    assert not hasattr(local_tools, "_looks_news_like_query")
    assert not hasattr(local_tools, "_looks_baseball_query")
    assert not hasattr(local_tools, "_build_rss_candidates")
    assert not hasattr(local_tools, "_query_looks_specific")
    assert not hasattr(local_tools, "_extract_google_news_rss_results")


def test_web_search_source_has_no_rss_news_or_baseball_strategy():
    source = Path("app/local_tools.py").read_text(encoding="utf-8")
    forbidden = [
        "_looks_news_like_query",
        "_looks_baseball_query",
        "_build_rss_candidates",
        "_query_looks_specific",
        "_extract_google_news_rss_results",
        "news.google.com/rss/search",
        "mlb.com/feeds/news/rss.xml",
        "espn.com/espn/rss/mlb/news",
        "sports.yahoo.com/mlb/rss/",
        "www3.nhk.or.jp/rss/news/cat7.xml",
        "fallback:baseball_static_links",
    ]
    for item in forbidden:
        assert item not in source


def test_normalize_search_query_remains_available():
    assert hasattr(local_tools, "_normalize_search_query")


def test_expand_search_variants_remains_available():
    assert hasattr(local_tools, "_expand_search_variants")


def test_expand_search_variants_keeps_hex_forms_for_local_search():
    variants = set(local_tools._expand_search_variants("15h"))
    assert {"15h", "15 h", "0x15"} <= variants
