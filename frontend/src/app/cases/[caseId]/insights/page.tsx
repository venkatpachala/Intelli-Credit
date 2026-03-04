"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import styles from "./PrimaryInsightPage.module.css";

interface PrimaryInsightData {
    factory_visit_date?: string;
    factory_capacity_pct?: number;
    management_quality?: number;
    site_condition?: string;
    key_person_risk?: boolean;
    supply_chain_risk?: boolean;
    cibil_commercial_score?: number;
    notes?: string;
}

interface Props {
    params: { caseId: string };
}

export default function PrimaryInsightPage({ params }: Props) {
    const { caseId } = params;
    const router = useRouter();
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState("");
    const [caseInfo, setCaseInfo] = useState<{ company_name: string } | null>(null);

    const [form, setForm] = useState<PrimaryInsightData>({
        factory_visit_date: "",
        factory_capacity_pct: undefined,
        management_quality: 3,
        site_condition: "good",
        key_person_risk: false,
        supply_chain_risk: false,
        cibil_commercial_score: undefined,
        notes: "",
    });

    const [scorePreview, setScorePreview] = useState<{
        delta: number;
        explanations: string[];
    }>({ delta: 0, explanations: [] });

    const token =
        typeof window !== "undefined" ? localStorage.getItem("token") : null;

    useEffect(() => {
        // Load case info
        if (!token) return;
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/cases/${caseId}`, {
            headers: { Authorization: `Bearer ${token}` },
        })
            .then((r) => r.json())
            .then((d) => setCaseInfo(d))
            .catch(() => { });

        // Load existing primary insight
        fetch(
            `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/cases/${caseId}/primary-insight`,
            { headers: { Authorization: `Bearer ${token}` } }
        )
            .then((r) => r.json())
            .then((d) => {
                if (d.qualitative && Object.keys(d.qualitative).length > 0) {
                    setForm((prev) => ({ ...prev, ...d.qualitative }));
                }
            })
            .catch(() => { });
    }, [caseId, token]);

    // Live score preview (client-side estimate)
    useEffect(() => {
        let delta = 0;
        const explanations: string[] = [];

        if (form.factory_capacity_pct !== undefined) {
            const pct = form.factory_capacity_pct;
            if (pct >= 80) { delta += 8; explanations.push(`Factory capacity ${pct}% → +8 pts`); }
            else if (pct >= 60) { delta += 4; explanations.push(`Factory capacity ${pct}% → +4 pts`); }
            else if (pct >= 40) { delta -= 5; explanations.push(`Factory capacity ${pct}% → -5 pts`); }
            else { delta -= 12; explanations.push(`Factory capacity ${pct}% → -12 pts`); }
        }

        if (form.management_quality) {
            const mq = form.management_quality;
            const map: Record<number, [number, string]> = {
                5: [7, "Excellent mgmt → +7 pts"], 4: [4, "Good mgmt → +4 pts"],
                3: [0, "Average mgmt → 0 pts"], 2: [-6, "Below-avg mgmt → -6 pts"], 1: [-12, "Poor mgmt → -12 pts"],
            };
            const [d, l] = map[mq] || [0, ""];
            if (d !== 0) { delta += d; explanations.push(l); }
        }

        if (form.site_condition) {
            const sc: Record<string, number> = { excellent: 5, good: 3, average: 0, poor: -5, critical: -10 };
            const d = sc[form.site_condition] ?? 0;
            if (d !== 0) { delta += d; explanations.push(`Site ${form.site_condition} → ${d > 0 ? "+" : ""}${d} pts`); }
        }

        if (form.key_person_risk) { delta -= 5; explanations.push("Key-person risk → -5 pts"); }
        if (form.supply_chain_risk) { delta -= 4; explanations.push("Supply chain risk → -4 pts"); }

        if (form.cibil_commercial_score !== undefined) {
            const c = form.cibil_commercial_score;
            if (c >= 750) { delta += 6; explanations.push(`CIBIL ${c} → +6 pts`); }
            else if (c >= 700) { delta += 3; explanations.push(`CIBIL ${c} → +3 pts`); }
            else if (c < 650) { delta -= 8; explanations.push(`CIBIL ${c} → -8 pts`); }
        }

        // Cap at ±15
        delta = Math.max(-15, Math.min(15, delta));
        setScorePreview({ delta, explanations });
    }, [form]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setError("");

        // Clean: remove undefined/empty
        const payload: Record<string, unknown> = {};
        if (form.factory_visit_date) payload.factory_visit_date = form.factory_visit_date;
        if (form.factory_capacity_pct !== undefined) payload.factory_capacity_pct = form.factory_capacity_pct;
        if (form.management_quality) payload.management_quality = form.management_quality;
        if (form.site_condition) payload.site_condition = form.site_condition;
        if (form.key_person_risk !== undefined) payload.key_person_risk = form.key_person_risk;
        if (form.supply_chain_risk !== undefined) payload.supply_chain_risk = form.supply_chain_risk;
        if (form.cibil_commercial_score !== undefined) payload.cibil_commercial_score = form.cibil_commercial_score;
        if (form.notes) payload.notes = form.notes;

        try {
            const res = await fetch(
                `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/cases/${caseId}/primary-insight`,
                {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                    },
                    body: JSON.stringify(payload),
                }
            );
            if (!res.ok) throw new Error(await res.text());
            setSaved(true);
            setTimeout(() => router.push(`/cases/${caseId}/upload`), 1500);
        } catch (err) {
            setError(String(err));
        } finally {
            setSaving(false);
        }
    };

    const mgmtLabels: Record<number, string> = {
        1: "Poor", 2: "Below Average", 3: "Average", 4: "Good", 5: "Excellent"
    };

    return (
        <div className={styles.page}>
            <div className={styles.header}>
                <div className={styles.badge}>Pillar 3 · Primary Insight</div>
                <h1 className={styles.title}>
                    Field Due Diligence
                    {caseInfo && <span className={styles.company}> — {caseInfo.company_name}</span>}
                </h1>
                <p className={styles.subtitle}>
                    Enter your on-site observations. These directly adjust the AI composite score
                    (±15 pts) and appear in the Credit Appraisal Memo with full explainability.
                </p>
            </div>

            <form onSubmit={handleSubmit} className={styles.formGrid}>
                {/* Left column */}
                <div className={styles.leftCol}>
                    {/* Factory Visit */}
                    <section className={styles.card}>
                        <div className={styles.cardHeader}>
                            <span className={styles.cardIcon}>🏭</span>
                            <h2>Factory / Site Visit</h2>
                        </div>

                        <label className={styles.label}>Date of Visit</label>
                        <input
                            type="date"
                            className={styles.input}
                            value={form.factory_visit_date || ""}
                            onChange={(e) => setForm({ ...form, factory_visit_date: e.target.value })}
                        />

                        <label className={styles.label}>
                            Factory Capacity Utilisation (%)
                            {form.factory_capacity_pct !== undefined && (
                                <span className={styles.valueBadge}>{form.factory_capacity_pct}%</span>
                            )}
                        </label>
                        <input
                            type="range" min={0} max={100} step={5}
                            className={styles.slider}
                            value={form.factory_capacity_pct ?? 70}
                            onChange={(e) =>
                                setForm({ ...form, factory_capacity_pct: Number(e.target.value) })
                            }
                        />
                        <div className={styles.sliderLabels}>
                            <span>0% (Idle)</span><span>50% (Half)</span><span>100% (Full)</span>
                        </div>

                        <label className={styles.label}>Site / Facility Condition</label>
                        <div className={styles.buttonGroup}>
                            {["excellent", "good", "average", "poor", "critical"].map((s) => (
                                <button
                                    key={s}
                                    type="button"
                                    className={`${styles.groupBtn} ${form.site_condition === s ? styles.groupBtnActive : ""} ${styles[`site_${s}`]}`}
                                    onClick={() => setForm({ ...form, site_condition: s })}
                                >
                                    {s.charAt(0).toUpperCase() + s.slice(1)}
                                </button>
                            ))}
                        </div>
                    </section>

                    {/* Management Assessment */}
                    <section className={styles.card}>
                        <div className={styles.cardHeader}>
                            <span className={styles.cardIcon}>👔</span>
                            <h2>Management Assessment</h2>
                        </div>

                        <label className={styles.label}>
                            Management Quality Rating
                            <span className={styles.valueBadge}>
                                {mgmtLabels[form.management_quality || 3]} ({form.management_quality}/5)
                            </span>
                        </label>
                        <div className={styles.starsRow}>
                            {[1, 2, 3, 4, 5].map((n) => (
                                <button
                                    key={n}
                                    type="button"
                                    className={`${styles.star} ${(form.management_quality || 0) >= n ? styles.starOn : ""}`}
                                    onClick={() => setForm({ ...form, management_quality: n })}
                                >
                                    ★
                                </button>
                            ))}
                        </div>

                        <div className={styles.checkRow}>
                            <label className={styles.checkLabel}>
                                <input
                                    type="checkbox"
                                    checked={form.key_person_risk || false}
                                    onChange={(e) => setForm({ ...form, key_person_risk: e.target.checked })}
                                />
                                <span>Key-person risk <em>(business overly dependent on one individual)</em></span>
                            </label>
                        </div>

                        <div className={styles.checkRow}>
                            <label className={styles.checkLabel}>
                                <input
                                    type="checkbox"
                                    checked={form.supply_chain_risk || false}
                                    onChange={(e) => setForm({ ...form, supply_chain_risk: e.target.checked })}
                                />
                                <span>Supply chain concentration risk <em>(single supplier / single customer)</em></span>
                            </label>
                        </div>
                    </section>

                    {/* CIBIL */}
                    <section className={styles.card}>
                        <div className={styles.cardHeader}>
                            <span className={styles.cardIcon}>📊</span>
                            <h2>CIBIL Commercial Score</h2>
                        </div>
                        <p className={styles.cardNote}>
                            From CIBIL C-MAP report (if available). Leave blank to use the AI-estimated score.
                        </p>
                        <label className={styles.label}>
                            Score (300–900)
                            {form.cibil_commercial_score !== undefined && (
                                <span className={`${styles.valueBadge} ${form.cibil_commercial_score >= 750 ? styles.green :
                                        form.cibil_commercial_score >= 650 ? styles.amber : styles.red
                                    }`}>
                                    {form.cibil_commercial_score >= 750 ? "Very Good" :
                                        form.cibil_commercial_score >= 700 ? "Good" :
                                            form.cibil_commercial_score >= 650 ? "Fair" : "Poor"}
                                </span>
                            )}
                        </label>
                        <input
                            type="number" min={300} max={900} step={1}
                            placeholder="e.g. 750"
                            className={styles.input}
                            value={form.cibil_commercial_score ?? ""}
                            onChange={(e) =>
                                setForm({
                                    ...form,
                                    cibil_commercial_score: e.target.value ? Number(e.target.value) : undefined,
                                })
                            }
                        />
                    </section>
                </div>

                {/* Right column */}
                <div className={styles.rightCol}>
                    {/* Score Preview */}
                    <div className={styles.scoreCard}>
                        <div className={styles.scoreCardTitle}>Live Score Impact Preview</div>
                        <div className={`${styles.scoreDelta} ${scorePreview.delta > 0 ? styles.deltaPos :
                                scorePreview.delta < 0 ? styles.deltaNeg : styles.deltaZero
                            }`}>
                            {scorePreview.delta > 0 ? "+" : ""}{scorePreview.delta} pts
                        </div>
                        <div className={styles.scoreNote}>
                            Applied to composite score (max ±15 pts)
                        </div>
                        {scorePreview.explanations.length > 0 ? (
                            <ul className={styles.explainList}>
                                {scorePreview.explanations.map((e, i) => (
                                    <li key={i} className={styles.explainItem}>
                                        <span className={
                                            e.includes("+") ? styles.explainPos : styles.explainNeg
                                        }>
                                            {e.includes("+") ? "▲" : e.includes("-") ? "▼" : "●"}
                                        </span>
                                        {e}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className={styles.noExplain}>Fill in the fields to see score impact</p>
                        )}
                        <div className={styles.explainFooter}>
                            All adjustments will appear verbatim in the generated CAM document
                            with the label <strong>[PRIMARY INSIGHT]</strong>
                        </div>
                    </div>

                    {/* Qualitative Notes */}
                    <section className={styles.card}>
                        <div className={styles.cardHeader}>
                            <span className={styles.cardIcon}>📝</span>
                            <h2>Credit Officer Notes</h2>
                        </div>
                        <p className={styles.cardNote}>
                            Observations from factory visit, management interviews, industry contacts.
                            AI will analyse these for keywords and include them in the Decision Rationale section of the CAM.
                        </p>
                        <textarea
                            rows={8}
                            className={styles.textarea}
                            placeholder={
                                "Examples:\n" +
                                "• Facility is modern, well-maintained, operating at full capacity\n" +
                                "• MD has 20+ years of experience in the industry, strong management team\n" +
                                "• Company expanding into new product line — Rs. 15 Cr capex planned\n" +
                                "• Single-customer dependency (60% revenue from Reliance Industries) — supply chain risk"
                            }
                            value={form.notes || ""}
                            onChange={(e) => setForm({ ...form, notes: e.target.value })}
                        />
                    </section>

                    {/* Submit */}
                    {error && <div className={styles.error}>{error}</div>}
                    {saved && (
                        <div className={styles.success}>
                            ✅ Primary insight saved! Redirecting to document upload...
                        </div>
                    )}

                    <div className={styles.actions}>
                        <button
                            type="button"
                            className={styles.skipBtn}
                            onClick={() => router.push(`/cases/${caseId}/upload`)}
                        >
                            Skip — proceed to upload
                        </button>
                        <button type="submit" className={styles.submitBtn} disabled={saving}>
                            {saving ? "Saving..." : "Save & Continue →"}
                        </button>
                    </div>

                    <p className={styles.helpText}>
                        You can skip this step and add observations later. However, insights
                        must be saved <strong>before running the AI pipeline</strong> to affect the score.
                    </p>
                </div>
            </form>
        </div>
    );
}
