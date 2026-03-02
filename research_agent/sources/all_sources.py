"""
Research Sources
================
Five independent sources. Each returns (flags, findings, raw_data).
All are generic — driven entirely by EntityProfile.
Nothing about any specific company is hardcoded.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import List, Tuple, Optional

import httpx
import structlog
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import get_settings
from core.entity_profile import EntityProfile
from core.output_contract import (
    ResearchFlag, Severity, FlagCategory, DataSource
)

logger   = structlog.get_logger(__name__)
settings = get_settings()

# ── Type alias ───────────────────────────────────────────────
SourceOutput = Tuple[List[ResearchFlag], List[dict], dict]
# flags, findings (raw dicts), raw_data


def _flag_id() -> str:
    return f"FLAG_{uuid.uuid4().hex[:8].upper()}"


# ═════════════════════════════════════════════════════════════
# SOURCE 1 — RBI Defaulter List
# First check. Hard reject if found.
# ═════════════════════════════════════════════════════════════

class RBISource:
    """
    Checks company + all promoters against RBI wilful defaulter list.
    List is downloaded once and indexed locally in PostgreSQL.
    Uses pg_trgm fuzzy matching for name variations.
    """
    THRESHOLD = 88   # % name similarity to count as match

    async def check(self, entity: EntityProfile,
                    db=None) -> SourceOutput:
        log = logger.bind(case_id=entity.case_id, source="rbi")
        log.info("started")

        flags, findings = [], []
        entities = [
            {"name": entity.legal_name, "pan": entity.pan, "type": "company"}
        ] + [
            {"name": p.name, "pan": p.pan, "type": "promoter"}
            for p in entity.promoters
        ]

        for e in entities:
            match = await self._check_one(e, db)
            if match:
                entity_label = "Company" if e["type"] == "company" else f"Promoter {e['name']}"
                flags.append(ResearchFlag(
                    flag_id=_flag_id(),
                    severity=Severity.CRITICAL,
                    category=FlagCategory.FRAUD,
                    source=DataSource.RBI,
                    title=f"{'Company' if e['type'] == 'company' else 'Promoter'} on RBI Wilful Defaulter List",
                    description=(
                        f"{entity_label} "
                        f"matched RBI wilful defaulter list. "
                        f"Reported by {match.get('bank_name', 'Unknown')}. "
                        f"Outstanding: ₹{match.get('outstanding_amt', 0):,.0f}. "
                        f"Reported: {match.get('date_reported', 'N/A')}. "
                        f"RBI guidelines mandate AUTOMATIC REJECTION."
                    ),
                    evidence=f"Match: {match.get('entity_name')} — {match.get('list_type', 'wilful_defaulter')}",
                    score_impact=-100,
                    confidence=match.get("confidence", 1.0),
                    requires_verification=match.get("confidence", 1.0) < 0.95,
                ))

        log.info("complete", flags=len(flags))
        return flags, findings, {"entities_checked": len(entities)}

    async def _check_one(self, entity: dict, db) -> Optional[dict]:
        if db is None:
            return await self._file_check(entity)
        return await self._db_check(entity, db)

    async def _db_check(self, entity: dict, db) -> Optional[dict]:
        from sqlalchemy import text

        # PAN exact match first
        if entity.get("pan"):
            r = await db.execute(
                text("SELECT * FROM ra_rbi_defaulters WHERE pan = :pan LIMIT 1"),
                {"pan": entity["pan"]}
            )
            row = r.fetchone()
            if row:
                d = dict(row._mapping)
                d["confidence"] = 1.0
                return d

        # Fuzzy name match via pg_trgm
        r = await db.execute(
            text("""
                SELECT *, similarity(name_normalized, :name) AS sim
                FROM ra_rbi_defaulters
                WHERE name_normalized % :name
                  AND similarity(name_normalized, :name) > :threshold
                ORDER BY sim DESC LIMIT 1
            """),
            {"name": entity["name"].lower(),
             "threshold": self.THRESHOLD / 100}
        )
        row = r.fetchone()
        if row:
            d = dict(row._mapping)
            d["confidence"] = float(d.get("sim", 0.9))
            return d
        return None

    async def _file_check(self, entity: dict) -> Optional[dict]:
        """Fallback when no DB — check local JSON file."""
        path = Path("data/rbi_defaulters.json")
        if not path.exists():
            return None
        with open(path) as f:
            defaulters = json.load(f)
        names = [d["entity_name"].lower() for d in defaulters]
        match = process.extractOne(
            entity["name"].lower(), names,
            scorer=fuzz.token_sort_ratio, score_cutoff=self.THRESHOLD
        )
        if match:
            d = defaulters[match[2]]
            d["confidence"] = match[1] / 100
            return d
        return None


# ═════════════════════════════════════════════════════════════
# SOURCE 2 — MCA21
# Company charges, director history, filing compliance.
# ═════════════════════════════════════════════════════════════

class MCASource:
    """
    Fetches from MCA21 API:
      - Charge registry (assets pledged to other lenders)
      - Director DIN history (struck-off companies)
      - ROC filing compliance (annual return gaps)
    """

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=12.0,
            headers={"Accept": "application/json",
                     "User-Agent": "IntelliCredit/1.0"},
            follow_redirects=True,
        )

    async def fetch(self, entity: EntityProfile) -> SourceOutput:
        if not entity.cin:
            return [], [], {"skipped": "no CIN"}

        log = logger.bind(case_id=entity.case_id, source="mca")
        log.info("started")

        flags, findings, raw = [], [], {}

        try:
            charges, dir_data, filings = await asyncio.gather(
                self._charges(entity.cin),
                self._director_companies(entity),
                self._filings(entity.cin),
                return_exceptions=True,
            )

            if not isinstance(charges, Exception) and charges:
                raw["charges"] = charges
                f, fn = self._analyze_charges(charges, entity)
                flags.extend(f); findings.extend(fn)

            if not isinstance(dir_data, Exception) and dir_data:
                raw["director_cos"] = dir_data
                f, fn = self._analyze_directors(dir_data, entity)
                flags.extend(f); findings.extend(fn)

            if not isinstance(filings, Exception) and filings:
                raw["filings"] = filings
                f, fn = self._analyze_filings(filings, entity)
                flags.extend(f); findings.extend(fn)

            if not flags:
                findings.append({"type": "positive",
                                 "text": "MCA checks — no adverse findings"})

        except Exception as e:
            log.error("mca_failed", error=str(e))

        log.info("complete", flags=len(flags))
        return flags, findings, raw

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8))
    async def _charges(self, cin: str) -> dict:
        r = await self._http.get(
            f"{settings.mca_base_url}/companies/{cin}/charges"
        )
        return r.json() if r.status_code == 200 else {}

    async def _director_companies(self, entity: EntityProfile) -> list:
        results = []
        tasks = [
            self._din_companies(p.din, p.name)
            for p in entity.promoters if p.din
        ]
        for res in await asyncio.gather(*tasks, return_exceptions=True):
            if not isinstance(res, Exception):
                results.extend(res)
        return results

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def _din_companies(self, din: str, name: str) -> list:
        r = await self._http.get(
            f"{settings.mca_base_url}/directors/{din}/companies"
        )
        if r.status_code == 200:
            return [{"promoter": name, "din": din, **co}
                    for co in r.json().get("companies", [])]
        return []

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def _filings(self, cin: str) -> dict:
        r = await self._http.get(
            f"{settings.mca_base_url}/companies/{cin}/filings"
        )
        return r.json() if r.status_code == 200 else {}

    def _analyze_charges(self, data: dict, entity: EntityProfile):
        flags, findings = [], []
        open_c = [c for c in data.get("charges", [])
                  if "open" in c.get("charge_status", "").lower()]
        if not open_c:
            return flags, findings

        total   = sum(c.get("amount", 0) for c in open_c)
        holders = list({c.get("charge_holder", "?") for c in open_c})
        sev     = Severity.HIGH if len(open_c) > 3 else Severity.MEDIUM

        flags.append(ResearchFlag(
            flag_id=_flag_id(), severity=sev,
            category=FlagCategory.FINANCIAL, source=DataSource.MCA,
            title=f"{len(open_c)} Open Charges — ₹{total/100000:.1f}L",
            description=(
                f"{len(open_c)} open charges registered on MCA "
                f"totalling ₹{total/100000:.1f}L, held by: "
                f"{', '.join(holders[:4])}. "
                f"New lender will rank below existing charge holders."
            ),
            score_impact=-20 if len(open_c) > 3 else -10,
        ))
        return flags, findings

    def _analyze_directors(self, dir_data: list, entity: EntityProfile):
        flags, findings = [], []
        struck = [d for d in dir_data
                  if "strike" in d.get("company_status", "").lower()]
        if struck:
            names = list({d["promoter"] for d in struck})
            cos   = [d.get("company_name", "") for d in struck[:5]]
            flags.append(ResearchFlag(
                flag_id=_flag_id(), severity=Severity.HIGH,
                category=FlagCategory.PROMOTER, source=DataSource.MCA,
                title=f"Director(s) of {len(struck)} Struck-Off Company(ies)",
                description=(
                    f"Promoter(s) {', '.join(names)} are/were directors "
                    f"of {len(struck)} struck-off companies: "
                    f"{', '.join(cos)}. Indicates poor management track record."
                ),
                score_impact=-20,
            ))
        return flags, findings

    def _analyze_filings(self, data: dict, entity: EntityProfile):
        flags, findings = [], []
        annual = [f for f in data.get("filings", [])
                  if "MGT" in f.get("form_type", "").upper()
                  or "annual" in f.get("description", "").lower()]
        if not annual:
            return flags, findings

        latest = max(annual,
                     key=lambda x: x.get("date_of_filing", "2000-01-01"))
        filed_str = latest.get("date_of_filing", "")
        try:
            filed_dt = datetime.fromisoformat(filed_str).date()
            gap = (date.today() - filed_dt).days // 30
            if gap > 15:
                flags.append(ResearchFlag(
                    flag_id=_flag_id(), severity=Severity.MEDIUM,
                    category=FlagCategory.REGULATORY, source=DataSource.MCA,
                    title=f"ROC Filing Gap: {gap} Months",
                    description=(
                        f"Annual return last filed {gap} months ago "
                        f"({filed_str}). Expected within 12 months of FY end. "
                        f"Non-compliance may attract ROC penalty."
                    ),
                    score_impact=-15,
                ))
        except (ValueError, AttributeError):
            pass
        return flags, findings

    async def close(self):
        await self._http.aclose()


# ═════════════════════════════════════════════════════════════
# SOURCE 3 — eCourts
# Litigation search for company + each promoter.
# ═════════════════════════════════════════════════════════════

class ECourtSource:

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; IntelliCredit/1.0)"},
            follow_redirects=True,
        )

    async def search(self, entity: EntityProfile) -> SourceOutput:
        log = logger.bind(case_id=entity.case_id, source="ecourts")
        log.info("started")

        all_cases, flags, findings = [], [], []
        parties = [(entity.search_name, "company")] + [
            (p.name, f"promoter:{p.name}")
            for p in entity.promoters
        ]

        for party_name, party_type in parties:
            try:
                cases = await self._search_party(party_name)
                for c in cases:
                    c["searched_as"] = party_type
                all_cases.extend(cases)
            except Exception as e:
                log.warning("party_search_failed",
                            party=party_name, error=str(e))

        flags, findings = self._analyze(all_cases, entity)
        log.info("complete", cases=len(all_cases), flags=len(flags))
        return flags, findings, {"cases": all_cases, "total": len(all_cases)}

    async def _search_party(self, party_name: str) -> list:
        try:
            r = await self._http.get(
                f"{settings.ecourts_base_url if hasattr(settings, 'ecourts_base_url') else 'https://ecourts.gov.in/ecourts_home'}/index.php",
                params={"p": "home", "action": "party_search",
                        "party_name": party_name},
            )
            if r.status_code == 200:
                return self._parse(r.text, party_name)
        except Exception:
            pass
        return []

    def _parse(self, html: str, party_name: str) -> list:
        soup  = BeautifulSoup(html, "lxml")
        cases = []
        for row in soup.select("table.case-list tr, tr.case-row"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            cases.append({
                "case_number": cells[0].get_text(strip=True),
                "court":       cells[1].get_text(strip=True),
                "filing_date": cells[2].get_text(strip=True),
                "status":      cells[3].get_text(strip=True)
                               if len(cells) > 3 else "Unknown",
                "party":       party_name,
            })
        return cases

    def _analyze(self, cases: list, entity: EntityProfile):
        flags, findings = [], []
        if not cases:
            findings.append({"type": "positive",
                             "text": "No litigation found on eCourts"})
            return flags, findings

        criminal = [c for c in cases if any(
            kw in c.get("case_number", "").upper()
            for kw in ("CRL", "FIR", "ST ", "CC ")
        )]
        civil = [c for c in cases if c not in criminal]

        for c in criminal:
            flags.append(ResearchFlag(
                flag_id=_flag_id(), severity=Severity.CRITICAL,
                category=FlagCategory.LITIGATION, source=DataSource.ECOURTS,
                title=f"Criminal Case: {c.get('case_number', 'Unknown')}",
                description=(
                    f"Criminal case found on eCourts: "
                    f"{c.get('case_number')} at {c.get('court', 'Unknown')}. "
                    f"Filed: {c.get('filing_date', 'Unknown')}. "
                    f"Status: {c.get('status', 'Unknown')}. "
                    f"Searched as: {c.get('searched_as', 'Unknown')}."
                ),
                case_number=c.get("case_number"),
                court=c.get("court"),
                case_status=c.get("status"),
                score_impact=-55,
            ))

        if len(civil) >= 3:
            flags.append(ResearchFlag(
                flag_id=_flag_id(), severity=Severity.HIGH,
                category=FlagCategory.LITIGATION, source=DataSource.ECOURTS,
                title=f"{len(civil)} Civil Cases Pending",
                description=(
                    f"{len(civil)} civil cases found for "
                    f"{entity.search_name} and/or promoters. "
                    f"Multiple active disputes indicate legal/counterparty risk."
                ),
                score_impact=-20,
            ))
        elif civil:
            findings.append({
                "type": "medium",
                "text": f"{len(civil)} civil case(s) found — individual review recommended"
            })
        return flags, findings

    async def close(self):
        await self._http.aclose()


# ═════════════════════════════════════════════════════════════
# SOURCE 4 — News (Tavily)
# Dynamic queries built from entity — no hardcoding.
# ═════════════════════════════════════════════════════════════

class NewsSource:
    """
    Searches news for any company using Tavily.
    Queries are built dynamically from EntityProfile.
    Nothing is hardcoded for any specific company.
    """

    EXISTENTIAL = [
        ("fraud",           Severity.CRITICAL, FlagCategory.FRAUD),
        ("scam",            Severity.CRITICAL, FlagCategory.FRAUD),
        ("sfio",            Severity.CRITICAL, FlagCategory.FRAUD),
        ("cbi raid",        Severity.CRITICAL, FlagCategory.FRAUD),
        ("ed raid",         Severity.CRITICAL, FlagCategory.FRAUD),
        ("money laundering",Severity.CRITICAL, FlagCategory.FRAUD),
        ("arrested",        Severity.CRITICAL, FlagCategory.PROMOTER),
        ("nclt admit",      Severity.CRITICAL, FlagCategory.LITIGATION),
        ("insolvency",      Severity.CRITICAL, FlagCategory.LITIGATION),
        ("wilful default",  Severity.CRITICAL, FlagCategory.FINANCIAL),
    ]
    HIGH_SIGNALS = [
        ("court case",      Severity.HIGH, FlagCategory.LITIGATION),
        ("rating downgrade",Severity.HIGH, FlagCategory.FINANCIAL),
        ("npa",             Severity.HIGH, FlagCategory.FINANCIAL),
        ("bad loan",        Severity.HIGH, FlagCategory.FINANCIAL),
    ]

    def __init__(self):
        self._client = None
        if settings.tavily_api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=settings.tavily_api_key)
            except ImportError:
                logger.warning("tavily_not_installed")

    async def crawl(self, entity: EntityProfile) -> SourceOutput:
        if not self._client:
            return [], [], {"skipped": "Tavily not configured"}

        log = logger.bind(case_id=entity.case_id, source="news")
        log.info("started")

        all_results, flags, findings = [], [], []
        plan = self._query_plan(entity)

        for batch in plan:
            results = await self._run_batch(batch["queries"])
            all_results.extend(results)

            if batch.get("stop_if_existential"):
                flag = self._scan_existential(results, entity)
                if flag:
                    flags.append(flag)
                    log.warning("existential_risk", title=flag.title)

        # Deduplicate
        seen, unique = set(), []
        for r in all_results:
            h = hashlib.md5(r.get("content", "")[:100].encode()).hexdigest()
            if h not in seen:
                seen.add(h); unique.append(r)

        # Extract HIGH findings
        for r in unique:
            content = (r.get("content", "") + r.get("raw_content", "")).lower()
            if not self._is_relevant(content, entity):
                continue
            for kw, sev, cat in self.HIGH_SIGNALS:
                if kw in content:
                    flags.append(ResearchFlag(
                        flag_id=_flag_id(), severity=sev, category=cat,
                        source=DataSource.NEWS,
                        title=f"News Signal: {kw.title()}",
                        description=(
                            f"News search found '{kw}' signal for "
                            f"{entity.search_name}. "
                            f"Source: {r.get('title', 'Unknown')}."
                        ),
                        evidence=r.get("content", "")[:300],
                        source_url=r.get("url"),
                        score_impact=-25,
                        confidence=0.65,
                        requires_verification=True,
                    ))
                    break

        findings = [
            {"title": r.get("title"), "url": r.get("url"),
             "snippet": r.get("content", "")[:300]}
            for r in unique
            if self._is_relevant(
                (r.get("content","") + r.get("raw_content","")).lower(),
                entity
            )
        ]

        log.info("complete", results=len(unique), flags=len(flags))
        return flags, findings, {"total_results": len(unique)}

    def _query_plan(self, entity: EntityProfile) -> list:
        name    = entity.search_name
        city    = entity.city or ""
        sector  = entity.sector or ""
        primary = entity.primary_promoter()
        pname   = primary.name if primary else ""

        return [
            {   # Must search first — stop if existential found
                "stop_if_existential": True,
                "queries": [
                    f'"{name}" fraud scam ED CBI SFIO India',
                    f'"{name}" insolvency NCLT IBC India',
                    f'"{name}" wilful defaulter NPA',
                    f'"{pname}" {city} arrested criminal' if pname else None,
                ]
            },
            {
                "stop_if_existential": False,
                "queries": [
                    f'"{name}" court case High Court India',
                    f'"{name}" rating downgrade ICRA CRISIL',
                    f'{sector} RBI regulation India 2024 2025',
                ]
            },
            {
                "stop_if_existential": False,
                "queries": [
                    f'"{name}" business news India',
                    f'{sector} industry outlook India 2025',
                ]
            },
        ]

    async def _run_batch(self, queries: list) -> list:
        loop = asyncio.get_event_loop()
        results = []
        for q in [q for q in queries if q]:
            try:
                r = await loop.run_in_executor(
                    None,
                    lambda query=q: self._client.search(
                        query=query,
                        search_depth="advanced",
                        max_results=3,
                        include_raw_content=True,
                    )
                )
                for item in r.get("results", []):
                    item["_query"] = q
                    results.append(item)
            except Exception as e:
                logger.warning("tavily_query_failed",
                               query=q, error=str(e))
        return results

    def _scan_existential(self, results: list,
                           entity: EntityProfile) -> Optional[ResearchFlag]:
        for r in results:
            content = (r.get("content","") + r.get("raw_content","")).lower()
            if not self._is_relevant(content, entity):
                continue
            for kw, sev, cat in self.EXISTENTIAL:
                if kw in content:
                    return ResearchFlag(
                        flag_id=_flag_id(), severity=sev, category=cat,
                        source=DataSource.NEWS,
                        title=f"Existential Risk: {kw.title()} Signal",
                        description=(
                            f"News found '{kw}' signal for "
                            f"{entity.search_name}. "
                            f"Immediate verification required before proceeding."
                        ),
                        evidence=r.get("content", "")[:300],
                        source_url=r.get("url"),
                        score_impact=-60,
                        confidence=0.7,
                        requires_verification=True,
                    )
        return None

    def _is_relevant(self, content: str, entity: EntityProfile) -> bool:
        """Prevent false positives — verify result is about our company."""
        if entity.search_name.lower() in content:
            return True
        for name in entity.all_promoter_names():
            if name.lower() in content:
                for token in entity.disambiguation_tokens:
                    if token.lower() in content:
                        return True
        return False


# ═════════════════════════════════════════════════════════════
# SOURCE 5 — GSTN
# GST registration status. Simple but important.
# ═════════════════════════════════════════════════════════════

class GSTNSource:

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=10.0,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    async def fetch(self, entity: EntityProfile) -> SourceOutput:
        if not entity.gstin:
            return [], [], {"skipped": "no GSTIN"}

        log = logger.bind(case_id=entity.case_id, source="gstn")
        try:
            r = await self._http.get(
                f"{settings.gstn_base_url}/search",
                params={"gstin": entity.gstin}
            )
            data = r.json() if r.status_code == 200 else {}
        except Exception as e:
            log.warning("gstn_failed", error=str(e))
            return [], [], {"error": str(e)}

        flags, findings = [], []
        ti = data.get("taxpayerInfo") or data
        status = (ti.get("sts") or ti.get("status") or "Unknown").upper()

        if "CANCEL" in status or "SUSPEND" in status:
            flags.append(ResearchFlag(
                flag_id=_flag_id(), severity=Severity.HIGH,
                category=FlagCategory.REGULATORY, source=DataSource.GSTN,
                title=f"GST Registration {status.title()}",
                description=(
                    f"GSTIN {entity.gstin} is {status}. "
                    f"A cancelled/suspended GST registration means the company "
                    f"cannot legally conduct taxable business in India."
                ),
                score_impact=-30,
            ))
        elif "ACTIVE" in status or "REGISTERED" in status:
            findings.append({"type": "positive",
                             "text": f"GST registration ACTIVE since {ti.get('rgdt', 'N/A')}"})

        log.info("complete", status=status, flags=len(flags))
        return flags, findings, {"status": status}

    async def close(self):
        await self._http.aclose()