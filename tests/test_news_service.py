"""Testes do serviço agregador de notícias e calendário macroeconômico."""

from pathlib import Path
from unittest.mock import patch

from smc_trader.config import load_config
from smc_trader.services.news_service import CalendarEvent, NewsItem, NewsService
from smc_trader.ui.server import SMCRequestHandler


def test_news_service_fallback_on_error(tmp_path):
    """Garante que fallbacks resilientes são gerados se as redes falharem."""
    cache_file = tmp_path / "test_news_cache.json"
    service = NewsService(cache_file=cache_file)

    with patch("urllib.request.urlopen", side_effect=Exception("Network disconnected")):
        feed = service.get_feed(force_refresh=True)

    assert "calendar" in feed
    assert "news" in feed
    assert "updated_at" in feed
    assert len(feed["calendar"]) >= 5
    assert len(feed["news"]) >= 3
    assert cache_file.exists()


def test_news_service_cache_hit(tmp_path):
    """Testa leitura e escrita do cache com TTL."""
    cache_file = tmp_path / "test_news_cache.json"
    service = NewsService(cache_file=cache_file)

    feed1 = service.get_feed(force_refresh=False)
    assert cache_file.exists()

    # Segunda chamada deve usar o cache sem tentar rede
    with patch("urllib.request.urlopen", side_effect=AssertionError("Não deveria chamar rede!")):
        feed2 = service.get_feed(force_refresh=False)

    assert feed1["updated_at"] == feed2["updated_at"]
    assert len(feed1["calendar"]) == len(feed2["calendar"])


def test_calendar_event_and_news_dataclasses():
    """Testa criação e propriedades das dataclasses de eventos e notícias."""
    ev = CalendarEvent(
        title="CPI m/m",
        country="USD",
        date_iso="2026-11-09T13:30:00Z",
        impact="High",
        forecast="0.2%",
        previous="0.2%",
        is_today=True,
        is_high_impact=True,
    )
    assert ev.is_today is True
    assert ev.is_high_impact is True

    item = NewsItem(
        title="Fed mantém taxas de juros",
        source="CNBC Markets",
        url="https://cnbc.com/news",
        published_at="2026-11-09",
        summary="Resumo do anúncio do Fed",
        category="global",
    )
    assert item.category == "global"
    assert "CNBC" in item.source


def test_api_get_and_post_news(tmp_path):
    """Testa handlers _handle_get_news e _handle_post_news_refresh no SMCRequestHandler."""
    handler = SMCRequestHandler.__new__(SMCRequestHandler)
    handler.data_root = tmp_path
    handler.app_cfg = load_config(Path("config/default.yaml"))

    sent_data = {}

    def mock_send_json(data, status=200):
        nonlocal sent_data
        sent_data = data

    handler._send_json = mock_send_json

    # Teste GET /api/news
    handler._handle_get_news()
    assert "calendar" in sent_data
    assert "news" in sent_data
    assert "sources" in sent_data

    # Teste POST /api/news/refresh
    handler._handle_post_news_refresh()
    assert "calendar" in sent_data
    assert "news" in sent_data
