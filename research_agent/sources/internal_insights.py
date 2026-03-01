"""
sources/internal_insights.py
============================
Evaluates qualitative notes from Credit Officers (Due Diligence / Site Visits).
Adjusts the risk score by raising flags based on basic keyword matching
(which can later be upgraded to an LLM-based sentiment analyzer).
"""

import uuid
from typing import List, Tuple

import structlog

from core.entity_profile import EntityProfile
from core.output_contract import (
    DataSource, FlagCategory, ResearchFlag, Severity
)

logger = structlog.get_logger(__name__)

SourceOutput = Tuple[List[ResearchFlag], List[dict], dict]

def _flag_id() -> str:
    return f"FLAG_{uuid.uuid4().hex[:8].upper()}"

class PrimaryInsightSource:
    """
    Analyzes qualitative notes provided in the ingestion payload.
    Adjusts final risk score based on nuances in the textual notes.
    """

    # Basic keyword rules (mocking an LLM for now)
    NEGATIVE_KEYWORDS = [
        ("below capacity", Severity.HIGH, FlagCategory.FINANCIAL, -20),
        ("40%", Severity.HIGH, FlagCategory.FINANCIAL, -20),
        ("poor condition", Severity.HIGH, FlagCategory.FINANCIAL, -20),
        ("strike", Severity.MEDIUM, FlagCategory.FINANCIAL, -15),
        ("poor management", Severity.HIGH, FlagCategory.PROMOTER, -20),
        ("discrepancy", Severity.HIGH, FlagCategory.FRAUD, -25),
        ("uncooperative", Severity.MEDIUM, FlagCategory.PROMOTER, -10),
        ("obsolete machinery", Severity.MEDIUM, FlagCategory.FINANCIAL, -15),
    ]

    POSITIVE_KEYWORDS = [
        "strong order book", "operating at full capacity", 
        "experienced management", "good condition"
    ]

    async def analyze(self, entity: EntityProfile) -> SourceOutput:
        if not entity.qualitative_notes:
            return [], [], {"skipped": "No qualitative notes provided"}
            
        log = logger.bind(case_id=entity.case_id, source="primary_insights")
        log.info("started")
        
        flags, findings = [], []
        
        for note in entity.qualitative_notes:
            content_lower = note.content.lower()
            note_flagged = False
            
            # Simple keyword-based extraction as a placeholder for LLM evaluation
            for kw, sev, cat, impact in self.NEGATIVE_KEYWORDS:
                if kw in content_lower:
                    flags.append(ResearchFlag(
                        flag_id=_flag_id(), 
                        severity=sev, 
                        category=cat,
                        source=DataSource.INTERNAL,
                        title=f"Negative Primary Insight",
                        description=(
                            f"Credit Officer observation raised a concern regarding '{kw}'. "
                            f"Full note: {note.content}"
                        ),
                        evidence=f"Reported by {note.author} on {note.date}",
                        score_impact=impact,
                        confidence=0.9,
                        requires_verification=False,
                    ))
                    note_flagged = True
                    break 
            
            if not note_flagged:
                positive_found = any(p in content_lower for p in self.POSITIVE_KEYWORDS)
                finding_type = "positive" if positive_found else "info"
                findings.append({
                    "type": finding_type,
                    "text": f"Insight ({note.author}): {note.content}"
                })
                
        log.info("complete", flags=len(flags))
        return flags, findings, {"notes_analyzed": len(entity.qualitative_notes)}
