'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import Sidebar from '../../../components/Sidebar';
import { apiGetCAM, apiSendToApprover, CAMData } from '@/lib/api';
import styles from './CAMViewer.module.css';

const DECISION_STYLE: Record<string, string> = {
    AMBER: styles.decisionAmber, GREEN: styles.decisionGreen,
    RED: styles.decisionRed, BLACK: styles.decisionBlack,
};
const FLAG_ICONS: Record<string, string> = {
    CRITICAL: '🔴', HIGH: '🟠', MEDIUM: '🟡', LOW: '🔵', POSITIVE: '🟢',
};
const C_COLORS: Record<string, string> = {
    green: 'var(--green)', amber: 'var(--amber)', red: 'var(--red)',
};

function ScoreBar({ score, max, color }: { score: number; max: number; color: string }) {
    return (
        <div className={styles.scoreBarTrack}>
            <div className={styles.scoreBarFill}
                style={{ width: `${(score / max) * 100}%`, background: C_COLORS[color] }} />
        </div>
    );
}

function formatCr(n: number): string {
    if (!n || n === 0) return '—';
    return `₹${(n / 10000000).toFixed(2)} Cr`;
}

export default function CAMViewerPage() {
    const { caseId } = useParams<{ caseId: string }>();
    const router = useRouter();
    const [cam, setCam] = useState<CAMData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showFullCAM, setShowFullCAM] = useState(false);
    const [sendLoading, setSendLoading] = useState(false);
    const [sendDone, setSendDone] = useState(false);
    const [userRole, setUserRole] = useState('');

    useEffect(() => {
        setUserRole(localStorage.getItem('user_role') || '');
        apiGetCAM(caseId)
            .then(setCam)
            .catch(e => setError(e.message))
            .finally(() => setLoading(false));
    }, [caseId]);

    const handleSendToApprover = async () => {
        setSendLoading(true);
        try {
            await apiSendToApprover(caseId);
            setSendDone(true);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Failed to send to approver');
        } finally {
            setSendLoading(false);
        }
    };

    if (loading) {
        return (
            <div className={styles.layout}>
                <Sidebar role={userRole === 'senior_approver' ? 'approver' : 'manager'} />
                <main className={styles.main}>
                    <div className={styles.loadingState}>
                        <span className="spinner spinner-lg" />
                        <span>Loading CAM report…</span>
                    </div>
                </main>
            </div>
        );
    }

    if (error || !cam) {
        return (
            <div className={styles.layout}>
                <Sidebar role={userRole === 'senior_approver' ? 'approver' : 'manager'} />
                <main className={styles.main}>
                    <div className={styles.loadingState}>
                        <div className={styles.errorIcon}>❌</div>
                        <div className={styles.errorTitle}>{error || 'CAM not found'}</div>
                        <div className={styles.errorDesc}>
                            The CAM may still be generating.{' '}
                            <button className="btn-ghost" onClick={() => window.location.reload()}>Refresh</button>
                        </div>
                        <Link href={`/cases/${caseId}/progress`} className="btn-secondary">
                            ← Check Pipeline Status
                        </Link>
                    </div>
                </main>
            </div>
        );
    }

    const totalRate = cam.rate_derivation.reduce((s, r) => s + r.rate, 0);
    const hasFlags = cam.risk_flags.some(g => g.flags.length > 0 && g.level !== 'POSITIVE');

    return (
        <div className={styles.layout}>
            <Sidebar role={userRole === 'senior_approver' ? 'approver' : 'manager'} />

            <main className={styles.main}>
                {/* Page header */}
                <div className={styles.pageHeader}>
                    <div>
                        <div className={styles.breadcrumb}>
                            <Link href={userRole === 'senior_approver' ? '/dashboard/approver' : '/dashboard/manager'}>
                                Dashboard
                            </Link>
                            <span>›</span>
                            <span>CAM Report</span>
                        </div>
                        <h1 className={styles.companyName}>{cam.company_name}</h1>
                        <div className={styles.metaRow}>
                            <span className={`mono ${styles.metaCaseId}`}>{cam.case_id}</span>
                            <span className={styles.metaDot}>·</span>
                            <span>Generated {cam.generated_at}</span>
                            <span className={styles.metaDot}>·</span>
                            <span>{cam.prepared_by}</span>
                        </div>
                    </div>
                    <div className={styles.headerActions}>
                        {userRole !== 'senior_approver' && !sendDone && (
                            <button
                                className="btn-primary"
                                onClick={handleSendToApprover}
                                disabled={sendLoading}
                                id="btn-send-to-approver"
                            >
                                {sendLoading ? <><span className="spinner" /> Sending…</> : '📤 Send to Approver'}
                            </button>
                        )}
                        {sendDone && (
                            <div className={styles.sentBadge}>✅ Sent to Approver Queue</div>
                        )}
                        {userRole === 'senior_approver' && (
                            <Link href={`/cases/${caseId}/review`} className="btn-primary">
                                Make Decision →
                            </Link>
                        )}
                    </div>
                </div>

                {/* Decision card */}
                <div className={`${styles.decisionCard} ${DECISION_STYLE[cam.decision_color]}`}>
                    <div className={styles.decisionBadge}>
                        {cam.decision_color === 'GREEN' ? '🟢'
                            : cam.decision_color === 'AMBER' ? '🟡'
                                : cam.decision_color === 'RED' ? '🔴' : '⚫'} {cam.decision}
                    </div>
                    <div className={styles.decisionGrid}>
                        {[
                            { label: 'Recommended Limit', value: formatCr(cam.recommended_limit) },
                            { label: 'Requested Limit', value: formatCr(cam.requested_limit) },
                            { label: 'Interest Rate', value: `${cam.interest_rate.toFixed(2)}% p.a.` },
                            { label: 'Tenor', value: `${cam.tenor} months` },
                        ].map(f => (
                            <div key={f.label} className={styles.decisionField}>
                                <div className={styles.dfLabel}>{f.label}</div>
                                <div className={styles.dfVal}>{f.value}</div>
                            </div>
                        ))}
                        <div className={styles.decisionField}>
                            <div className={styles.dfLabel}>Composite Score</div>
                            <div className={styles.dfVal}>
                                <span className={styles.scoreNum}>{cam.composite_score}</span>
                                <span className={styles.scoreMax}>/100</span>{' '}
                                <span className={`badge-${cam.decision_color.toLowerCase() === 'green' ? 'green' : cam.decision_color.toLowerCase() === 'amber' ? 'amber' : cam.decision_color.toLowerCase() === 'red' ? 'red' : 'black'}`}>
                                    {cam.decision_color}
                                </span>
                            </div>
                        </div>
                        {cam.research_risk_band && (
                            <div className={styles.decisionField}>
                                <div className={styles.dfLabel}>Research Risk Band</div>
                                <div className={styles.dfVal}>{cam.research_risk_band}</div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Decision summary */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>💡 AI Analysis Summary</div>
                    <p className={styles.decisionSummary}>&ldquo;{cam.decision_summary}&rdquo;</p>
                </div>

                {/* Decision Rationale (new 8th section) */}
                {(cam as any).decision_rationale && (
                    <div className={styles.section}>
                        <div className={styles.sectionTitle}>📋 Decision Rationale — Cross-Pillar Explanation</div>
                        <div className={styles.rationaleBox}>
                            <div className={styles.rationaleTag}>AI-Generated · Cross-Pillar Analysis · 3 Pillars</div>
                            <div className={styles.rationaleText}>{(cam as any).decision_rationale}</div>
                        </div>
                    </div>
                )}

                {/* Cross-pillar contradictions */}
                {(cam as any).cross_pillar_contradictions?.length > 0 && (
                    <div className={styles.section}>
                        <div className={styles.sectionTitleRow}>
                            <div className={styles.sectionTitle}>🔀 Cross-Pillar Contradictions</div>
                            <span className={styles.contradictionBadge}>
                                {(cam as any).cross_pillar_contradictions.length} detected
                            </span>
                        </div>
                        <div className={styles.contradictionList}>
                            {(cam as any).cross_pillar_contradictions.map((c: string, i: number) => (
                                <div key={i} className={styles.contradictionItem}>
                                    <span className={styles.contradictionIcon}>⚠️</span>
                                    <span>{c}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Primary Insight (Qualitative) Adjustment */}
                {((cam as any).qualitative_adjustment !== 0 && (cam as any).qualitative_adjustment !== undefined) && (
                    <div className={styles.section}>
                        <div className={styles.sectionTitle}>🏭 Primary Insight Score Adjustment</div>
                        <div className={styles.qualCard}>
                            <div className={styles.qualDelta}>
                                <span className={`${styles.qualDeltaNum} ${(cam as any).qualitative_adjustment > 0 ? styles.qualPos : styles.qualNeg
                                    }`}>
                                    {(cam as any).qualitative_adjustment > 0 ? '+' : ''}{(cam as any).qualitative_adjustment} pts
                                </span>
                                <span className={styles.qualDeltaLabel}>
                                    applied to composite score from field observations
                                </span>
                            </div>
                            {(cam as any).qualitative_explanations?.length > 0 && (
                                <ul className={styles.qualList}>
                                    {(cam as any).qualitative_explanations.map((e: string, i: number) => (
                                        <li key={i} className={styles.qualItem}>{e}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                )}

                {/* Five Cs */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>📊 Five Cs Scorecard</div>
                    <div className={styles.fiveCsGrid}>
                        {cam.five_c_scores.map(c => (
                            <div key={c.name} className={styles.cCard}>
                                <div className={styles.cHeader}>
                                    <span className={styles.cName}>{c.name}</span>
                                    <span className={styles.cScore} style={{ color: C_COLORS[c.color] }}>
                                        {c.score}/{c.max}
                                    </span>
                                </div>
                                <ScoreBar score={c.score} max={c.max} color={c.color} />
                            </div>
                        ))}
                    </div>
                </div>

                {/* Risk flags */}
                <div className={styles.section}>
                    <div className={styles.sectionTitleRow}>
                        <div className={styles.sectionTitle}>🚦 Risk Flags</div>
                        <div className={styles.flagSummary}>
                            {cam.risk_flags.find(f => f.level === 'CRITICAL')?.flags.length || 0} CRITICAL &nbsp;
                            {cam.risk_flags.find(f => f.level === 'HIGH')?.flags.length || 0} HIGH &nbsp;
                            {cam.risk_flags.find(f => f.level === 'MEDIUM')?.flags.length || 0} MEDIUM
                        </div>
                    </div>
                    {cam.risk_flags.map(group => (
                        <div key={group.level}
                            className={`${styles.flagGroup} ${styles[`fg_${group.level.toLowerCase()}`]}`}>
                            <div className={styles.flagGroupHeader}>
                                <span>{FLAG_ICONS[group.level]} {group.level}</span>
                                {group.flags.length === 0
                                    ? <span className={styles.noneText}>None</span>
                                    : <span className={styles.flagCount}>{group.flags.length} flag{group.flags.length > 1 ? 's' : ''}</span>}
                            </div>
                            {group.flags.length > 0 && (
                                <ul className={styles.flagList}>
                                    {group.flags.map(f => (
                                        <li key={f} className={styles.flagItem}>• {f}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    ))}
                </div>

                {/* Rate derivation */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>💰 Interest Rate Derivation</div>
                    <div className={styles.rateTable}>
                        {cam.rate_derivation.map((row, i) => (
                            <div key={i} className={`${styles.rateRow} ${row.is_base ? styles.rateBase : ''}`}>
                                <span className={styles.rateLabel}>{row.label}</span>
                                <span className={styles.rateVal}>{row.is_base ? '' : '+'}{row.rate.toFixed(2)}%</span>
                            </div>
                        ))}
                        <div className={styles.rateDivider} />
                        <div className={`${styles.rateRow} ${styles.rateFinal}`}>
                            <span className={styles.rateLabel}>Final Rate</span>
                            <span className={styles.rateVal}>{totalRate.toFixed(2)}%</span>
                        </div>
                    </div>
                </div>

                {/* Metadata */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>📈 Pipeline Metrics</div>
                    <div className={styles.metricsGrid}>
                        <div className={styles.metricBox}>
                            <div className={styles.metricLabel}>Extraction Flags</div>
                            <div className={styles.metricVal}>{cam.extraction_flags ?? 0}</div>
                        </div>
                        <div className={styles.metricBox}>
                            <div className={styles.metricLabel}>Research Flags</div>
                            <div className={styles.metricVal}>{cam.research_flags ?? 0}</div>
                        </div>
                        <div className={styles.metricBox}>
                            <div className={styles.metricLabel}>Research Score</div>
                            <div className={styles.metricVal}>{cam.research_risk_score ?? '—'}/100</div>
                        </div>
                        <div className={styles.metricBox}>
                            <div className={styles.metricLabel}>AI Risk Band</div>
                            <div className={styles.metricVal}>{cam.research_risk_band ?? '—'}</div>
                        </div>
                    </div>
                </div>

                {/* Tags */}
                {cam.tags && cam.tags.length > 0 && (
                    <div className={styles.section}>
                        <div className={styles.sectionTitle}>🏷️ Research Tags</div>
                        <div className={styles.tagsList}>
                            {cam.tags.map(t => (
                                <span key={t} className={styles.tagPill}>{t}</span>
                            ))}
                        </div>
                    </div>
                )}

                {/* Approver section */}
                {userRole === 'senior_approver' && (
                    <div className={styles.approverSection}>
                        <div className={styles.approverTitle}>── Senior Approver Action ──</div>
                        <Link href={`/cases/${caseId}/review`} className="btn-primary" style={{ fontSize: 15, padding: '12px 28px' }}>
                            Make Approval Decision →
                        </Link>
                    </div>
                )}

                {userRole !== 'senior_approver' && (
                    <div className={styles.approverSection}>
                        <div className={styles.approverTitle}>── Submit for Approval ──</div>
                        {sendDone ? (
                            <div className={styles.sentBadge}>✅ Case sent to Senior Approver queue</div>
                        ) : (
                            <button
                                className="btn-primary"
                                onClick={handleSendToApprover}
                                disabled={sendLoading}
                                style={{ fontSize: 15, padding: '12px 28px' }}
                            >
                                {sendLoading
                                    ? <><span className="spinner" /> Sending…</>
                                    : '📤 Send to Senior Approver →'}
                            </button>
                        )}
                    </div>
                )}
            </main>
        </div>
    );
}
