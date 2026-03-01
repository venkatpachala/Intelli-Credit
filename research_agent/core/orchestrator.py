"""
core/orchestrator.py
====================
Runs all 6 research sources concurrently (asyncio.gather) including Primary Insights,
collects flags + findings, passes them to tagger and scorer,
and assembles the final ResearchOutput.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

import structlog

from config.settings import get_settings
from core.entity_profile import EntityProfile
from core.output_contract import (
    DataSource, ResearchOutput, RiskBand, SourceResult,
)
from processing.scorer import compute_score
from processing.tagger import assign_tags
from sources.all_sources import (
    ECourtSource, GSTNSource, MCASource, NewsSource, RBISource,
)
from sources.internal_insights import PrimaryInsightSource

logger   = structlog.get_logger(__name__)
settings = get_settings()


async def run_research(
    entity: EntityProfile,
    db=None,
) -> ResearchOutput:
    """
    Orchestrate all 5 sources concurrently, aggregate results,
    score, tag, and return a ResearchOutput.

    Parameters
    ----------
    entity : EntityProfile
        Canonical internal entity model (built by entity_builder).
    db : AsyncSession | None
        SQLAlchemy async DB session (passed to RBI source for pg_trgm queries).
        If None, RBI source falls back to file-based lookup.
    """
    log        = logger.bind(case_id=entity.case_id)
    started_at = datetime.utcnow()
    log.info("orchestrator_started")

    # ── Instantiate sources ───────────────────────────────────
    rbi_source    = RBISource()
    mca_source    = MCASource()
    ecourt_source = ECourtSource()
    news_source   = NewsSource()
    gstn_source   = GSTNSource()
    insight_source = PrimaryInsightSource()

    # ── Run all 6 concurrently ────────────────────────────────
    results = await asyncio.gather(
        _run_source(
            name=DataSource.RBI,
            coro=rbi_source.check(entity, db),
        ),
        _run_source(
            name=DataSource.MCA,
            coro=mca_source.fetch(entity),
        ),
        _run_source(
            name=DataSource.ECOURTS,
            coro=ecourt_source.search(entity),
        ),
        _run_source(
            name=DataSource.NEWS,
            coro=news_source.crawl(entity),
        ),
        _run_source(
            name=DataSource.GSTN,
            coro=gstn_source.fetch(entity),
        ),
        _run_source(
            name=DataSource.INTERNAL,
            coro=insight_source.analyze(entity),
        ),
        return_exceptions=False,   # individual source errors already handled inside
    )

    # ── Clean up HTTP clients ─────────────────────────────────
    await asyncio.gather(
        mca_source.close(),
        ecourt_source.close(),
        gstn_source.close(),
        return_exceptions=True,
    )

    # ── Aggregate ─────────────────────────────────────────────
    all_flags    = []
    all_findings = []
    for sr in results:
        all_flags.extend(sr.flags)
        all_findings.extend(sr.findings)

    # ── Score ─────────────────────────────────────────────────
    risk_score, auto_reject = compute_score(all_flags, settings)
    risk_band               = _band(risk_score, auto_reject)

    # ── Tag ───────────────────────────────────────────────────
    tags = assign_tags(all_flags, entity, risk_band)

    log.info(
        "orchestrator_complete",
        score=risk_score,
        band=risk_band,
        flags=len(all_flags),
        auto_reject=auto_reject,
    )

    return ResearchOutput(
        case_id=entity.case_id,
        company_name=entity.legal_name,
        cin=entity.cin,
        gstin=entity.gstin,
        risk_score=risk_score,
        risk_band=risk_band,
        auto_reject=auto_reject,
        flags=all_flags,
        findings=all_findings,
        source_results=results,
        tags=tags,
        started_at=started_at,
    )


async def _run_source(
    name: DataSource,
    coro,
) -> SourceResult:
    """
    Wrapper that times a single source coroutine and converts
    its (flags, findings, raw_data) tuple to a SourceResult.
    Captures exceptions so one failing source never kills the run.
    """
    t0 = time.monotonic()
    try:
        flags, findings, raw_data = await asyncio.wait_for(
            coro,
            timeout=settings.source_timeout_seconds,
        )
        return SourceResult(
            source=name,
            flags=flags,
            findings=findings,
            raw_data=raw_data,
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    except asyncio.TimeoutError:
        logger.warning("source_timeout", source=name)
        return SourceResult(
            source=name,
            error=f"Timed out after {settings.source_timeout_seconds}s",
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    except Exception as exc:
        logger.error("source_error", source=name, error=str(exc))
        return SourceResult(
            source=name,
            error=str(exc),
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )


def _band(score: int, auto_reject: bool) -> RiskBand:
    """Map numeric score → RiskBand."""
    if auto_reject or score <= 0:
        return RiskBand.BLACK
    if score < settings.high_risk_threshold:
        return RiskBand.RED
    if score < settings.medium_risk_threshold:
        return RiskBand.AMBER
    return RiskBand.GREEN
