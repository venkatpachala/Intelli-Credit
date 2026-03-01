import json
import os
import re

from dotenv import load_dotenv

# Load .env from project root (one level up from core/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ── The master extraction prompt ──────────────────────────────────────────────
EXTRACTION_PROMPT = """
You are a senior credit analyst at an Indian bank. 
You have received raw text extracted from financial documents (Annual Reports, Rating Reports, Legal filings, Bank Statements, GST Returns, etc.).
Your job is to extract ALL relevant credit information, including identifying risks mentioned in primary documents vs secondary research data, and return it as a SINGLE valid JSON object.

DOCUMENT TEXT:
{document_text}

COMPANY HINT (if known): {company_hint}

Extract and return a JSON object with EXACTLY these keys:
{{
  "company_snapshot": {{
    "name": "",
    "industry": "",
    "sector_risk_level": "Low/Medium/High",
    "years_in_operation": null,
    "market_position": "",
    "geographic_presence": []
  }},

  "financial_health_assessment": {{
    "revenue_trend": "Growing/Stable/Declining",
    "profitability_trend": "",
    "cash_flow_quality": "",
    "leverage_risk": "",
    "working_capital_cycle_days": null,
    "benchmark_comparison": {{
      "industry_average_ebitda_margin": null,
      "company_ebitda_margin": null,
      "industry_average_de_ratio": null,
      "company_de_ratio": null
    }},
    "red_flags": [],
    "strengths": []
  }},

  "banking_behavior_assessment": {{
    "cash_flow_volatility": "",
    "payment_discipline_score": null,
    "od_dependency_risk": "",
    "emi_servicing_track_record": ""
  }},

  "compliance_risk": {{
    "gst_risk": "",
    "tax_compliance_risk": "",
    "roc_filing_status": "",
    "regulatory_violations": []
  }},

  "litigation_risk": {{
    "active_cases_severity": "",
    "financial_impact_estimate": null,
    "criminal_exposure": false,
    "tax_exposure": ""
  }},

  "management_quality_assessment": {{
    "experience_level": "",
    "governance_practices_score": null,
    "related_party_risk": "",
    "credibility_risk": ""
  }},

  "industry_and_external_intelligence": {{
    "sector_growth_rate": null,
    "sector_outlook": "",
    "competitive_pressure": "",
    "recent_negative_news": [],
    "recent_positive_news": [],
    "macroeconomic_risk": ""
  }},

  "credit_rating_analysis": {{
    "current_rating": "",
    "rating_trend": "",
    "default_history": false
  }},

  "esg_assessment": {{
    "environmental_risk": "",
    "social_risk": "",
    "governance_risk": ""
  }},

  "overall_risk_scoring": {{
    "financial_risk_score": null,
    "compliance_risk_score": null,
    "management_risk_score": null,
    "industry_risk_score": null,
    "overall_credit_score": null,
    "risk_category": "Low/Moderate/High/Very High"
  }},

  "loan_recommendation_context": {{
    "recommended_loan_amount": null,
    "suggested_tenure": "",
    "collateral_required": "",
    "covenants_suggested": [],
    "key_conditions_precedent": []
  }},

  "critical_risk_flags_for_llm": []
}}

RULES:
1. For overall_risk_scoring, score each dimension from 0 (safest) to 10 (riskiest). overall_credit_score is the weighted average.
2. For risk_category: score 0-3 = "Low", 3-5 = "Moderate", 5-7 = "High", 7-10 = "Very High"
3. For critical_risk_flags_for_llm, list EVERY specific concern you found — data inconsistencies, sudden drops, high related party exposure, serious litigation, negative cash flow, etc.
4. For financial_health_assessment.red_flags, be specific (e.g. "Revenue declined 30% YoY from FY2023 to FY2024")
5. For financial_health_assessment.strengths, be specific (e.g. "ICR at 18x indicates very strong debt servicing capability")
6. For loan_recommendation_context.recommended_loan_amount, suggest a specific number based on the financials (use revenue/cash flow based sizing)
7. For benchmark_comparison, use publicly known industry averages for the company's sector
8. For banking_behavior_assessment, extract from bank statements / GST data if available. If not available, state "Not available — no bank statement provided"
9. For litigation_risk, scan for NCLT, IBC, court cases, legal notices, arbitration references
10. For esg_assessment, check for environmental fines, labor issues, governance concerns
11. Return ONLY valid JSON. No explanation text. No markdown. Just the JSON object.
12. Extract data from ALL periods mentioned in the document (multi-year comparison is critical)
13. For companies reporting in USD (like US-listed companies), use "million USD" or "billion USD" as unit
"""


class LLMStructurer:
    """
    Sends extracted text to LLM and returns structured credit data.
    Supports: Gemini (primary), Anthropic Claude, OpenAI GPT-4.
    Automatically picks up API keys from environment variables.
    """

    def __init__(self):
        self.gemini_key    = os.getenv("GEMINI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.openai_key    = os.getenv("OPENAI_API_KEY")
        self.provider      = self._detect_provider()

        # Read config from .env (with sensible defaults)
        self.gemini_model    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self.openai_model    = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.temperature     = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.max_context     = int(os.getenv("MAX_CONTEXT_CHARS", "200000"))

        print(f"      [LLM] Provider: {self.provider}")

    def _detect_provider(self) -> str:
        if self.gemini_key:
            return "gemini"
        if self.anthropic_key:
            return "anthropic"
        if self.openai_key:
            return "openai"
        return "demo"  # No API key — use hardcoded demo data

    def extract(self, raw_texts: list, company_hint: str = None) -> dict:
        """
        Takes list of page dicts from extractor.
        Returns structured dict.
        """
        if self.provider == "demo":
            print("      [LLM] No API key found — using DEMO structured data")
            from demo.bpsl_demo import get_demo_structured
            return get_demo_structured()

        # Combine all pages into one document (truncate if too long)
        # Use configured max context, fallback to 80K for non-Gemini providers
        max_chars = self.max_context if self.provider == "gemini" else min(self.max_context, 80_000)
        combined_text = self._combine_pages(raw_texts, max_chars=max_chars)
        prompt        = EXTRACTION_PROMPT.format(
            document_text = combined_text,
            company_hint  = company_hint or "Unknown",
        )

        if self.provider == "gemini":
            raw_response = self._call_gemini(prompt)
        elif self.provider == "anthropic":
            raw_response = self._call_anthropic(prompt)
        else:
            raw_response = self._call_openai(prompt)

        return self._parse_response(raw_response)

    def _combine_pages(self, raw_texts: list, max_chars: int = 200_000) -> str:
        """
        Combines all pages. Truncates to max_chars to stay within LLM context limits.
        Keeps first and last portions (most important for financial docs).
        """
        pages = []
        for page in raw_texts:
            pages.append(f"[PAGE {page['page']}]\n{page['text']}")

        full_text = "\n\n".join(pages)

        if len(full_text) <= max_chars:
            return full_text

        # Keep first 60% and last 40% if too long (financials often at end)
        keep_front = int(max_chars * 0.6)
        keep_back  = max_chars - keep_front
        truncated  = (
            full_text[:keep_front] +
            "\n\n[... MIDDLE SECTION TRUNCATED FOR CONTEXT LIMIT ...]\n\n" +
            full_text[-keep_back:]
        )
        print(f"      [LLM] Document truncated from {len(full_text):,} to {max_chars:,} chars")
        return truncated

    # ── GEMINI ────────────────────────────────────────────────
    def _call_gemini(self, prompt: str) -> str:
        """Calls Google Gemini API using the google-genai SDK."""
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "google-genai not installed.\n"
                "Run: pip install google-genai"
            )

        client = genai.Client(api_key=self.gemini_key)
        response = client.models.generate_content(
            model=self.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": self.temperature,
            },
        )
        return response.text

    # ── ANTHROPIC ─────────────────────────────────────────────
    def _call_anthropic(self, prompt: str) -> str:
        """Calls Anthropic Claude API."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic not installed.\nRun: pip install anthropic")

        client   = anthropic.Anthropic(api_key=self.anthropic_key)
        message  = client.messages.create(
            model      = self.anthropic_model,
            max_tokens = 8192,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    # ── OPENAI ────────────────────────────────────────────────
    def _call_openai(self, prompt: str) -> str:
        """Calls OpenAI GPT-4 API."""
        try:
            import openai
        except ImportError:
            raise ImportError("openai not installed.\nRun: pip install openai")

        client   = openai.OpenAI(api_key=self.openai_key)
        response = client.chat.completions.create(
            model    = self.openai_model,
            messages = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},  # forces JSON output
        )
        return response.choices[0].message.content

    # ── PARSE ─────────────────────────────────────────────────
    def _parse_response(self, raw: str) -> dict:
        """Safely parses LLM JSON response. Handles markdown fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()

        try:
            return {"fields": json.loads(cleaned), "parse_success": True, "provider": self.provider}
        except json.JSONDecodeError as e:
            print(f"      [LLM] JSON parse error: {e}")
            # Return raw text so we don't lose the data
            return {
                "fields": {},
                "raw_response": cleaned,
                "parse_success": False,
                "parse_error": str(e),
                "provider": self.provider,
            }
