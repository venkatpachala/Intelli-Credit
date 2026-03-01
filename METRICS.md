# Intelli-Credit — Metrics, Mathematical Evaluation & Scoring Framework

This document details every metric used at each layer of the pipeline, the mathematical formulas behind them, and how information is evaluated to produce the final credit score.

---

## Layer 1: Data Extraction (LLM Structuring)

The LLM extracts 12 structured sections from raw documents. Each field includes a **confidence tag**:
- `HIGH` — exact number found verbatim in documents
- `MEDIUM` — inferred or computed from available data
- `LOW` — estimated based on context

### Key Financial Metrics Extracted

| Metric | Source Document | Formula |
|--------|---------------|---------|
| Revenue Growth | Annual Report / P&L | `ΔR = (R_t - R_{t-1}) / R_{t-1} × 100` |
| EBITDA Margin | Annual Report | `EBITDA Margin = EBITDA / Revenue × 100` |
| PAT Margin | Annual Report | `PAT Margin = Profit After Tax / Revenue × 100` |
| Debt-to-Equity | Balance Sheet | `D/E = Total Debt / Shareholders' Equity` |
| Interest Coverage Ratio | P&L Statement | `ICR = EBITDA / Interest Expense` |
| Working Capital Cycle | Balance Sheet + P&L | `WCC = Debtors Days + Inventory Days - Creditors Days` |
| Free Cash Flow Margin | Cash Flow Statement | `FCF Margin = (Operating CF - CapEx) / Revenue × 100` |

---

## Layer 2: Cross-Validation Engine (10 Checks)

Each check produces a **severity** (`CRITICAL > HIGH > MEDIUM > LOW`) and a **result** (`PASS / FAIL / FLAG / WARN / SKIP`).

### CV_001 — Interest Coverage Ratio (ICR)

**Purpose:** Can the company pay its interest obligations?

```
ICR = EBITDA / Interest Expense
```

| Condition | Result | Severity |
|-----------|--------|----------|
| ICR ≥ 1.5x | PASS | LOW |
| ICR < 1.5x | FAIL | HIGH |

> **Banking Standard:** RBI mandates ICR > 1.5x for term loans. ICR < 1.0x means the company cannot cover interest from operating profits.

---

### CV_002 — Gearing Ratio (Debt/Equity)

**Purpose:** How leveraged is the company?

```
Gearing = Total Debt / Shareholders' Equity
```

| Condition | Result | Severity |
|-----------|--------|----------|
| Gearing < 1.0x | PASS | LOW |
| 1.0x ≤ Gearing < 2.0x | WARN | MEDIUM |
| Gearing ≥ 2.0x | FAIL | CRITICAL |

> **Rationale:** A gearing > 2.0x means debt is twice the equity — a single bad quarter could wipe out the company.

---

### CV_003 — PAT Margin

**Purpose:** Is the company actually profitable?

```
PAT Margin = (Profit After Tax / Revenue) × 100
```

| Condition | Result | Severity |
|-----------|--------|----------|
| PAT Margin ≥ 2% | PASS | LOW |
| PAT Margin < 2% | WARN | MEDIUM |

> **Note:** A PAT margin below 2% indicates the company is barely profitable and vulnerable to any cost increase.

---

### CV_004 — Debt Trend Analysis

**Purpose:** Is debt increasing dangerously over time?

```
Debt Trend% = ((Debt_latest - Debt_earliest) / Debt_earliest) × 100
```

| Condition | Result | Severity |
|-----------|--------|----------|
| Debt reduced > 10% | PASS | LOW |
| -10% ≤ Δ ≤ 10% | PASS (Stable) | LOW |
| 10% < Δ ≤ 30% | WATCH | MEDIUM |
| Δ > 30% | WARN | HIGH |

---

### CV_005 — Cash Trend Analysis

**Purpose:** Is the company's liquidity deteriorating?

```
Cash Trend% = ((Cash_latest - Cash_earliest) / Cash_earliest) × 100
```

| Condition | Result | Severity |
|-----------|--------|----------|
| Cash grew or stable | PASS | LOW |
| Cash declined 10-30% | WATCH | MEDIUM |
| Cash declined > 30% | WARN — Liquidity Stress | HIGH |

---

### CV_006 — Revenue Consistency

**Purpose:** Detect revenue inflation or sudden collapse.

```
Revenue Growth% = ((Revenue_latest - Revenue_earliest) / Revenue_earliest) × 100
```

| Condition | Result | Severity |
|-----------|--------|----------|
| -10% ≤ Δ ≤ 100% | PASS — Normal Range | LOW |
| Δ < -30% | WARN — Investigate | HIGH |
| -30% < Δ < -10% | WATCH | MEDIUM |
| Δ > 100% | FLAG — Verify against GST/bank | HIGH |

> **India-Specific:** Revenue growth > 100% in 2 years without corresponding GST/bank data is a classic circular trading signal.

---

### CV_007 — Audit Qualifications

**Purpose:** Did the statutory auditor raise any red flags?

```
IF audit_qualifications[] is NOT empty → FLAG (HIGH)
ELSE → PASS (LOW)
```

> **Why This Matters:** Audit qualifications (Emphasis of Matter, Going Concern doubts) are the strongest independent signal of financial distress.

---

### CV_008 — Litigation Detection

**Purpose:** Scan for active legal proceedings.

```
Keyword scan on red_flags[]:
  ["litigation", "court", "legal", "suit", "ibc", "nclt",
   "winding up", "insolvency", "ni act", "cheque bounce"]

IF any match → FLAG (HIGH)
ELSE → PASS (LOW)
```

---

### CV_009 — GST vs Bank Statement (Circular Trading Detector) ⚠️

**Purpose:** The most powerful fraud detection check. Compares declared GST turnover against actual bank credits.

```
Ratio = GST_Turnover / Bank_Credits
Mismatch% = (Ratio - 1) × 100
```

| Condition | Result | Severity |
|-----------|--------|----------|
| Ratio ≤ 1.1x | PASS | LOW |
| 1.1x < Ratio ≤ 1.3x | WARN — Minor Mismatch | MEDIUM |
| Ratio > 1.3x | **CRITICAL FLAG** — Circular Trading | **CRITICAL** |

> **Explanation:** If a company reports ₹10 Cr GST turnover but only ₹7 Cr flows through its bank account, someone is creating fake invoices. This is the primary detection mechanism for circular trading in Indian lending.

---

### CV_010 — ITC Ratio vs Sector Benchmark

**Purpose:** Detect fabricated Input Tax Credit claims.

```
Actual ITC Ratio = ITC_Claimed / GST_Turnover
Benchmark = Sector-specific value (see table)
Deviation% = ((Actual - Benchmark) / Benchmark) × 100
```

**Sector Benchmarks (India):**
| Sector | ITC Benchmark |
|--------|--------------|
| Trading | 5% |
| Agriculture | 6% |
| Logistics | 7% |
| Entertainment | 8% |
| Pharmaceuticals | 9% |
| Infrastructure | 10% |
| Textiles | 10% |
| Steel & Metals | 12% |
| Real Estate | 14% |

| Deviation | Result | Severity |
|-----------|--------|----------|
| ≤ 25% above benchmark | PASS | LOW |
| 25-50% above | WATCH | MEDIUM |
| > 50% above | FLAG — Fabricated Credits | HIGH |

---

## Layer 3: Risk Scoring Engine

### Individual Dimension Scores (0-10 scale)

Each dimension is scored from **0 (safest)** to **10 (riskiest)** by the LLM. If the LLM doesn't provide scores, a fallback formula is used:

```
Financial Risk Score (fallback) = min(Critical_failures × 3 + High_failures × 2 + Medium_warnings, 10)
```

Where:
- `Critical_failures` = CV checks with severity = CRITICAL and result contains FAIL/FLAG
- `High_failures` = CV checks with severity = HIGH and result contains FAIL/FLAG
- `Medium_warnings` = CV checks with severity = MEDIUM and result contains WARN

### Overall Credit Score

```
Overall Credit Score = (Financial + Compliance + Management + Industry) / 4
```

### Risk Category Mapping

| Score Range | Category |
|------------|----------|
| 0.0 — 3.0 | **Low** ✅ |
| 3.1 — 5.0 | **Moderate** ⚠️ |
| 5.1 — 7.0 | **High** 🔶 |
| 7.1 — 10.0 | **Very High** 🔴 |

---

## Layer 4: Research Agent Enrichment

The web search agent runs 6 targeted query categories and uses keyword-based severity detection:

### Litigation Severity Escalation
```python
serious_keywords = ["nclt", "ibc", "insolvency", "fraud", "arrest", "scam", "default"]
IF any keyword found in web results → litigation_risk.active_cases_severity = "High"
```

### Management Credibility Check
```python
neg_keywords = ["arrest", "fraud", "scam", "resignation", "controversy", "disqualified"]
IF any keyword in promoter news → management_quality.credibility_risk = "High"
```

### Regulatory Violation Detection
```python
IF any of ["penalty", "fine", "violation", "ban", "suspended"] in regulatory news
→ compliance_risk.regulatory_violations += [title]
```

---

## Layer 5: Vector Database (FAISS)

### Embedding Models
| Provider | Model | Dimensions | Use Case |
|----------|-------|-----------|----------|
| Gemini (Primary) | `gemini-embedding-001` | 3072 | High-precision semantic search |
| HuggingFace (Fallback) | `BAAI/bge-large-en-v1.5` | 1024 | Cost-effective, strong English |

### Similarity Search
```
FAISS uses L2 (Euclidean) distance for nearest-neighbor search:
    distance(a, b) = √(Σ(aᵢ - bᵢ)²)
```

### Chunking Strategy
```
Chunk Size = 1000 characters
Overlap    = 200 characters (20%)
```

> **Why 20% overlap?** Financial documents have cross-references between paragraphs. A 200-char overlap ensures that sentences split across chunk boundaries are still captured in at least one chunk.
