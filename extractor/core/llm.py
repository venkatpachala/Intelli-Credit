import json
import os
import re


# ── The master extraction prompt ──────────────────────────────────────────────
EXTRACTION_PROMPT = """
You are a senior credit analyst at an Indian bank. 
You have received raw text extracted from financial documents.
Your job is to extract ALL relevant credit information and return it as a SINGLE valid JSON object.

DOCUMENT TEXT:
{document_text}

COMPANY HINT (if known): {company_hint}

Extract and return a JSON object with EXACTLY these keys:
{{
  "company_profile": {{
    "legal_name": "",
    "cin": "",
    "sector": "",
    "incorporation_year": null,
    "registered_address": "",
    "promoter_name": "",
    "promoter_stake_pct": null,
    "employee_count": null
  }},
  "income_statement": {{
    "periods": [],
    "total_revenue": {{}},
    "ebitda": {{}},
    "pat": {{}},
    "ebitda_margin_pct": {{}},
    "pat_margin_pct": {{}}
  }},
  "balance_sheet": {{
    "total_debt": {{}},
    "cash_and_equivalents": {{}},
    "gearing_ratio": {{}},
    "current_ratio": {{}},
    "debt_equity_ratio": {{}}
  }},
  "credit_metrics": {{
    "interest_coverage_ratio": {{}},
    "dscr": {{}},
    "working_capital_days": null,
    "existing_credit_facilities": []
  }},
  "operational_metrics": {{
    "key_products": [],
    "production_capacity": "",
    "sales_volume": {{}},
    "key_customers": [],
    "geographic_presence": []
  }},
  "audit_qualifications": [],
  "contingent_liabilities": [],
  "red_flags_found": [],
  "positive_factors": [],
  "fields_not_found": []
}}

RULES:
1. For any financial figure, use format: {{"value": <number>, "unit": "crore/lakh/tonne etc", "period": "FY2024", "confidence": "HIGH/MEDIUM/LOW"}}
2. confidence = HIGH if exact number found in doc, MEDIUM if inferred, LOW if guessed
3. If a field is not found in the document, add its name to "fields_not_found" list
4. For red_flags_found, include: circular trading, audit qualifications, high leverage, litigation, director issues, revenue mismatch
5. Return ONLY valid JSON. No explanation text. No markdown. Just the JSON object.
"""


class LLMStructurer:
    """
    Sends extracted text to LLM and returns structured credit data.
    Automatically picks up API keys from environment variables.
    """

    def __init__(self):
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.openai_key    = os.getenv("OPENAI_API_KEY")
        self.gemini_key    = os.getenv("GEMINI_API_KEY")
        self.gemini_model  = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.provider      = self._detect_provider()
        print(f"      [LLM] Provider: {self.provider}")

    def _detect_provider(self) -> str:
        if self.anthropic_key:
            return "anthropic"
        if self.openai_key:
            return "openai"
        if self.gemini_key:
            return "gemini"
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
        combined_text = self._combine_pages(raw_texts)
        prompt        = EXTRACTION_PROMPT.format(
            document_text = combined_text,
            company_hint  = company_hint or "Unknown",
        )

        if self.provider == "anthropic":
            raw_response = self._call_anthropic(prompt)
        elif self.provider == "gemini":
            raw_response = self._call_gemini(prompt)
        else:
            raw_response = self._call_openai(prompt)

        return self._parse_response(raw_response)

    def _combine_pages(self, raw_texts: list, max_chars: int = 80000) -> str:
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

    def _call_gemini(self, prompt: str) -> str:
        """Calls Google Gemini API."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai not installed.\nRun: pip install google-generativeai")

        genai.configure(api_key=self.gemini_key)
        model    = genai.GenerativeModel(self.gemini_model)
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )
        return response.text

    def _call_anthropic(self, prompt: str) -> str:
        """Calls Anthropic Claude API."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic not installed.\nRun: pip install anthropic")

        client   = anthropic.Anthropic(api_key=self.anthropic_key)
        message  = client.messages.create(
            model      = "claude-opus-4-6",
            max_tokens = 4096,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _call_openai(self, prompt: str) -> str:
        """Calls OpenAI GPT-4 API."""
        try:
            import openai
        except ImportError:
            raise ImportError("openai not installed.\nRun: pip install openai")

        client   = openai.OpenAI(api_key=self.openai_key)
        response = client.chat.completions.create(
            model    = "gpt-4o",
            messages = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},  # forces JSON output
        )
        return response.choices[0].message.content

    def _parse_response(self, raw: str) -> dict:
        """Safely parses LLM JSON response. Handles markdown fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()

        try:
            return {"fields": json.loads(cleaned), "parse_success": True}
        except json.JSONDecodeError as e:
            print(f"      [LLM] JSON parse error: {e}")
            # Return raw text so we don't lose the data
            return {
                "fields": {},
                "raw_response": cleaned,
                "parse_success": False,
                "parse_error": str(e),
            }
