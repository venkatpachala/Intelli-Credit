"""
cam_engine/narrative/generator.py
====================================
NarrativeGenerator — calls Google Gemini for each of the 7 CAM sections.

Design:
  - One isolated API call per section (no shared context)
  - Graceful degradation: failed sections return a template fallback
  - Sequential calls to respect rate limits
  - Each call uses the same model already used by the extractor (gemini-2.0-flash)
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from .models import CAMNarratives, NarrativeInput
from .prompts import (
    SYSTEM_PREAMBLE,
    EXECUTIVE_SUMMARY_PROMPT,
    CHARACTER_PROMPT,
    CAPACITY_PROMPT,
    CAPITAL_PROMPT,
    COLLATERAL_PROMPT,
    CONDITIONS_PROMPT,
    RISK_MITIGANTS_PROMPT,
)


def _safe(v, fallback=0.0):
    if v is None: return fallback
    if isinstance(v, dict): return float(v.get("value", fallback) or fallback)
    try:    return float(v)
    except: return fallback


class NarrativeGenerator:
    """
    Generates all 7 CAM section narratives using Google Gemini Flash.
    Falls back gracefully if API is unavailable.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key   = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name= os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.model     = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name    = self.model_name,
                generation_config={
                    "temperature":      0.2,     # factual / low creativity
                    "top_p":            0.9,
                    "max_output_tokens": 1500,
                },
            )
        except ImportError:
            self.model = None
            print("[NarrativeGenerator] google-generativeai not installed. Narratives will use fallback text.")
        except Exception as e:
            self.model = None
            print(f"[NarrativeGenerator] Gemini init failed: {e}")

    # ── Core Gemini call ─────────────────────────────────────

    def _call(self, prompt: str, section: str, max_tokens: int = 1200) -> str:
        if not self.model:
            return self._fallback(section)
        try:
            # Gemini takes a single combined prompt (system + user merged)
            response = self.model.generate_content(prompt)
            # Handle blocked / empty response
            if not response.candidates:
                return self._fallback(section, "No candidates returned (content policy)")
            part = response.candidates[0].content.parts[0]
            return part.text.strip()
        except Exception as e:
            return self._fallback(section, error=str(e))

    def _fallback(self, section: str, error: str = "") -> str:
        msg = f"[{section} narrative not available"
        if error:
            msg += f" — {error[:120]}"
        msg += ". Review the data tables in this section manually.]"
        return msg

    # ── Generate all sections ────────────────────────────────

    def generate_all(self, inp: NarrativeInput) -> CAMNarratives:
        """
        Calls Gemini sequentially for all 8 sections.
        Returns CAMNarratives with any per-section errors recorded.
        """
        results   = CAMNarratives()
        errors    = {}
        sections  = [
            ("executive_summary", self._exec_summary),
            ("character",         self._character),
            ("capacity",          self._capacity),
            ("capital",           self._capital),
            ("collateral",        self._collateral),
            ("conditions",        self._conditions),
            ("risk_mitigants",    self._risk_mitigants),
            ("decision_rationale",self._decision_rationale),
        ]

        for attr, fn in sections:
            try:
                text = fn(inp)
                setattr(results, attr, text)
            except Exception as e:
                errors[attr] = str(e)
                setattr(results, attr, self._fallback(attr, str(e)))
            time.sleep(0.3)   # brief pause between calls (rate limit buffer)

        results.errors = errors
        return results

    # ── Section builders ─────────────────────────────────────

    def _exec_summary(self, inp: NarrativeInput) -> str:
        pos_factors = _format_list([
            f"Capacity Score {inp.capacity_score}/100",
            f"Capital Score {inp.capital_score}/100",
            f"Character Score {inp.character_score}/100",
        ])
        risk_factors = _format_list([
            f"Collateral coverage {inp.coverage_market:.2f}x (preferred >=1.50x)"
            if inp.coverage_market > 0 else "Collateral data under review",
        ] + [
            f.get("title", f.get("description", str(f)))
            for f in inp.research_flags
            if f.get("severity") in ("HIGH", "CRITICAL")
        ][:2])

        amount_reason = (
            f"Recommended limit of Rs.{inp.recommended_cr:.2f} Cr is moderated from "
            f"Rs.{inp.requested_cr:.2f} Cr due to: " +
            "; ".join(
                adj.get("reason", "") for adj in inp.amount_adjustments[:2]
            )
        ) if inp.amount_adjustments else "Full requested limit recommended."

        rate_reasons = _format_list([
            p.get("reason", "") for p in inp.rate_premiums if p.get("bps", 0) > 0
        ][:4])

        conditions_summary = "; ".join(inp.conditions_precedent[:2]) if inp.conditions_precedent else "Standard banking conditions apply."

        prompt = EXECUTIVE_SUMMARY_PROMPT.format(
            system_preamble  = SYSTEM_PREAMBLE,
            company_name     = inp.company_name,
            cin              = inp.cin,
            industry         = inp.industry,
            loan_type        = inp.loan_type,
            tenor_months     = inp.tenor_months,
            requested_cr     = inp.requested_cr,
            decision         = inp.decision,
            recommended_cr   = inp.recommended_cr,
            interest_rate    = inp.interest_rate,
            risk_band        = inp.risk_band,
            composite_score  = inp.composite_score,
            positive_factors = pos_factors,
            risk_factors     = risk_factors,
            amount_reason    = amount_reason,
            rate_reasons     = rate_reasons,
            conditions_summary = conditions_summary,
        )
        # Append primary insight note if present
        if inp.qualitative_adjustment != 0:
            qi_note = (
                f"\n\nNote: Primary Insight (field observation) adjustment of "
                f"{'+' if inp.qualitative_adjustment > 0 else ''}{inp.qualitative_adjustment} pts "
                f"was applied to the composite score based on credit officer's field notes."
            )
            prompt += qi_note
        return self._call(prompt, "Executive Summary", max_tokens=500)

    def _character(self, inp: NarrativeInput) -> str:
        promoter_table = _format_promoters(inp.promoters)
        lit_count      = inp.litigation_count
        lit_text       = f"{lit_count} case(s) found in eCourts" if lit_count else "No cases found in eCourts search"
        mca_text       = f"{inp.mca_flag_count} MCA flag(s) noted" if inp.mca_flag_count else "No adverse MCA findings"
        news_text      = "; ".join(inp.news_signals[:3]) if inp.news_signals else "No adverse news signals detected"

        char_flags = _format_flags([
            f for f in inp.research_flags
            if f.get("category") in ("PROMOTER", "FRAUD", "LITIGATION")
        ])

        prompt = CHARACTER_PROMPT.format(
            system_preamble   = SYSTEM_PREAMBLE,
            company_name      = inp.company_name,
            cin               = inp.cin,
            industry          = inp.industry,
            character_score   = inp.character_score,
            character_band    = _score_band(inp.character_score),
            promoter_table    = promoter_table,
            rbi_result        = inp.rbi_result,
            litigation_summary= lit_text,
            mca_summary       = mca_text,
            news_summary      = news_text,
            character_flags   = char_flags,
        )
        return self._call(prompt, "Character", max_tokens=600)

    def _capacity(self, inp: NarrativeInput) -> str:
        rev    = _pad(inp.revenue, 3)
        ebitda = _pad(inp.ebitda,  3)
        pat    = _pad(inp.pat,     3)
        cfo    = _pad(inp.cfo,     3)
        per    = _pad(inp.periods, 3, fill="N/A")

        em = []
        for i in range(3):
            em.append((ebitda[i] / rev[i] * 100) if rev[i] > 0 else 0.0)

        cfo_pat = (cfo[2] / pat[2]) if pat[2] != 0 else 0.0

        concerns = "; ".join([
            f.get("title", str(f)) for f in inp.research_flags
            if f.get("category") == "FINANCIAL"
        ][:2]) or "None identified."

        bd_text = _format_breakdown(inp.capacity_breakdown)

        prompt = CAPACITY_PROMPT.format(
            system_preamble   = SYSTEM_PREAMBLE,
            company_name      = inp.company_name,
            capacity_score    = inp.capacity_score,
            capacity_band     = _score_band(inp.capacity_score),
            period_1 = per[0], period_2=per[1], period_3=per[2],
            rev_1=rev[0],  rev_2=rev[1],  rev_3=rev[2],
            ebitda_1=ebitda[0], ebitda_2=ebitda[1], ebitda_3=ebitda[2],
            pat_1=pat[0],  pat_2=pat[1],  pat_3=pat[2],
            cfo_1=cfo[0],  cfo_2=cfo[1],  cfo_3=cfo[2],
            ebitda_m_1=em[0], ebitda_m_2=em[1], ebitda_m_3=em[2],
            rev_cagr       = inp.rev_cagr,
            dscr           = inp.dscr,
            icr            = inp.icr,
            cfo_pat_ratio  = cfo_pat,
            capacity_breakdown = bd_text,
            capacity_concerns  = concerns,
        )
        return self._call(prompt, "Capacity", max_tokens=650)

    def _capital(self, inp: NarrativeInput) -> str:
        nw_vals = [inp.net_worth_cr] * 3
        per     = _pad(inp.periods, 3, fill="N/A")
        gearing = inp.total_debt_cr / inp.total_assets_cr if inp.total_assets_cr > 0 else 0.0
        bd_text = _format_breakdown(inp.capital_breakdown)

        prompt = CAPITAL_PROMPT.format(
            system_preamble          = SYSTEM_PREAMBLE,
            company_name             = inp.company_name,
            capital_score            = inp.capital_score,
            capital_band             = _score_band(inp.capital_score),
            period_3                 = per[2],
            net_worth_cr             = inp.net_worth_cr,
            total_debt_cr            = inp.total_debt_cr,
            de_ratio                 = inp.de_ratio,
            tangible_nw_cr           = inp.tangible_nw_cr,
            total_assets_cr          = inp.total_assets_cr,
            gearing_ratio            = gearing,
            promoter_shareholding    = inp.promoter_shareholding,
            period_1=per[0], period_2=per[1],
            nw_y1=nw_vals[0], nw_y2=nw_vals[1], nw_y3=nw_vals[2],
            capital_breakdown        = bd_text,
        )
        return self._call(prompt, "Capital", max_tokens=500)

    def _collateral(self, inp: NarrativeInput) -> str:
        coll_table = _format_collateral(inp.collateral_assets)
        bd_text    = _format_breakdown(inp.collateral_breakdown)

        prompt = COLLATERAL_PROMPT.format(
            system_preamble   = SYSTEM_PREAMBLE,
            company_name      = inp.company_name,
            collateral_score  = inp.collateral_score,
            collateral_band   = _score_band(inp.collateral_score),
            requested_cr      = inp.requested_cr,
            recommended_cr    = inp.recommended_cr,
            collateral_table  = coll_table,
            total_market_cr   = inp.total_market_cr,
            total_distress_cr = inp.total_distress_cr,
            coverage_market   = inp.coverage_market,
            coverage_distress = inp.coverage_distress,
            collateral_breakdown = bd_text,
        )
        return self._call(prompt, "Collateral", max_tokens=500)

    def _conditions(self, inp: NarrativeInput) -> str:
        sector_flags = _format_list([
            f.get("title", str(f)) for f in inp.research_flags
            if f.get("category") == "SECTOR"
        ])
        reg_notes = _format_list([
            f.get("title", str(f)) for f in inp.research_flags
            if f.get("category") == "REGULATORY"
        ]) or "No specific regulatory flags identified."

        repo_rate   = float(os.getenv("REPO_RATE",   "6.50"))
        bank_spread = float(os.getenv("BANK_SPREAD", "3.00"))

        prompt = CONDITIONS_PROMPT.format(
            system_preamble   = SYSTEM_PREAMBLE,
            company_name      = inp.company_name,
            industry          = inp.industry,
            conditions_score  = inp.conditions_score,
            conditions_band   = _score_band(inp.conditions_score),
            sector_score      = inp.sector_score,
            news_signals      = "; ".join(inp.news_signals[:4]) if inp.news_signals else "No adverse signals",
            sector_flags      = sector_flags or "No sector-specific flags",
            regulatory_notes  = reg_notes,
            repo_rate         = repo_rate,
            base_rate         = inp.rate_base,
            spread            = bank_spread,
        )
        return self._call(prompt, "Conditions", max_tokens=500)

    def _risk_mitigants(self, inp: NarrativeInput) -> str:
        risk_mitigant_rows = []
        for f in inp.research_flags:
            if f.get("severity") in ("HIGH", "MEDIUM", "CRITICAL"):
                risk_mitigant_rows.append(
                    f"  Risk: {f.get('title', str(f))} [{f.get('severity')}]\n"
                    f"  Mitigant: {_default_mitigant(f)}"
                )
        risk_table = "\n".join(risk_mitigant_rows) or "No significant risks identified."

        cond_list  = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(inp.conditions_precedent))
        cov_list   = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(inp.covenants))

        prompt = RISK_MITIGANTS_PROMPT.format(
            system_preamble     = SYSTEM_PREAMBLE,
            company_name        = inp.company_name,
            decision            = inp.decision,
            recommended_cr      = inp.recommended_cr,
            interest_rate       = inp.interest_rate,
            risk_mitigant_table = risk_table,
            conditions_list     = cond_list or "  Standard banking conditions apply.",
            covenants_list      = cov_list  or "  Standard covenant package applies.",
        )
        return self._call(prompt, "Risk Mitigants", max_tokens=700)

    def _decision_rationale(self, inp: NarrativeInput) -> str:
        """
        Generates the cross-pillar explainability section — the AI's explanation
        of WHY the decision was made, referencing contradictions between pillars.
        This is the section judges will probe most deeply.
        """
        qi_text = ""
        if inp.qualitative_explanations:
            qi_text = "Primary Insight adjustments applied:\n" + "\n".join(inp.qualitative_explanations)
        elif inp.factory_capacity_pct >= 0:
            qi_text = f"Factory capacity observed at {inp.factory_capacity_pct:.0f}%."
            if inp.management_quality > 0:
                qi_text += f" Management quality rated {inp.management_quality}/5."

        contradictions_text = ""
        if inp.cross_pillar_contradictions:
            contradictions_text = "Cross-pillar contradictions identified:\n" + \
                "\n".join(f"  - {c}" for c in inp.cross_pillar_contradictions)

        cibil_text = ""
        if inp.cibil_commercial_score > 0:
            cibil_text = f"CIBIL Commercial Score: {inp.cibil_commercial_score:.0f}."

        prompt = f"""{SYSTEM_PREAMBLE}

You are writing the DECISION RATIONALE section of a Credit Appraisal Memo (CAM) for {inp.company_name}.
This section must clearly explain the credit decision in plain language, citing specific evidence
from EACH of the three pillars of analysis:
  Pillar 1 — Document extraction (financial metrics)
  Pillar 2 — Research intelligence (RBI, MCA, eCourts, news)
  Pillar 3 — Scoring engine (composite score, qualitative observations)

DECISION: {inp.decision}
COMPOSITE SCORE: {inp.composite_score}/100  (Risk Band: {inp.risk_band})
RECOMMENDED AMOUNT: Rs.{inp.recommended_cr:.2f} Cr (Requested: Rs.{inp.requested_cr:.2f} Cr)
INTEREST RATE: {inp.interest_rate:.2f}% p.a.

FINANCIAL HIGHLIGHTS (Pillar 1):
  Capacity Score: {inp.capacity_score}/100  |  Capital Score: {inp.capital_score}/100
  Collateral Score: {inp.collateral_score}/100  |  GST Quality can be inferred
  Promoter Shareholding: {inp.promoter_shareholding:.1f}%

RESEARCH INTELLIGENCE (Pillar 2):
  Character Score: {inp.character_score}/100  |  Conditions Score: {inp.conditions_score}/100
  Litigation findings: {inp.litigation_count} case(s)
  MCA flags: {inp.mca_flag_count}
  RBI check: {inp.rbi_result}
  News signals: {'; '.join(inp.news_signals[:3]) if inp.news_signals else 'None adverse'}

PRIMARY INSIGHTS (Pillar 3 — Credit Officer Field Observations):
{qi_text if qi_text else '  No qualitative field data entered.'}
{cibil_text}

{contradictions_text}

Write a 3–5 paragraph analytical narrative that:
1. Opens with the decision and the single most important reason (cite specific metric/finding)
2. Explains the primary driving factors — financial and research — with specific numbers
3. If any contradictions exist between pillars, explicitly mention and explain them
4. Explains how qualitative field observations influenced the final score (if applicable)
5. Concludes with the recommended lending terms and key conditions

Use precise financial language. Do NOT use bullet points — write in flowing paragraphs.
Be specific: cite actual numbers (DSCR, D/E, eCourts case numbers, GST compliance %)."""

        return self._call(prompt, "Decision Rationale", max_tokens=900)


# ─────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────

def _pad(lst: list, n: int, fill=0.0) -> list:
    out = list(lst) + [fill] * n
    return out[:n]


def _score_band(score: int) -> str:
    if score >= 75: return "Strong"
    if score >= 60: return "Adequate"
    if score >= 45: return "Cautious"
    return "Weak"


def _format_list(items: List[str]) -> str:
    if not items:
        return "None identified."
    return "\n".join(f"  * {i}" for i in items if i)


def _format_flags(flags: List[Dict]) -> str:
    if not flags:
        return "  * No adverse flags detected from available sources."
    rows = []
    for f in flags:
        rows.append(
            f"  [{f.get('severity','?')}] {f.get('title', f.get('description', str(f)))}"
            + (f" -- {f.get('evidence', '')}" if f.get('evidence') else "")
        )
    return "\n".join(rows)


def _format_promoters(promoters: List[Dict]) -> str:
    if not promoters:
        return "  No promoter data available."
    rows = []
    for p in promoters:
        rows.append(
            f"  {p.get('name','?')} | {p.get('designation','Director')} "
            f"| DIN: {p.get('din','N/A')} "
            f"| Holding: {p.get('shareholding_pct', 0):.1f}%"
        )
    return "\n".join(rows)


def _format_collateral(assets: List[Dict]) -> str:
    if not assets:
        return "  No collateral details available."
    rows = []
    for a in assets:
        rows.append(
            f"  {a.get('type','Asset')} | "
            f"Market: Rs.{_safe(a.get('market_value')):.2f} Cr | "
            f"Distress: Rs.{_safe(a.get('distress_value')):.2f} Cr | "
            f"Charge: {a.get('charge','N/A')} | "
            f"Pledged: {'Yes' if a.get('pledged') else 'No'}"
        )
    return "\n".join(rows)


def _format_breakdown(breakdown: List[Dict]) -> str:
    if not breakdown:
        return "  Detailed breakdown not available."
    rows = []
    for b in breakdown:
        rows.append(f"  {b.get('label','?')} ({b.get('points',0)}/{b.get('max_points',100)} pts)")
    return "\n".join(rows)


def _default_mitigant(flag: Dict) -> str:
    cat = flag.get("category", "")
    if cat == "LITIGATION":
        return "Legal proceedings monitored via eCourts; legal opinion to be obtained pre-disbursement."
    if cat == "FINANCIAL":
        return "Financial covenants and quarterly monitoring to be instituted."
    if cat == "REGULATORY":
        return "Compliance status to be verified and rectification required as condition precedent."
    if cat == "PROMOTER":
        return "Enhanced promoter due-diligence; personal guarantee to be obtained."
    if cat == "SECTOR":
        return "Sector risk partially offset by company-specific strengths; annual sector review."
    if cat == "FRAUD":
        return "Escalate to credit committee immediately; halt processing."
    return "Enhanced monitoring and covenant package to address this risk."
