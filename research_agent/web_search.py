"""
research_agent/web_search.py
Performs web research on a company using DuckDuckGo search.
Returns structured intelligence: news, litigation, sector data, promoter info.
"""

import os
import json
import re
from datetime import datetime

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False


def search_company(company_name: str, industry: str = "") -> dict:
    """
    Runs multiple targeted web searches for a company.
    Returns structured research data.
    """
    if not HAS_DDG:
        print("      [Research] duckduckgo-search not installed. Using empty research.")
        return _empty_research(company_name)

    print(f"      [Research] Searching for: {company_name}")
    
    results = {
        "company_name": company_name,
        "industry": industry,
        "searched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "negative_news": [],
        "positive_news": [],
        "litigation": [],
        "sector_outlook": [],
        "promoter_info": [],
        "regulatory_news": [],
    }

    queries = {
        "negative_news": f"{company_name} fraud scandal controversy lawsuit",
        "positive_news": f"{company_name} growth expansion revenue record",
        "litigation": f"{company_name} NCLT IBC litigation court case legal",
        "sector_outlook": f"{industry or company_name} sector outlook India 2024 2025",
        "promoter_info": f"{company_name} promoter director board management",
        "regulatory_news": f"{company_name} RBI SEBI regulatory compliance violation",
    }

    for category, query in queries.items():
        try:
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=5))
                for r in search_results:
                    results[category].append({
                        "title": r.get("title", ""),
                        "body": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
            print(f"      [Research] {category}: {len(results[category])} results")
        except Exception as e:
            print(f"      [Research] {category} search failed: {e}")

    return results


def _empty_research(company_name: str) -> dict:
    """Returns empty research structure when search is unavailable."""
    return {
        "company_name": company_name,
        "industry": "",
        "searched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "negative_news": [],
        "positive_news": [],
        "litigation": [],
        "sector_outlook": [],
        "promoter_info": [],
        "regulatory_news": [],
        "note": "Web search unavailable. Install: pip install duckduckgo-search"
    }
