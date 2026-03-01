"""
validators/cross.py
Cross-validates extracted financial figures across multiple sources.

Detects:
    - Circular trading (GST turnover vs bank credits mismatch)
    - Revenue inflation (abnormal growth)
    - Fabricated ITC claims (ITC vs sector benchmark)
    - Leverage issues (gearing, interest coverage)
    - Audit qualifications and litigation flags
    - Cash and debt trends
"""


class CrossValidator:
    """
    Runs 10 validation checks on the structured extracted data.
    Each check returns a dict:
        check_id    : str   — CV_001 through CV_010
        description : str   — human readable name
        result      : str   — starts with PASS / FAIL / FLAG / WARN / SKIP / ERROR
        severity    : str   — CRITICAL / HIGH / MEDIUM / LOW
    """

    # ITC as % of GST turnover — sector benchmarks for India
    SECTOR_ITC_BENCHMARKS = {
        "Trading":           0.05,
        "Textiles":          0.10,
        "Steel & Metals":    0.12,
        "Iron & Steel":      0.12,
        "Pharmaceuticals":   0.09,
        "Logistics":         0.07,
        "Real Estate":       0.14,
        "Electricals":       0.12,
        "Agriculture":       0.06,
        "Infrastructure":    0.10,
        "Entertainment":     0.08,
        "Default":           0.10,
    }

    def run(self, structured: dict) -> list:
        """
        Runs all 10 validation checks.
        Returns a flat list of check result dicts.
        """
        fields  = structured.get("fields", structured)
        results = []

        results += self._check_interest_coverage(fields)
        results += self._check_gearing(fields)
        results += self._check_pat_margin(fields)
        results += self._check_debt_trend(fields)
        results += self._check_cash_trend(fields)
        results += self._check_revenue_consistency(fields)
        results += self._check_audit_qualifications(fields)
        results += self._check_litigation(fields)
        results += self._check_gst_bank_mismatch(fields)
        results += self._check_itc_ratio(fields)

        return results

    # ─────────────────────────────────────────────────────────
    # CV_001 — Interest Coverage Ratio
    # ─────────────────────────────────────────────────────────
    def _check_interest_coverage(self, fields: dict) -> list:
        MIN_THRESHOLD = 1.5
        try:
            icr_data   = fields.get("credit_metrics", {}).get("interest_coverage_ratio", {})
            if not icr_data:
                return [self._not_found("CV_001", "Interest Coverage Ratio")]

            latest_val = self._get_latest_value(icr_data)
            if latest_val is None:
                return [self._not_found("CV_001", "Interest Coverage Ratio")]

            passed = latest_val >= MIN_THRESHOLD
            return [{
                "check_id":    "CV_001",
                "description": "Interest Coverage Ratio ≥ 1.5x",
                "actual":      latest_val,
                "threshold":   MIN_THRESHOLD,
                "result":      f"{'PASS' if passed else 'FAIL'} — ICR at {latest_val}x",
                "severity":    "LOW" if passed else "HIGH",
            }]
        except Exception:
            return [self._error("CV_001", "Interest Coverage check")]

    # ─────────────────────────────────────────────────────────
    # CV_002 — Gearing Ratio
    # ─────────────────────────────────────────────────────────
    def _check_gearing(self, fields: dict) -> list:
        WARNING_LEVEL  = 1.0
        CRITICAL_LEVEL = 2.0
        try:
            gearing_data = fields.get("balance_sheet", {}).get("gearing_ratio", {})
            if not gearing_data:
                return [self._not_found("CV_002", "Gearing Ratio")]

            val = self._get_latest_value(gearing_data)
            if val is None:
                return [self._not_found("CV_002", "Gearing Ratio")]

            if val >= CRITICAL_LEVEL:
                result = f"FAIL — Gearing {val}x exceeds critical level 2.0x"
                sev    = "CRITICAL"
            elif val >= WARNING_LEVEL:
                result = f"WARN — Gearing {val}x above warning level 1.0x"
                sev    = "MEDIUM"
            else:
                result = f"PASS — Gearing {val}x is healthy"
                sev    = "LOW"

            return [{
                "check_id":    "CV_002",
                "description": "Gearing ratio check",
                "actual":      val,
                "result":      result,
                "severity":    sev,
            }]
        except Exception:
            return [self._error("CV_002", "Gearing check")]

    # ─────────────────────────────────────────────────────────
    # CV_003 — PAT Margin
    # ─────────────────────────────────────────────────────────
    def _check_pat_margin(self, fields: dict) -> list:
        MIN_MARGIN = 2.0
        try:
            margin_data = fields.get("income_statement", {}).get("pat_margin_pct", {})
            if not margin_data:
                return [self._not_found("CV_003", "PAT Margin")]

            val = self._get_latest_value(margin_data)
            if val is None:
                return [self._not_found("CV_003", "PAT Margin")]

            passed = val >= MIN_MARGIN
            return [{
                "check_id":    "CV_003",
                "description": "PAT Margin ≥ 2%",
                "actual":      f"{val}%",
                "threshold":   f"{MIN_MARGIN}%",
                "result":      f"{'PASS' if passed else 'WARN'} — PAT margin {val}%",
                "severity":    "LOW" if passed else "MEDIUM",
            }]
        except Exception:
            return [self._error("CV_003", "PAT Margin check")]

    # ─────────────────────────────────────────────────────────
    # CV_004 — Debt Trend
    # ─────────────────────────────────────────────────────────
    def _check_debt_trend(self, fields: dict) -> list:
        try:
            debt_data = fields.get("balance_sheet", {}).get("total_debt", {})
            if not debt_data:
                return [self._not_found("CV_004", "Debt Trend")]

            values = self._extract_time_series(debt_data)
            if len(values) < 2:
                return [{
                    "check_id":    "CV_004",
                    "description": "Debt trend analysis",
                    "result":      "SKIP — single period only, need 2+ years for trend",
                    "severity":    "LOW",
                }]

            trend_pct = round((values[-1] - values[0]) / values[0] * 100, 1)
            if trend_pct > 30:
                result = f"WARN — Debt grew {trend_pct}% over review period"
                sev    = "HIGH"
            elif trend_pct > 10:
                result = f"WATCH — Debt grew {trend_pct}%"
                sev    = "MEDIUM"
            elif trend_pct < -10:
                result = f"PASS — Debt reduced {abs(trend_pct)}% — positive sign"
                sev    = "LOW"
            else:
                result = f"PASS — Debt stable ({trend_pct}% change)"
                sev    = "LOW"

            return [{
                "check_id":    "CV_004",
                "description": "Debt trend analysis",
                "result":      result,
                "severity":    sev,
            }]
        except Exception:
            return [self._error("CV_004", "Debt trend check")]

    # ─────────────────────────────────────────────────────────
    # CV_005 — Cash Trend
    # ─────────────────────────────────────────────────────────
    def _check_cash_trend(self, fields: dict) -> list:
        try:
            cash_data = fields.get("balance_sheet", {}).get("cash_and_equivalents", {})
            if not cash_data:
                return [self._not_found("CV_005", "Cash Trend")]

            values = self._extract_time_series(cash_data)
            if len(values) < 2:
                return [{
                    "check_id":    "CV_005",
                    "description": "Cash trend analysis",
                    "result":      "SKIP — single period only",
                    "severity":    "LOW",
                }]

            trend_pct = round((values[-1] - values[0]) / values[0] * 100, 1)
            if trend_pct < -30:
                result = f"WARN — Cash fell {abs(trend_pct)}% — liquidity stress"
                sev    = "HIGH"
            elif trend_pct < -10:
                result = f"WATCH — Cash declined {abs(trend_pct)}%"
                sev    = "MEDIUM"
            else:
                result = f"PASS — Cash {'grew' if trend_pct >= 0 else 'stable'} ({trend_pct}%)"
                sev    = "LOW"

            return [{
                "check_id":    "CV_005",
                "description": "Cash trend analysis",
                "result":      result,
                "severity":    sev,
            }]
        except Exception:
            return [self._error("CV_005", "Cash trend check")]

    # ─────────────────────────────────────────────────────────
    # CV_006 — Revenue Consistency
    # ─────────────────────────────────────────────────────────
    def _check_revenue_consistency(self, fields: dict) -> list:
        try:
            rev_data = fields.get("income_statement", {}).get("total_revenue", {})
            if not rev_data:
                return [self._not_found("CV_006", "Revenue Consistency")]

            values = self._extract_time_series(rev_data)
            if len(values) < 2:
                return [{
                    "check_id":    "CV_006",
                    "description": "Revenue consistency check",
                    "result":      "SKIP — single period only",
                    "severity":    "LOW",
                }]

            growth_pct = round((values[-1] - values[0]) / values[0] * 100, 1)

            # >100% growth in 2 years is suspicious — flag for cross-check
            if growth_pct > 100:
                result = f"FLAG — Revenue grew {growth_pct}% — verify against GST/bank data"
                sev    = "HIGH"
            elif growth_pct < -30:
                result = f"WARN — Revenue declined {abs(growth_pct)}% — investigate cause"
                sev    = "HIGH"
            elif growth_pct < -10:
                result = f"WATCH — Revenue declined {abs(growth_pct)}%"
                sev    = "MEDIUM"
            else:
                result = f"PASS — Revenue trend: {growth_pct}% (normal range)"
                sev    = "LOW"

            return [{
                "check_id":    "CV_006",
                "description": "Revenue growth consistency check",
                "result":      result,
                "severity":    sev,
            }]
        except Exception:
            return [self._error("CV_006", "Revenue consistency check")]

    # ─────────────────────────────────────────────────────────
    # CV_007 — Audit Qualifications
    # ─────────────────────────────────────────────────────────
    def _check_audit_qualifications(self, fields: dict) -> list:
        try:
            quals = fields.get("audit_qualifications", [])
            if quals:
                return [{
                    "check_id":    "CV_007",
                    "description": "Audit qualifications check",
                    "result":      f"FLAG — {len(quals)} audit qualification(s) found",
                    "severity":    "HIGH",
                    "detail":      quals,
                }]
            return [{
                "check_id":    "CV_007",
                "description": "Audit qualifications check",
                "result":      "PASS — No audit qualifications found in document",
                "severity":    "LOW",
            }]
        except Exception:
            return [self._error("CV_007", "Audit qualifications check")]

    # ─────────────────────────────────────────────────────────
    # CV_008 — Litigation Detection
    # ─────────────────────────────────────────────────────────
    def _check_litigation(self, fields: dict) -> list:
        try:
            flags      = fields.get("red_flags_found", [])
            litigation = [
                f for f in flags
                if any(kw in str(f).lower() for kw in
                       ["litigation", "court", "legal", "suit", "ibc", "nclt",
                        "winding up", "insolvency", "ni act", "cheque bounce"])
            ]
            if litigation:
                return [{
                    "check_id":    "CV_008",
                    "description": "Litigation / legal risk check",
                    "result":      f"FLAG — {len(litigation)} litigation-related flag(s) detected",
                    "severity":    "HIGH",
                    "detail":      litigation,
                }]
            return [{
                "check_id":    "CV_008",
                "description": "Litigation / legal risk check",
                "result":      "PASS — No litigation flags found in document",
                "severity":    "LOW",
            }]
        except Exception:
            return [self._error("CV_008", "Litigation check")]

    # ─────────────────────────────────────────────────────────
    # CV_009 — GST vs Bank Statement Mismatch (Circular Trading)
    # THE MOST IMPORTANT FRAUD CHECK
    # ─────────────────────────────────────────────────────────
    def _check_gst_bank_mismatch(self, fields: dict) -> list:
        """
        Compares declared GST turnover against actual bank credits.
        A ratio > 1.3x means the company is declaring more revenue in
        GST returns than actually flows through its bank account.
        This is the classic "circular trading" or revenue inflation signal.

        This check only fires if BOTH GST and bank data are uploaded.
        """
        try:
            gst_val  = fields.get("gst_turnover")
            bank_val = fields.get("bank_credits")

            if not gst_val or not bank_val:
                return [{
                    "check_id":    "CV_009",
                    "description": "GST vs Bank Statement cross-check (Circular Trading Detector)",
                    "result":      "SKIP — Upload BOTH GSTR-3B CSV and bank statement to run this check",
                    "severity":    "LOW",
                    "tip":         (
                        "This is the most powerful fraud detection check. "
                        "Upload the GST returns CSV and bank statement CSV together."
                    ),
                }]

            ratio        = gst_val / bank_val
            mismatch_pct = round((ratio - 1) * 100, 1)

            if ratio > 1.3:
                return [{
                    "check_id":     "CV_009",
                    "description":  "GST vs Bank Statement cross-check",
                    "result":       (
                        f"CRITICAL FLAG — GST/Bank ratio {ratio:.2f}x. "
                        f"GST turnover is {mismatch_pct}% higher than bank credits. "
                        f"Circular trading or revenue inflation suspected."
                    ),
                    "severity":     "CRITICAL",
                    "gst_turnover": gst_val,
                    "bank_credits": bank_val,
                    "ratio":        round(ratio, 2),
                    "mismatch_pct": mismatch_pct,
                }]
            elif ratio > 1.1:
                return [{
                    "check_id":    "CV_009",
                    "description": "GST vs Bank Statement cross-check",
                    "result":      f"WARN — GST/Bank ratio {ratio:.2f}x — minor mismatch, verify",
                    "severity":    "MEDIUM",
                    "ratio":       round(ratio, 2),
                }]
            else:
                return [{
                    "check_id":    "CV_009",
                    "description": "GST vs Bank Statement cross-check",
                    "result":      f"PASS — GST/Bank ratio {ratio:.2f}x — within acceptable range",
                    "severity":    "LOW",
                    "ratio":       round(ratio, 2),
                }]
        except Exception:
            return [self._error("CV_009", "GST/Bank mismatch check")]

    # ─────────────────────────────────────────────────────────
    # CV_010 — ITC Ratio vs Sector Benchmark
    # ─────────────────────────────────────────────────────────
    def _check_itc_ratio(self, fields: dict) -> list:
        """
        Input Tax Credit (ITC) should be proportional to turnover for a sector.
        Trading companies have low ITC (~5%). Manufacturers have moderate ITC (~10-14%).
        Abnormally high ITC suggests fabricated input tax credit claims.
        """
        try:
            itc_val    = fields.get("itc_claimed")
            gst_val    = fields.get("gst_turnover")
            sector     = fields.get("company_profile", {}).get("sector", "Default")

            if not itc_val or not gst_val:
                return [{
                    "check_id":    "CV_010",
                    "description": "ITC ratio vs sector benchmark",
                    "result":      "SKIP — Upload GSTR-3B CSV with ITC and turnover columns",
                    "severity":    "LOW",
                }]

            actual_ratio    = itc_val / gst_val
            benchmark_ratio = self.SECTOR_ITC_BENCHMARKS.get(
                sector, self.SECTOR_ITC_BENCHMARKS["Default"]
            )
            deviation = round(
                (actual_ratio - benchmark_ratio) / benchmark_ratio * 100, 1
            )

            if deviation > 50:
                result = (
                    f"FLAG — ITC ratio {actual_ratio:.1%} is {deviation}% above "
                    f"sector benchmark ({benchmark_ratio:.1%}). "
                    f"Possible fabricated input credits."
                )
                sev = "HIGH"
            elif deviation > 25:
                result = (
                    f"WATCH — ITC ratio {actual_ratio:.1%} is {deviation}% above "
                    f"benchmark ({benchmark_ratio:.1%})"
                )
                sev = "MEDIUM"
            else:
                result = (
                    f"PASS — ITC ratio {actual_ratio:.1%} within "
                    f"sector norms (benchmark {benchmark_ratio:.1%})"
                )
                sev = "LOW"

            return [{
                "check_id":         "CV_010",
                "description":      "ITC ratio vs sector benchmark",
                "actual_ratio":     f"{actual_ratio:.1%}",
                "benchmark_ratio":  f"{benchmark_ratio:.1%}",
                "deviation_pct":    deviation,
                "result":           result,
                "severity":         sev,
            }]
        except Exception:
            return [self._error("CV_010", "ITC ratio check")]

    # ─────────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────────

    def _get_latest_value(self, data: dict):
        """Extracts the most recent numeric value from a field dict."""
        if isinstance(data, (int, float)):
            return data
        if isinstance(data, dict):
            # Check for direct 'value' key
            if "value" in data:
                return data["value"]
            # Look for period-keyed values — return last one
            numbers = [
                v for v in data.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            return numbers[-1] if numbers else None
        return None

    def _extract_time_series(self, data: dict) -> list:
        """
        Extracts a sorted list of numeric values from a period-keyed dict.
        Used to compute trends across FY2022, FY2023, FY2024 etc.
        """
        if isinstance(data, dict):
            numbers = [
                v for k, v in sorted(data.items())
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            return numbers
        return []

    def _not_found(self, check_id: str, field: str) -> dict:
        """Returns a SKIP result when required data is not in the extracted fields."""
        return {
            "check_id":    check_id,
            "description": f"{field} check",
            "result":      f"SKIP — {field} not found in extracted data",
            "severity":    "LOW",
        }

    def _error(self, check_id: str, check_name: str) -> dict:
        """Returns an ERROR result when a check throws an exception."""
        return {
            "check_id":    check_id,
            "description": check_name,
            "result":      "ERROR — Check failed due to missing or malformed data",
            "severity":    "LOW",
        }