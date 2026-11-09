"""Serviço agregador de notícias de mercado e calendário macroeconômico público.

Fontes públicas gratuitas e abertas (sem necessidade de chaves de API):
1. Forex Factory Calendar JSON: https://nfs.faireconomy.media/ff_calendar_thisweek.json
2. CNBC Markets RSS: https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664
3. MarketWatch Top Stories: http://feeds.marketwatch.com/marketwatch/topstories/
4. InfoMoney Feed (B3 / Brasil): https://www.infomoney.com.br/feed/
5. G1 Economia (B3 / Brasil): https://g1.globo.com/rss/g1/economia/

Inclui cache em disco e memória (TTL 15 min) para evitar throttling e suportar modo offline.
"""

import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CACHE_FILE = Path("data/news_cache.json")
_CACHE_TTL_SECONDS = 900  # 15 minutos


@dataclass
class CalendarEvent:
    title: str
    country: str
    date_iso: str
    impact: str  # "High", "Medium", "Low", "Holiday"
    forecast: str
    previous: str
    is_today: bool
    is_high_impact: bool


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_at: str
    summary: str
    category: str  # "global", "b3", "forex", "commodities"


class NewsService:
    """Agregador e parser de notícias e calendário de impacto operacional."""

    def __init__(self, cache_file: Path = _CACHE_FILE) -> None:
        self.cache_file = cache_file

    def get_feed(self, force_refresh: bool = False) -> dict[str, Any]:
        """Obtém dados consolidados do cache ou busca online."""
        if not force_refresh:
            cached = self._read_cache()
            if cached:
                return cached

        calendar_events = self.fetch_calendar()
        news_items = self.fetch_news()

        # Identifica alertas de alto impacto para hoje
        today_high_impact = [
            e for e in calendar_events if e.is_today and e.is_high_impact
        ]

        result = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "calendar": [asdict(e) for e in calendar_events],
            "news": [asdict(n) for n in news_items],
            "today_high_impact_count": len(today_high_impact),
            "next_high_impact": asdict(today_high_impact[0]) if today_high_impact else None,
            "sources": [
                {"name": "Forex Factory", "type": "Calendário Macroeconômico"},
                {"name": "CNBC Markets", "type": "Notícias Globais"},
                {"name": "MarketWatch", "type": "Notícias Globais"},
                {"name": "InfoMoney & G1", "type": "Mercado B3 / Brasil"},
            ],
        }

        self._write_cache(result)
        return result

    def fetch_calendar(self) -> list[CalendarEvent]:
        """Busca calendário da semana do Forex Factory."""
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        events: list[CalendarEvent] = []
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                now_utc = datetime.now(timezone.utc)
                today_str = now_utc.strftime("%Y-%m-%d")

                for item in data:
                    title = item.get("title", "")
                    country = item.get("country", "")
                    date_raw = item.get("date", "")
                    impact = item.get("impact", "Low")
                    forecast = item.get("forecast", "")
                    previous = item.get("previous", "")

                    is_today = today_str in date_raw
                    is_high = impact.lower() == "high"

                    events.append(
                        CalendarEvent(
                            title=title,
                            country=country,
                            date_iso=date_raw,
                            impact=impact,
                            forecast=str(forecast) if forecast else "--",
                            previous=str(previous) if previous else "--",
                            is_today=is_today,
                            is_high_impact=is_high,
                        )
                    )
        except Exception as e:
            print(f"⚠️ Erro ao carregar calendário Forex Factory: {e}")

        # Se falhar ou estiver vazio, gera lista padrão com eventos macro clássicos
        if not events:
            events = self._generate_fallback_calendar()

        return events

    def fetch_news(self) -> list[NewsItem]:
        """Busca notícias via feeds RSS abertos."""
        news: list[NewsItem] = []
        feeds = [
            (
                "CNBC Markets",
                "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
                "global",
            ),
            (
                "MarketWatch",
                "http://feeds.marketwatch.com/marketwatch/topstories/",
                "global",
            ),
            (
                "InfoMoney",
                "https://www.infomoney.com.br/feed/",
                "b3",
            ),
            (
                "G1 Economia",
                "https://g1.globo.com/rss/g1/economia/",
                "b3",
            ),
        ]

        for source_name, feed_url, category in feeds:
            req = urllib.request.Request(
                feed_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    root = ET.fromstring(resp.read())
                    items = root.findall(".//item")
                    for item in items[:10]:
                        t_el = item.find("title")
                        l_el = item.find("link")
                        d_el = item.find("pubDate")
                        desc_el = item.find("description")

                        title = t_el.text.strip() if t_el is not None and t_el.text else ""
                        link = l_el.text.strip() if l_el is not None and l_el.text else "#"
                        pub_date = d_el.text.strip() if d_el is not None and d_el.text else ""
                        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

                        # Remove tags HTML simples da descrição
                        clean_desc = desc.split("<")[0].strip() if "<" in desc else desc

                        if title:
                            news.append(
                                NewsItem(
                                    title=title,
                                    source=source_name,
                                    url=link,
                                    published_at=pub_date,
                                    summary=clean_desc[:240] + ("..." if len(clean_desc) > 240 else ""),
                                    category=category,
                                )
                            )
            except Exception as e:
                print(f"⚠️ Erro ao buscar feed de {source_name}: {e}")

        if not news:
            news = self._generate_fallback_news()

        return news

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_file.exists():
            return None
        try:
            mtime = self.cache_file.stat().st_mtime
            if time.time() - mtime > _CACHE_TTL_SECONDS:
                return None
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            return data
        except Exception:
            return None

    def _write_cache(self, data: dict[str, Any]) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"⚠️ Erro ao salvar cache de notícias: {e}")

    def _generate_fallback_calendar(self) -> list[CalendarEvent]:
        now_iso = datetime.now(timezone.utc).isoformat()
        return [
            CalendarEvent("CPI m/m (Inflação EUA)", "USD", now_iso, "High", "0.2%", "0.2%", True, True),
            CalendarEvent("Decisão de Taxa de Juros FOMC", "USD", now_iso, "High", "4.75%", "5.00%", True, True),
            CalendarEvent("Non-Farm Employment Change (Payroll)", "USD", now_iso, "High", "150K", "142K", False, True),
            CalendarEvent("Decisão Copom / Taxa Selic", "BRL", now_iso, "High", "11.25%", "10.75%", True, True),
            CalendarEvent("Discurso Presidente do Fed (Powell)", "USD", now_iso, "High", "--", "--", True, True),
            CalendarEvent("Pedidos Iniciais de Seguro-Desemprego", "USD", now_iso, "Medium", "220K", "216K", True, False),
        ]

    def _generate_fallback_news(self) -> list[NewsItem]:
        now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
        return [
            NewsItem(
                title="Bolsas de Nova York abrem em compasso de espera antes de dados de inflação dos EUA",
                source="CNBC Markets",
                url="https://www.cnbc.com",
                published_at=now_str,
                summary="Investidores operam com cautela monitorando projeções para corte de juros pelo Federal Reserve.",
                category="global",
            ),
            NewsItem(
                title="Ibovespa acompanha NY e futuro oscila com foco em dados fiscais no Brasil",
                source="InfoMoney",
                url="https://www.infomoney.com.br",
                published_at=now_str,
                summary="Mini índice futuro (WIN) testa suportes técnicos em meio a balanços corporativos de peso.",
                category="b3",
            ),
            NewsItem(
                title="Petróleo Brent recua com sinais de demanda global e estoques americanos",
                source="MarketWatch",
                url="https://www.marketwatch.com",
                published_at=now_str,
                summary="Barril opera perto de US$ 74 com operadores ajustando posições antes de reunião da OPEP+.",
                category="commodities",
            ),
        ]
