"""
cam_engine/narrative/prompts.py
==================================
All 7 Claude prompt templates.

Design principles:
  1. Claude gets NUMBERS and FLAGS — never makes decisions.
  2. Every prompt specifies exact word count and paragraph count.
  3. Indian banking terminology is explicitly required in each prompt.
  4. Prompts forbid adding information not supplied (prevents hallucination).
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────
# SYSTEM PREAMBLE (prepended to every section prompt)
# ─────────────────────────────────────────────────────────────

SYSTEM_PREAMBLE = """You are a Senior Credit Analyst at an Indian scheduled commercial bank 
with 15 years of experience writing Credit Appraisal Memos (CAMs) for the credit committee.
Your writing is precise, factual, and professional — the way a banker would write, not a 
consultant. You use Indian regulatory terminology correctly: DSCR, NPA, ROC, DIN, GSTIN, 
GSTR-3B, GSTR-2A, CIBIL CMR, IBC, RBI guidelines, Section 138 NI Act, eCourts, MCA21.

CRITICAL RULES:
- Do NOT change or invent numbers. Use ONLY the data provided.
- Do NOT soften CRITICAL or HIGH findings. State them factually.
- Do NOT use marketing language or fluff. Be direct.
- Do NOT add information not explicitly provided in the prompt.
- Write in third person about the company ("the company", "the borrower", not "you").
"""


# ─────────────────────────────────────────────────────────────
# SECTION 1 — EXECUTIVE SUMMARY
# ─────────────────────────────────────────────────────────────

EXECUTIVE_SUMMARY_PROMPT = """
{system_preamble}

=== TASK: EXECUTIVE SUMMARY ===

LOAN APPLICATION:
  Company:           {company_name}
  CIN:               {cin}
  Industry:          {industry}
  Loan Type:         {loan_type}
  Tenor:             {tenor_months} months
  Requested Amount:  ₹{requested_cr:.2f} Crore

CREDIT DECISION (already computed — do NOT change these):
  Decision:             {decision}
  Recommended Limit:    ₹{recommended_cr:.2f} Crore
  Recommended Rate:     {interest_rate:.2f}% p.a.
  Risk Band:            {risk_band}
  Composite Score:      {composite_score}/100

KEY APPROVAL DRIVERS (positive factors):
{positive_factors}

KEY RISK FACTORS:
{risk_factors}

AMOUNT MODERATION REASON (if recommended < requested):
{amount_reason}

RATE PREMIUM REASONS:
{rate_reasons}

CONDITIONS PRECEDENT (summary):
{conditions_summary}

Write EXACTLY 4 sentences:
Sentence 1: State the decision, recommended amount, rate, and risk band. Include all four data points.
Sentence 2: Name the 2 most important POSITIVE factors that are driving approval, with specific numbers.
Sentence 3: Name the 2 most important RISK FACTORS with the specific numbers that caused limit moderation or rate premium.
Sentence 4: State the 2 most important conditions precedent before disbursement.

Format: One cohesive paragraph of 4 sentences. No bullet points. No headers. 
Total: 120–180 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 2 — CHARACTER (Five Cs — C1)
# ─────────────────────────────────────────────────────────────

CHARACTER_PROMPT = """
{system_preamble}

=== TASK: CHARACTER SECTION (Five Cs — C1) ===
Character assesses promoter integrity, track record, and absence of adverse regulatory findings.

COMPANY: {company_name} | CIN: {cin} | Industry: {industry}
CHARACTER SCORE: {character_score}/100 ({character_band})

PROMOTERS:
{promoter_table}

REGULATORY CHECKS:
  RBI Wilful Defaulter Check:  {rbi_result}
  eCourts Litigation:          {litigation_summary}
  MCA Director History:        {mca_summary}
  News Signals:                {news_summary}

ALL CHARACTER-RELATED FLAGS:
{character_flags}

Write EXACTLY 3 paragraphs:

Paragraph 1 (70–90 words): Promoter background and track record. 
  Mention DIN status, years of business experience, primary industry background, 
  and any positive indicators available. Be factual.

Paragraph 2 (80–110 words): Adverse findings.
  Cite EVERY flag from the list above with specific evidence (case numbers, dates, 
  amounts where available). If no adverse flags, write: 
  "No adverse findings were detected across RBI wilful defaulter database, eCourts 
  litigation records, MCA21 director history, or news surveillance."
  Do NOT minimise or soften HIGH/CRITICAL findings.

Paragraph 3 (50–70 words): Overall character assessment.
  Conclude with a clear verdict — positive, cautious, or negative — backed by evidence.
  Use the character score to calibrate: 
  ≥80 = positive, 60–79 = cautious, <60 = negative. Be definitive.

Total: 200–270 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 3 — CAPACITY (Five Cs — C2)
# ─────────────────────────────────────────────────────────────

CAPACITY_PROMPT = """
{system_preamble}

=== TASK: CAPACITY SECTION (Five Cs — C2) ===
Capacity assesses the borrower's ability to repay from their own business earnings.

COMPANY: {company_name}
CAPACITY SCORE: {capacity_score}/100 ({capacity_band})

3-YEAR FINANCIAL PERFORMANCE:
  Period:           {period_1}       {period_2}       {period_3}
  Revenue (₹ Cr):   {rev_1:.2f}      {rev_2:.2f}      {rev_3:.2f}      [CAGR: {rev_cagr:.1f}%]
  EBITDA (₹ Cr):    {ebitda_1:.2f}   {ebitda_2:.2f}   {ebitda_3:.2f}
  PAT (₹ Cr):       {pat_1:.2f}      {pat_2:.2f}      {pat_3:.2f}
  CFO (₹ Cr):       {cfo_1:.2f}      {cfo_2:.2f}      {cfo_3:.2f}
  EBITDA Margin:    {ebitda_m_1:.1f}%  {ebitda_m_2:.1f}%  {ebitda_m_3:.1f}%

KEY REPAYMENT RATIOS:
  DSCR:              {dscr:.2f}x  (RBI minimum: 1.25x)
  Interest Coverage: {icr:.2f}x  (adequate: ≥2x)
  CFO/PAT:           {cfo_pat_ratio:.2f}x  (quality of earnings indicator)

CAPACITY SCORE BREAKDOWN:
{capacity_breakdown}

CONCERNS (if any): {capacity_concerns}

Write EXACTLY 3 paragraphs:

Paragraph 1 (90–110 words): Revenue and profitability trend.
  Discuss the 3-year revenue trajectory with the actual numbers. 
  Mention EBITDA margin improvement or compression and what it signals about  
  operating efficiency. Include PAT trend. Frame in context of the industry.

Paragraph 2 (80–100 words): Repayment capacity — DSCR and ICR.
  State the DSCR clearly, compare to the RBI norm of 1.25x, and interpret it.
  State the ICR and compare to the bank's benchmark of 2x.
  Be definitive: is the repayment capacity strong, adequate, or tight?

Paragraph 3 (60–80 words): Cash flow quality.
  Analyse CFO trend across 3 years. A positive and growing CFO confirms real 
  earnings quality vs accounting profit. If CFO/PAT > 1, state it positively.
  If CFO is negative in any year, flag it explicitly.

Total: 230–290 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 4 — CAPITAL (Five Cs — C3)
# ─────────────────────────────────────────────────────────────

CAPITAL_PROMPT = """
{system_preamble}

=== TASK: CAPITAL SECTION (Five Cs — C3) ===
Capital assesses the promoter's financial commitment — the 'skin in the game.'

COMPANY: {company_name}
CAPITAL SCORE: {capital_score}/100 ({capital_band})

BALANCE SHEET HIGHLIGHTS (latest year: {period_3}):
  Net Worth:              ₹{net_worth_cr:.2f} Crore
  Total Debt:             ₹{total_debt_cr:.2f} Crore
  Debt/Equity Ratio:      {de_ratio:.2f}x
  Tangible Net Worth:     ₹{tangible_nw_cr:.2f} Crore
  Total Assets:           ₹{total_assets_cr:.2f} Crore
  Gearing (Debt/Assets):  {gearing_ratio:.2f}x

PROMOTER COMMITMENT:
  Promoter Shareholding: {promoter_shareholding:.1f}%

TREND (if available):
  Net Worth {period_1}: ₹{nw_y1:.2f} Cr | {period_2}: ₹{nw_y2:.2f} Cr | {period_3}: ₹{nw_y3:.2f} Cr

CAPITAL SCORE BREAKDOWN:
{capital_breakdown}

Write EXACTLY 2 paragraphs:

Paragraph 1 (100–130 words): Balance sheet strength.
  Analyse net worth level and trend. Interpret D/E ratio — is it conservative, 
  moderate, or stretched? Is there intangible inflation (compare NW vs Tangible NW)?
  If D/E > 2x, flag it explicitly as elevated leverage. State gearing ratio.

Paragraph 2 (70–90 words): Promoter commitment.
  State promoter shareholding % and what it signals about confidence in the business.
  High promoter holding (>51%) is positive — skin in the game. 
  If promoter holding is declining or below 30%, flag it.
  Conclude with overall capital adequacy verdict.

Total: 170–220 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 5 — COLLATERAL (Five Cs — C4)
# ─────────────────────────────────────────────────────────────

COLLATERAL_PROMPT = """
{system_preamble}

=== TASK: COLLATERAL SECTION (Five Cs — C4) ===
Collateral is the bank's secondary recovery route if the borrower defaults.

COMPANY: {company_name}
COLLATERAL SCORE: {collateral_score}/100 ({collateral_band})

LOAN DETAILS:
  Requested Amount:  ₹{requested_cr:.2f} Crore
  Recommended Limit: ₹{recommended_cr:.2f} Crore

COLLATERAL ASSETS:
{collateral_table}

COVERAGE ANALYSIS:
  Total Market Value:    ₹{total_market_cr:.2f} Crore
  Total Distress Value:  ₹{total_distress_cr:.2f} Crore
  Coverage (Market):     {coverage_market:.2f}x  (bank's preferred minimum: 1.50x)
  Coverage (Distress):   {coverage_distress:.2f}x

COLLATERAL SCORE BREAKDOWN:
{collateral_breakdown}

Write EXACTLY 2 paragraphs:

Paragraph 1 (90–120 words): Asset description and quality.
  Describe the type of security being offered. Comment on asset liquidity — 
  immovable property (lower liquidity), plant & machinery (medium), 
  book debts / receivables (higher liquidity). Mention charge rank (first, second, 
  pari passu) and whether any assets are pledged elsewhere. 
  Use terms: "registered mortgage", "hypothecation", "first charge", "pari passu".

Paragraph 2 (80–100 words): Coverage adequacy.
  State both coverage ratios (market and distress) clearly. Compare to the 
  bank's preferred minimum of 1.50x. If coverage is below threshold, state the 
  shortfall and the condition precedent required. If above threshold, confirm 
  adequate secondary recovery. Conclude with whether collateral is adequate,  
  marginal, or insufficient.

Total: 170–220 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 6 — CONDITIONS (Five Cs — C5)
# ─────────────────────────────────────────────────────────────

CONDITIONS_PROMPT = """
{system_preamble}

=== TASK: CONDITIONS SECTION (Five Cs — C5) ===
Conditions cover the external environment — industry health, regulatory climate, macro economy.

COMPANY: {company_name} | INDUSTRY: {industry}
CONDITIONS SCORE: {conditions_score}/100 ({conditions_band})

SECTOR INTELLIGENCE (research agent):
  Sector Outlook Score: {sector_score}/100
  News Signals:         {news_signals}
  Sector Flags:         {sector_flags}
  Regulatory Context:   {regulatory_notes}

MACRO CONTEXT:
  RBI Repo Rate:    {repo_rate:.2f}%
  Base Rate:        {base_rate:.2f}% (Repo + {spread:.2f}% spread)

Write EXACTLY 2 paragraphs:

Paragraph 1 (90–120 words): Sector and industry outlook.
  Describe the state of the {industry} sector as of the current date.
  Cite any specific findings from the news signals or sector flags above.
  Are tailwinds or headwinds dominant? Reference demand, pricing, regulatory, 
  or competition dynamics. If sector_score ≥70: favourable; 50–69: neutral; <50: challenging.

Paragraph 2 (70–90 words): Regulatory and macro environment.
  Cover the interest rate environment (RBI repo trajectory), any sector-specific RBI 
  or SEBI regulations relevant to this borrower, and GST/tax compliance context.
  If any regulatory flags exist, state them explicitly.
  Conclude: are conditions supportive, neutral, or headwind-heavy for this borrower?

Total: 160–210 words.
"""


# ─────────────────────────────────────────────────────────────
# SECTION 7 — RISK MITIGANTS & CONDITIONS PRECEDENT
# ─────────────────────────────────────────────────────────────

RISK_MITIGANTS_PROMPT = """
{system_preamble}

=== TASK: RISK MITIGANTS & RECOMMENDATION SECTION ===

COMPANY: {company_name}
FINAL DECISION: {decision}
RECOMMENDED AMOUNT: ₹{recommended_cr:.2f} Crore at {interest_rate:.2f}% p.a.

IDENTIFIED RISKS AND THEIR MITIGANTS:
{risk_mitigant_table}

CONDITIONS PRECEDENT (pre-disbursement):
{conditions_list}

ONGOING COVENANTS:
{covenants_list}

Write EXACTLY 3 parts — do NOT add headers, just write them as flowing paragraphs:

Part 1 — Risk Mitigants (100–130 words):
  For each risk listed in the table, write one sentence stating the specific 
  mitigant in banker language. Be specific (e.g., "The collateral shortfall of 0.12x 
  is mitigated by..."). Avoid generic statements.

Part 2 — Conditions Precedent (60–80 words):
  Summarise the conditions precedent in prose (not bullet points). 
  State them as requirements that must be met before first drawdown.

Part 3 — Covenants (60–80 words):
  Summarise the key ongoing covenants in prose. 
  State from which date/event they are triggered.
  Mention the consequence of covenant breach (right of recall).

Total: 220–290 words.
"""
