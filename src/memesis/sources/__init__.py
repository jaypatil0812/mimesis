"""Phase 2 source adapters."""

from memesis.sources.bluesky import BlueskyAdapter, JetstreamEventNormalizer
from memesis.sources.hackernews import HackerNewsAdapter
from memesis.sources.openalex import OpenAlexAdapter
from memesis.sources.rss import RssAdapter
from memesis.sources.web import WebPageAdapter

__all__ = [
    "BlueskyAdapter",
    "HackerNewsAdapter",
    "JetstreamEventNormalizer",
    "OpenAlexAdapter",
    "RssAdapter",
    "WebPageAdapter",
]
