"""
Configuration for ArXiv Daily Paper Fetch.
Sensitive values are read from environment variables (set via GitHub Secrets).
Non-sensitive values are loaded from data/config.json.
"""

import os
import json

# ── Zotero API ──────────────────────────────────────────
ZOTERO_ID = os.environ.get("ZOTERO_ID", "")
ZOTERO_KEY = os.environ.get("ZOTERO_KEY", "")
ZOTERO_API_BASE = "https://api.zotero.org"

# ── ArXiv Query ─────────────────────────────────────────
# ArXiv category codes, e.g. "cs.CV+cs.LG+cs.AI+cs.CL"
ARXIV_QUERY = os.environ.get("ARXIV_QUERY", "cs.CV+cs.LG+cs.AI+cs.CL")
ARXIV_API_BASE = "http://export.arxiv.org/api/query"
MAX_PAPER_NUM = int(os.environ.get("MAX_PAPER_NUM", "10"))

# ── SiliconFlow Reranker ─────────────────────────────────
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
SILICONFLOW_RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"
SILICONFLOW_BATCH_SIZE = 64

# ── Followed Authors & Institutions ─────────────────────
_followed_authors = []
_followed_institutions = []


def load_user_config(config_path="data/config.json"):
    """Load followed authors/institutions from JSON config file."""
    global _followed_authors, _followed_institutions
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        _followed_authors = cfg.get("followed_authors", [])
        _followed_institutions = cfg.get("followed_institutions", [])
    except FileNotFoundError:
        print(f"[WARN] Config file {config_path} not found, using empty lists.")
        _followed_authors = []
        _followed_institutions = []


def get_followed_authors():
    return _followed_authors


def get_followed_institutions():
    return _followed_institutions
