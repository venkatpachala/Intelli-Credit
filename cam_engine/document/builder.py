"""
cam_engine/document/builder.py
================================
CAMBuilder — assembles the full Credit Appraisal Memo as a .docx file.

Each section has its own private method.
The build() method calls them in CAM document order.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Cm

from .styles import (
    Colors, Fonts, FONT_SIZES, PAGE_MARGIN, TABLE_WIDTH,
    band_color, band_light_color, score_color,
)


def _safe(v, fallback=0.0):
    if v is None: return fallback
    if isinstance(v, dict): return float(v.get("value", fallback) or fallback)
    try:    return float(v)
    except: return fallback


class CAMBuilder:
    """
    Builds the Credit Appraisal Memorandum as a python-docx Document.

    Usage:
        builder = CAMBuilder()
        doc     = builder.build(cam_data)
        doc.save("CAM_CASE123.docx")
    """

    def __init__(self):
        self.doc = Document()
        self._setup_page()
        self._section_count = 0

    # ─────────────────────────────────────────────────────────
    # Page setup
    # ─────────────────────────────────────────────────────────

    def _setup_page(self):
        section = self.doc.sections[0]
        section.top_margin    = PAGE_MARGIN
        section.bottom_margin = PAGE_MARGIN
        section.left_margin   = PAGE_MARGIN
        section.right_margin  = PAGE_MARGIN

        # Default paragraph style
        style = self.doc.styles["Normal"]
        style.font.name = Fonts.MAIN
        style.font.size = Pt(FONT_SIZES["body"])

    # ─────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────

    def build(self, data: Dict) -> Document:
        """
        data = the full cam_data dict produced by cam_engine/main.py
        """
        self._add_cover_page(data)
        self._add_section1_executive_summary(data)
        self._add_section2_company_profile(data)
        self._add_section3_character(data)
        self._add_section4_capacity(data)
        self._add_section5_capital(data)
        self._add_section6_collateral(data)
        self._add_section7_conditions(data)
        self._add_section8_risk_matrix(data)
        self._add_section9_recommendation(data)
        self._add_footer(data)
        return self.doc

    # ─────────────────────────────────────────────────────────
    # COVER PAGE
    # ─────────────────────────────────────────────────────────

    def _add_cover_page(self, d: Dict):
        # Bank name
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("INTELLI-CREDIT BANK")
        run.bold      = True
        run.font.size = Pt(FONT_SIZES["bank_name"])
        run.font.color.rgb = Colors.PRIMARY

        # Subtitle
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("CREDIT APPRAISAL MEMORANDUM")
        run.font.size = Pt(FONT_SIZES["cam_title"])
        run.font.color.rgb = Colors.SECONDARY
        run.bold = True

        self._add_divider(Colors.PRIMARY)
        self.doc.add_paragraph()

        # Decision box
        risk_band    = d.get("risk_band", "AMBER")
        decision     = d.get("decision", "CONDITIONAL APPROVAL")
        rec_amount   = _safe(d.get("recommended_amount_inr")) / 1e7   # to crores
        req_amount   = _safe(d.get("requested_amount_inr"))  / 1e7
        interest_rate= _safe(d.get("interest_rate"))
        comp_score   = int(_safe(d.get("composite_score")))

        self._add_decision_box(decision, rec_amount, req_amount, interest_rate, comp_score, risk_band)

        self.doc.add_paragraph()
        self._add_divider(Colors.SEPARATOR)
        self.doc.add_paragraph()

        # Cover metadata table
        case_ref = f"CAM/{d.get('case_id','?')}/{datetime.now().strftime('%Y%m')}"
        meta = [
            ("Company Name",    d.get("company_name", "—")),
            ("CIN",             d.get("cin", "—")),
            ("Industry / Sector",d.get("industry", "—")),
            ("Loan Type",       d.get("loan_type", "—")),
            ("Report Date",     datetime.now().strftime("%d %B %Y")),
            ("Prepared By",     "Intelli-Credit AI Engine v3.0"),
            ("CAM Reference",   case_ref),
        ]
        self._add_meta_table(meta)
        self.doc.add_page_break()

    def _add_decision_box(self, decision: str, rec_cr: float, req_cr: float,
                           rate: float, score: int, band: str):
        """Prominent colored box showing the final credit decision."""
        tbl = self.doc.add_table(rows=1, cols=1)
        tbl.style = "Table Grid"
        cell = tbl.rows[0].cells[0]

        # Cell background color
        bg = band_light_color(band)
        self._set_cell_bg(cell, bg)

        cell_p = cell.paragraphs[0]
        cell_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Decision text
        dr = cell_p.add_run(f"DECISION: {decision}")
        dr.bold = True
        dr.font.size = Pt(14)
        dr.font.color.rgb = band_color(band)

        cell_p.add_run("\n")

        # Amount and rate on same line
        ar_run = cell_p.add_run(
            f"Recommended: ₹{rec_cr:.2f} Cr  |  Rate: {rate:.2f}% p.a.  |  "
            f"Score: {score}/100  |  Risk Band: {band}"
        )
        ar_run.font.size = Pt(11)
        ar_run.font.color.rgb = Colors.SECONDARY

        if rec_cr < req_cr and req_cr > 0:
            cell_p.add_run("\n")
            note = cell_p.add_run(f"(Requested: ₹{req_cr:.2f} Cr — limit moderated)")
            note.font.size = Pt(9)
            note.font.color.rgb = Colors.SCORE_AMBER
            note.italic = True

        cell.paragraphs[0].paragraph_format.space_before = Pt(8)
        cell.paragraphs[0].paragraph_format.space_after  = Pt(8)

    # ─────────────────────────────────────────────────────────
    # SECTION 1 — EXECUTIVE SUMMARY
    # ─────────────────────────────────────────────────────────

    def _add_section1_executive_summary(self, d: Dict):
        self._add_section_heading("1", "EXECUTIVE SUMMARY & RECOMMENDATION", d.get("risk_band","AMBER"))
        self._add_score_ribbon([
            (d.get("composite_score", 0), "Composite Score", d.get("risk_band","AMBER")),
        ])
        self._add_narrative(d.get("narratives", {}).get("executive_summary", ""))
        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 2 — COMPANY PROFILE
    # ─────────────────────────────────────────────────────────

    def _add_section2_company_profile(self, d: Dict):
        self._add_section_heading("2", "COMPANY PROFILE")
        profile = d.get("company_profile", {})
        loan    = d.get("loan_details", {})
        promoters = d.get("promoters", [])

        rows = [
            ("Legal Name",            d.get("company_name")),
            ("Corporate Identity No.",d.get("cin")),
            ("GSTIN",                 d.get("gstin")),
            ("Industry / Sector",     d.get("industry") or profile.get("sector")),
            ("Registered Address",    profile.get("registered_address") or profile.get("address")),
            ("Incorporation Year",    profile.get("incorporation_year")),
            ("Promoter Shareholding", f"{profile.get('promoter_stake_pct', 0):.1f}%"),
            ("Loan Amount Requested", f"₹{_safe(loan.get('amount_inr'))/1e7:.2f} Crore"),
            ("Loan Type",             loan.get("type") or d.get("loan_type")),
            ("Tenor",                 f"{loan.get('tenor_months', 0)} months"),
            ("Purpose",               loan.get("purpose")),
        ]
        self._add_kv_table(rows)
        self.doc.add_paragraph()

        # Promoters sub-table
        if promoters:
            self._add_sub_heading("Promoters / Directors")
            self._add_promoter_table(promoters)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 3 — CHARACTER
    # ─────────────────────────────────────────────────────────

    def _add_section3_character(self, d: Dict):
        scores = d.get("dimension_scores", {})
        char_score = _dim_score(scores, "Character")
        self._add_section_heading("3", "CHARACTER (Five Cs — C1)")
        self._add_score_ribbon([(char_score, "Character Score", _score_band_str(char_score))])
        self._add_narrative(d.get("narratives", {}).get("character", ""))
        self.doc.add_paragraph()

        # Research flags table (character-related)
        char_flags = [f for f in d.get("research_flags", [])
                      if f.get("category") in ("PROMOTER","FRAUD","LITIGATION")]
        if char_flags:
            self._add_sub_heading("Research Findings — Character Flags")
            self._add_flags_table(char_flags)

        # Score breakdown
        bd = _dim_breakdown(scores, "Character")
        if bd:
            self._add_sub_heading("Score Breakdown")
            self._add_score_breakdown_table(bd)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 4 — CAPACITY
    # ─────────────────────────────────────────────────────────

    def _add_section4_capacity(self, d: Dict):
        scores     = d.get("dimension_scores", {})
        cap_score  = _dim_score(scores, "Capacity")
        extraction = d.get("extraction", {})

        self._add_section_heading("4", "CAPACITY (Five Cs — C2)")
        self._add_score_ribbon([(cap_score, "Capacity Score", _score_band_str(cap_score))])

        # 3-year financial table
        self._add_sub_heading("3-Year Financial Performance")
        self._add_financial_trend_table(extraction)

        # Key ratios ribbon
        cm   = extraction.get("credit_metrics", {})
        dscr = _safe(cm.get("dscr"))
        icr  = self._latest_icr(cm)
        self._add_sub_heading("Key Repayment Ratios")
        self._add_ratio_table([
            ("DSCR",              dscr,  "x", 1.25, 2.0,   "RBI minimum: 1.25x"),
            ("Interest Coverage", icr,   "x", 2.0,  4.0,   "Adequate: ≥2x"),
        ])

        self._add_narrative(d.get("narratives", {}).get("capacity", ""))

        bd = _dim_breakdown(scores, "Capacity")
        if bd:
            self._add_sub_heading("Score Breakdown")
            self._add_score_breakdown_table(bd)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 5 — CAPITAL
    # ─────────────────────────────────────────────────────────

    def _add_section5_capital(self, d: Dict):
        scores     = d.get("dimension_scores", {})
        cap_score  = _dim_score(scores, "Capital")
        extraction = d.get("extraction", {})
        bs         = extraction.get("balance_sheet", {})

        self._add_section_heading("5", "CAPITAL (Five Cs — C3)")
        self._add_score_ribbon([(cap_score, "Capital Score", _score_band_str(cap_score))])

        cm    = extraction.get("credit_metrics", {})
        de_raw= cm.get("debt_equity", 0)
        de    = _safe(de_raw) if not isinstance(de_raw, dict) else _last_dict_val(de_raw)
        nw    = _safe(bs.get("net_worth"))
        td_raw= bs.get("total_debt", {})
        td    = _safe(td_raw) if not isinstance(td_raw, dict) else (
            _safe(td_raw.get("term_loan_outstanding", 0)) + _safe(td_raw.get("total_rated_facilities", 0))
        )
        ta    = _safe(bs.get("total_assets"))
        tnw   = _safe(bs.get("tangible_net_worth")) or nw
        gear  = _safe(list(bs.get("gearing_ratio", {}).values())[-1]) if bs.get("gearing_ratio") else (td / ta if ta else 0.0)

        self._add_sub_heading("Balance Sheet Highlights")
        self._add_ratio_table([
            ("Net Worth",        nw,   "₹ Cr", 100,  500,  "Higher = stronger capital base"),
            ("Total Debt",       td,   "₹ Cr", None, None, "Lower = less leveraged"),
            ("Debt/Equity",      de,   "x",    None, 1.5,  "Lower = less leveraged (≤1x preferred)"),
            ("Tangible NW",      tnw,  "₹ Cr", 100,  500,  "Excludes goodwill/intangibles"),
            ("Gearing Ratio",    gear, "x",    None, 0.5,  "Debt as % of total assets"),
        ])

        self._add_narrative(d.get("narratives", {}).get("capital", ""))

        bd = _dim_breakdown(scores, "Capital")
        if bd:
            self._add_sub_heading("Score Breakdown")
            self._add_score_breakdown_table(bd)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 6 — COLLATERAL
    # ─────────────────────────────────────────────────────────

    def _add_section6_collateral(self, d: Dict):
        scores     = d.get("dimension_scores", {})
        col_score  = _dim_score(scores, "Collateral")
        extraction = d.get("extraction", {})
        assets     = extraction.get("collateral_data", [])

        self._add_section_heading("6", "COLLATERAL (Five Cs — C4)")
        self._add_score_ribbon([(col_score, "Collateral Score", _score_band_str(col_score))])

        if assets:
            self._add_sub_heading("Collateral Assets")
            self._add_collateral_table(assets)

        self._add_narrative(d.get("narratives", {}).get("collateral", ""))

        bd = _dim_breakdown(scores, "Collateral")
        if bd:
            self._add_sub_heading("Score Breakdown")
            self._add_score_breakdown_table(bd)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 7 — CONDITIONS
    # ─────────────────────────────────────────────────────────

    def _add_section7_conditions(self, d: Dict):
        scores    = d.get("dimension_scores", {})
        con_score = _dim_score(scores, "Conditions")
        self._add_section_heading("7", "CONDITIONS (Five Cs — C5)")
        self._add_score_ribbon([(con_score, "Conditions Score", _score_band_str(con_score))])
        self._add_narrative(d.get("narratives", {}).get("conditions", ""))
        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 8 — RISK MATRIX
    # ─────────────────────────────────────────────────────────

    def _add_section8_risk_matrix(self, d: Dict):
        self._add_section_heading("8", "RISK MATRIX")

        all_flags = d.get("research_flags", [])
        ext_flags = d.get("extraction_flags", [])  # from extractor risk_flags

        combined = []
        for f in all_flags:
            combined.append({
                "severity": f.get("severity", "MEDIUM"),
                "title":    f.get("title", f.get("description", str(f))),
                "source":   f.get("source", "Research Agent"),
                "mitigant": _default_mitigant_str(f),
            })
        for f in ext_flags:
            if isinstance(f, dict):
                combined.append({
                    "severity": f.get("severity", "MEDIUM"),
                    "title":    f.get("flag", str(f)),
                    "source":   "Document Analysis",
                    "mitigant": "Enhanced monitoring and covenant package.",
                })

        if combined:
            self._add_risk_matrix_table(combined)
        else:
            self._add_narrative("No significant risk flags identified across all sources.")

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # SECTION 9 — RECOMMENDATION
    # ─────────────────────────────────────────────────────────

    def _add_section9_recommendation(self, d: Dict):
        self._add_section_heading("9", "RECOMMENDATION & CONDITIONS PRECEDENT")

        # 9.1 — Amount derivation
        self._add_sub_heading("9.1 — Loan Amount Derivation")
        self._add_amount_derivation_table(d)

        self.doc.add_paragraph()

        # 9.2 — Rate derivation (the explainability showpiece)
        self._add_sub_heading("9.2 — Interest Rate Derivation")
        self._add_rate_derivation_table(d)

        self.doc.add_paragraph()

        # 9.3 — Conditions precedent
        self._add_sub_heading("9.3 — Conditions Precedent (Pre-Disbursement)")
        for cond in d.get("conditions_precedent", []):
            self._add_bullet(cond)

        self.doc.add_paragraph()

        # 9.4 — Covenants
        self._add_sub_heading("9.4 — Ongoing Covenants")
        for cov in d.get("covenants", []):
            self._add_bullet(cov)

        self.doc.add_paragraph()

        # Narrative conclusion
        self._add_narrative(d.get("narratives", {}).get("risk_mitigants", ""))
        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # Table builders
    # ─────────────────────────────────────────────────────────

    def _add_financial_trend_table(self, extraction: Dict):
        income  = extraction.get("income_statement", {})
        periods = income.get("periods", ["FY1", "FY2", "FY3"])[:3]

        def get_vals(field):
            raw = income.get(field, {})
            if isinstance(raw, dict):
                vals = []
                for k, v in raw.items():
                    if "2025_unaudited" in str(k).lower():
                        label = "9M FY25*"
                    else:
                        label = k
                    vals.append((label, _safe(v)))
                return vals
            return []

        rev_vals    = get_vals("total_revenue")
        ebitda_vals = get_vals("ebitda")
        pat_vals    = get_vals("pat")

        if not rev_vals:
            self._add_narrative("Financial trend data not available in extracted documents.")
            return

        headers  = ["Metric (₹ Crore)"] + [r[0] for r in rev_vals]
        rev_row  = ["Total Revenue"]    + [f"{v:.0f}" for _, v in rev_vals]
        ebitda_r = ["EBITDA"]           + ([f"{v:.0f}" for _, v in ebitda_vals] if ebitda_vals else ["—"]*len(rev_vals))
        pat_row  = ["PAT"]              + ([f"{v:.0f}" for _, v in pat_vals]    if pat_vals    else ["—"]*len(rev_vals))

        # EBITDA margins
        margins  = ["EBITDA Margin %"]
        for (_, r), (_, e) in zip(rev_vals, ebitda_vals if ebitda_vals else []):
            margins.append(f"{e/r*100:.1f}%" if r else "—")

        all_rows = [rev_row, ebitda_r, pat_row, margins]
        self._add_plain_table(headers, all_rows)

    def _add_ratio_table(self, ratios: List):
        """
        ratios = list of tuples:
          (label, value, unit, warn_threshold, good_threshold, note)
        """
        tbl = self.doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for i, h in enumerate(["Metric", "Value", "Status", "Note"]):
            self._style_header_cell(hdr[i], h)

        for label, value, unit, warn_t, good_t, note in ratios:
            if value is None or value == 0:
                continue
            row   = tbl.add_row().cells
            flag  = "✓" if (good_t and value >= good_t) else ("!" if (warn_t and value < warn_t) else "~")
            color = Colors.SCORE_GREEN if flag == "✓" else (Colors.SCORE_RED if flag == "!" else Colors.SCORE_AMBER)

            row[0].text = str(label)
            if unit == "₹ Cr":
                row[1].text = f"₹{value:.2f} Cr"
            elif unit == "x":
                row[1].text = f"{value:.2f}x"
            elif unit == "%":
                row[1].text = f"{value:.1f}%"
            else:
                row[2].text = f"{value:.2f}"
            row[2].text = flag
            row[3].text = note or ""
            self._color_cell_text(row[2], color)

        self.doc.add_paragraph()

    def _add_collateral_table(self, assets: List[Dict]):
        headers = ["Asset Type", "Market Value", "Distress Value", "Charge Rank", "Pledged?"]
        rows = []
        for a in assets:
            rows.append([
                a.get("type", "Asset"),
                f"₹{_safe(a.get('market_value')):.2f} Cr",
                f"₹{_safe(a.get('distress_value')):.2f} Cr",
                a.get("charge", "N/A"),
                "Yes" if a.get("pledged") else "No",
            ])
        self._add_plain_table(headers, rows)

    def _add_promoter_table(self, promoters: List[Dict]):
        headers = ["Name", "Designation", "DIN", "Holding %"]
        rows = []
        for p in promoters:
            rows.append([
                p.get("name", "?"),
                p.get("designation", "Director"),
                p.get("din", "N/A"),
                f"{p.get('shareholding_pct', 0):.1f}%",
            ])
        self._add_plain_table(headers, rows)

    def _add_flags_table(self, flags: List[Dict]):
        headers = ["Severity", "Finding", "Source", "Evidence"]
        rows = []
        for f in flags:
            rows.append([
                f.get("severity", "?"),
                f.get("title", f.get("description", str(f)))[:120],
                f.get("source", "?"),
                (f.get("evidence", "") or "")[:100],
            ])
        self._add_plain_table(headers, rows, severity_col=0)

    def _add_risk_matrix_table(self, risks: List[Dict]):
        headers = ["Severity", "Risk", "Source", "Mitigant"]
        rows = []
        for r in risks:
            rows.append([
                r.get("severity", "MEDIUM"),
                r.get("title", str(r))[:120],
                r.get("source", "?"),
                r.get("mitigant", "")[:120],
            ])
        self._add_plain_table(headers, rows, severity_col=0)

    def _add_score_breakdown_table(self, breakdown: List[Dict]):
        headers = ["Sub-dimension", "Points Awarded", "Max Points", "Benchmark"]
        rows = []
        for b in breakdown:
            rows.append([
                b.get("label", "?")[:80],
                str(b.get("points", 0)),
                str(b.get("max_points", 100)),
                b.get("benchmark", "")[:80],
            ])
        self._add_plain_table(headers, rows)

    def _add_amount_derivation_table(self, d: Dict):
        """The explainability chain for the recommended amount."""
        adj_chain = d.get("amount_adjustments", [])
        req       = _safe(d.get("requested_amount_inr")) / 1e7
        wc_gap    = _safe(d.get("wc_gap_inr")) / 1e7
        base      = _safe(d.get("base_amount_inr")) / 1e7
        final     = _safe(d.get("recommended_amount_inr")) / 1e7

        tbl = self.doc.add_table(rows=1, cols=3)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for i, h in enumerate(["Step", "Amount (₹ Cr)", "Rationale"]):
            self._style_header_cell(hdr[i], h)

        # Starting row
        r = tbl.add_row().cells
        r[0].text = "Requested Amount"
        r[1].text = f"₹{req:.2f} Cr"
        r[2].text = "As submitted by applicant"

        if wc_gap > 0 and wc_gap < req:
            r = tbl.add_row().cells
            r[0].text = "Working Capital Gap (ceiling)"
            r[1].text = f"₹{wc_gap:.2f} Cr"
            r[2].text = "Min(requested, WC gap) = base amount"
            r = tbl.add_row().cells
            r[0].text = "→ Base Amount"
            r[1].text = f"₹{base:.2f} Cr"
            r[2].text = "Working capital gap is the lending ceiling"

        for adj in adj_chain:
            r = tbl.add_row().cells
            r[0].text = f"× {adj.get('factor', 1.0):.2f}"
            r[1].text = f"₹{adj.get('after', 0)/1e7:.2f} Cr"
            r[2].text = adj.get("reason", "")

        r = tbl.add_row().cells
        r[0].text = "RECOMMENDED LIMIT"
        r[1].text = f"₹{final:.2f} Cr"
        r[2].text = "Rounded to nearest ₹25L"
        for cell in r:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True

        self.doc.add_paragraph()

    def _add_rate_derivation_table(self, d: Dict):
        """The cornerstone explainability table — every basis point justified."""
        premiums  = d.get("rate_premiums", [])
        base_rate = _safe(d.get("base_rate")) or 9.50
        final     = _safe(d.get("interest_rate"))

        tbl = self.doc.add_table(rows=1, cols=3)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for i, h in enumerate(["Component", "Rate", "Rationale"]):
            self._style_header_cell(hdr[i], h)

        # Base rate
        r = tbl.add_row().cells
        r[0].text = "Base Rate (Repo + Spread)"
        r[1].text = f"{base_rate:.2f}%"
        r[2].text = f"RBI Repo Rate + Bank MCLR Spread"

        visible_premiums = [p for p in premiums if p.get("bps", 0) > 0]
        for p in visible_premiums:
            r = tbl.add_row().cells
            r[0].text = f"Risk Premium ({p.get('source','')})"
            r[1].text = f"+{p.get('bps',0)/100:.2f}%"
            r[2].text = p.get("reason", "")

        # Total
        r = tbl.add_row().cells
        r[0].text = "FINAL INTEREST RATE"
        r[1].text = f"{final:.2f}% p.a."
        r[2].text = d.get("rate_band", "")
        for cell in r:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True
                    run.font.color.rgb = Colors.PRIMARY

        self.doc.add_paragraph()

    def _add_kv_table(self, rows: List):
        """Simple two-column key-value table."""
        tbl = self.doc.add_table(rows=0, cols=2)
        tbl.style = "Table Grid"
        tbl.columns[0].width = Inches(2.2)
        tbl.columns[1].width = Inches(4.1)

        for i, (k, v) in enumerate(rows):
            if v is None: continue
            r = tbl.add_row().cells
            r[0].text = str(k)
            r[1].text = str(v)
            # Alternating row background
            if i % 2 == 0:
                self._set_cell_bg(r[0], Colors.TABLE_ALT)
                self._set_cell_bg(r[1], Colors.TABLE_ALT)
            for cell in r:
                for para in cell.paragraphs:
                    para.paragraph_format.space_before = Pt(3)
                    para.paragraph_format.space_after  = Pt(3)

        self.doc.add_paragraph()

    def _add_meta_table(self, rows: List):
        self._add_kv_table(rows)

    def _add_plain_table(self, headers: List[str], rows: List[List], severity_col: int = -1):
        """Generic styled table with navy header row and alternating rows."""
        tbl = self.doc.add_table(rows=1, cols=len(headers))
        tbl.style = "Table Grid"

        hdr_cells = tbl.rows[0].cells
        for i, h in enumerate(headers):
            self._style_header_cell(hdr_cells[i], h)

        for ri, row in enumerate(rows):
            r = tbl.add_row().cells
            bg = Colors.TABLE_ALT if ri % 2 == 0 else Colors.WHITE
            for ci, val in enumerate(row):
                r[ci].text = str(val) if val is not None else "—"
                if bg != Colors.WHITE:
                    self._set_cell_bg(r[ci], bg)
                # Color severity cells
                if ci == severity_col:
                    sev_map = {
                        "CRITICAL": Colors.RED,
                        "HIGH":     Colors.SCORE_AMBER,
                        "MEDIUM":   RGBColor(0x1A, 0x72, 0xBD),
                        "LOW":      Colors.SECONDARY,
                    }
                    col = sev_map.get(str(val).upper(), Colors.SECONDARY)
                    self._color_cell_text(r[ci], col, bold=True)
                r[ci].paragraphs[0].paragraph_format.space_before = Pt(3)
                r[ci].paragraphs[0].paragraph_format.space_after  = Pt(3)

        self.doc.add_paragraph()

    # ─────────────────────────────────────────────────────────
    # Structural helpers
    # ─────────────────────────────────────────────────────────

    def _add_section_heading(self, number: str, title: str, band: str = ""):
        self._add_divider(Colors.PRIMARY)
        p = self.doc.add_paragraph()
        run = p.add_run(f"SECTION {number} — {title}")
        run.bold = True
        run.font.size = Pt(FONT_SIZES["h1"])
        run.font.color.rgb = Colors.PRIMARY
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after  = Pt(4)

    def _add_sub_heading(self, title: str):
        p = self.doc.add_paragraph()
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(FONT_SIZES["h2"])
        run.font.color.rgb = Colors.SECONDARY
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after  = Pt(2)

    def _add_narrative(self, text: str):
        if not text:
            return
        para = self.doc.add_paragraph()
        run  = para.add_run(text)
        run.font.size = Pt(FONT_SIZES["body"])
        para.paragraph_format.space_before = Pt(4)
        para.paragraph_format.space_after  = Pt(6)
        para.paragraph_format.line_spacing = Pt(14)

    def _add_bullet(self, text: str):
        p = self.doc.add_paragraph(style="List Bullet")
        run = p.add_run(text)
        run.font.size = Pt(FONT_SIZES["body"])

    def _add_divider(self, color: RGBColor = None):
        p   = self.doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pBdr= OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "8")
        bottom.set(qn("w:space"), "1")
        col = color or Colors.PRIMARY
        bottom.set(qn("w:color"), f"{col[0]:02X}{col[1]:02X}{col[2]:02X}")
        pBdr.append(bottom)
        pPr.append(pBdr)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(2)

    def _add_score_ribbon(self, scores: List):
        """Small inline score badge(s)."""
        p = self.doc.add_paragraph()
        for score_val, label, band in scores:
            sc = int(_safe(score_val))
            run = p.add_run(f" {label}: {sc}/100 [{band}] ")
            run.bold = True
            run.font.size = Pt(FONT_SIZES["small"])
            run.font.color.rgb = score_color(sc)
        p.paragraph_format.space_after = Pt(6)

    def _add_footer(self, data: Dict):
        section = self.doc.sections[0]
        footer  = section.footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(
            f"CONFIDENTIAL — {data.get('company_name','')} | "
            f"CAM Ref: CAM/{data.get('case_id','?')}/{datetime.now().strftime('%Y%m')} | "
            f"Generated: {datetime.now().strftime('%d %b %Y')} | " 
            "Intelli-Credit AI Engine v3.0"
        )
        run.font.size = Pt(7)
        run.font.color.rgb = Colors.SECONDARY

    # ─────────────────────────────────────────────────────────
    # Low-level XML cell styling
    # ─────────────────────────────────────────────────────────

    def _style_header_cell(self, cell, text: str):
        cell.text = text
        self._set_cell_bg(cell, Colors.TABLE_HDR)
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True
                run.font.color.rgb = Colors.WHITE
                run.font.size = Pt(FONT_SIZES["small"])
            para.paragraph_format.space_before = Pt(3)
            para.paragraph_format.space_after  = Pt(3)

    def _set_cell_bg(self, cell, color: RGBColor):
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement("w:shd")
        hex_color = f"{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        shd.set(qn("w:val"),   "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"),  hex_color)
        tcPr.append(shd)

    def _color_cell_text(self, cell, color: RGBColor, bold: bool = False):
        for para in cell.paragraphs:
            for run in para.runs:
                run.font.color.rgb = color
                if bold:
                    run.bold = True

    def _latest_icr(self, credit_metrics: Dict) -> float:
        """Extract latest ICR from potentially nested dict."""
        raw = credit_metrics.get("interest_coverage_ratio", 0)
        if isinstance(raw, dict):
            vals = [_safe(v) for v in raw.values() if _safe(v) > 0]
            return vals[-1] if vals else 0.0
        return _safe(raw)


# ─────────────────────────────────────────────────────────────
# Module-level utilities
# ─────────────────────────────────────────────────────────────

def _dim_score(scores_dict: Dict, name: str) -> int:
    """Find score for a named dimension."""
    if isinstance(scores_dict, list):
        for d in scores_dict:
            if isinstance(d, dict) and d.get("name") == name:
                return int(d.get("score", 50))
            if hasattr(d, "name") and d.name == name:
                return int(d.score)
    return 50


def _dim_breakdown(scores_dict: Any, name: str) -> List[Dict]:
    """Find breakdown list for a named dimension."""
    if isinstance(scores_dict, list):
        for d in scores_dict:
            if isinstance(d, dict) and d.get("name") == name:
                return d.get("breakdown", [])
            if hasattr(d, "name") and d.name == name:
                return [b.model_dump() for b in d.breakdown]
    return []


def _score_band_str(score: int) -> str:
    if score >= 70: return "GREEN"
    if score >= 50: return "AMBER"
    if score >= 30: return "RED"
    return "BLACK"


def _last_dict_val(d: Dict) -> float:
    if not d or not isinstance(d, dict):
        return 0.0
    vals = list(d.values())
    return _safe(vals[-1]) if vals else 0.0


def _default_mitigant_str(flag: Dict) -> str:
    cat = flag.get("category", "")
    if cat == "LITIGATION":     return "eCourts monitoring; legal opinion required."
    if cat == "FINANCIAL":      return "Financial covenants + quarterly reporting."
    if cat == "REGULATORY":     return "Compliance verification as condition precedent."
    if cat == "PROMOTER":       return "Enhanced DD; personal guarantee."
    if cat == "SECTOR":         return "Sector monitoring; annual review."
    if cat == "FRAUD":          return "Escalate to credit committee immediately."
    return "Enhanced monitoring."
