'use client';

import { useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Sidebar from '../../../components/Sidebar';
import { apiUploadDocs, apiStartPipeline } from '@/lib/api';
import styles from './UploadPage.module.css';

interface DocSlot { id: string; label: string; hint: string; files: File[]; required: boolean; }

const MANDATORY_DOCS: Omit<DocSlot, 'files'>[] = [
    { id: 'annual_report', label: 'Annual Report (Last 3 Years)', hint: 'FY24, FY23, FY22 reports', required: true },
    { id: 'bank_statements', label: 'Bank Statements (12 Months)', hint: 'CC / Current account statements', required: true },
    { id: 'itr', label: 'ITR + Computation (Last 2 Years)', hint: 'ITR FY24, FY23 with CA computation', required: true },
    { id: 'gst_returns', label: 'GST Returns — GSTR-3B (12M)', hint: 'Monthly GSTR-3B for 12 months', required: true },
    { id: 'gstr2a', label: 'GST Returns — GSTR-2A (12M)', hint: 'GSTR-2A purchase register — used for CV_011 ITC reconciliation', required: false },
    { id: 'cibil', label: 'CIBIL Commercial Report (CMR)', hint: 'Latest CIBIL CMR report (for CIBIL Source 6)', required: false },
];

const OPTIONAL_DOCS = [
    'Sanction Letters from Existing Lenders', 'Latest CMA Data / Projections',
    'Valuation Report (if collateral)', 'Board Resolution', 'MOA / AOA',
    'Site Visit Report', 'Rating Agency Report (ICRA / CRISIL / CARE)',
];

export default function UploadPage() {
    const { caseId } = useParams<{ caseId: string }>();
    const router = useRouter();

    const [docs, setDocs] = useState<DocSlot[]>(MANDATORY_DOCS.map(d => ({ ...d, files: [] })));
    const [optional, setOptional] = useState<{ label: string; files: File[] }[]>(
        OPTIONAL_DOCS.map(l => ({ label: l, files: [] }))
    );
    const [dragOver, setDragOver] = useState<string | null>(null);
    const [uploading, setUploading] = useState(false);
    const [uploadPct, setUploadPct] = useState(0);
    const [error, setError] = useState('');

    const allMandatoryDone = docs.every(d => !d.required || d.files.length > 0);
    const doneCount = docs.filter(d => d.files.length > 0).length;

    const handleDrop = useCallback((id: string, files: FileList | null, isOpt = false) => {
        if (!files) return;
        const arr = Array.from(files);
        if (isOpt) {
            setOptional(prev => prev.map(d => d.label === id ? { ...d, files: [...d.files, ...arr] } : d));
        } else {
            setDocs(prev => prev.map(d => d.id === id ? { ...d, files: [...d.files, ...arr] } : d));
        }
    }, []);

    const handleStart = async () => {
        setError('');
        setUploading(true);
        try {
            // Collect all files
            const allFiles: File[] = [
                ...docs.flatMap(d => d.files),
                ...optional.flatMap(d => d.files),
            ];
            // Upload files
            setUploadPct(20);
            await apiUploadDocs(caseId, allFiles);
            setUploadPct(60);
            // Start pipeline
            await apiStartPipeline(caseId);
            setUploadPct(100);
            router.push(`/cases/${caseId}/progress`);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Failed to start analysis');
            setUploading(false);
            setUploadPct(0);
        }
    };

    return (
        <div className={styles.layout}>
            <Sidebar role="manager" />

            <main className={styles.main}>
                <div className={styles.pageHeader}>
                    <div className={styles.headerLeft}>
                        <div className={`mono ${styles.caseLabel}`}>{caseId}</div>
                        <h1 className={styles.pageTitle}>Upload Documents</h1>
                    </div>
                    <div className={styles.stepBadge}>Step 3 of 4 — Upload Documents</div>
                </div>

                {/* Primary Insight Banner */}
                <div className={styles.insightBanner}>
                    <span className={styles.insightBannerIcon}>🏭</span>
                    <div className={styles.insightBannerText}>
                        <strong>Add Field Observations (Primary Insight)</strong> to let credit officer notes
                        adjust the AI composite score by up to ±15 points.
                    </div>
                    <a
                        href={`/cases/${caseId}/insights`}
                        className={styles.insightBannerBtn}
                    >
                        Open Field Insights &rarr;
                    </a>
                </div>

                {/* Progress bar */}
                <div className={styles.progressCard}>
                    <div className={styles.progressInfo}>
                        <span className={styles.progressLabel}>Mandatory Documents</span>
                        <span className={styles.progressCount}>{doneCount} / {docs.length}</span>
                    </div>
                    <div className={styles.progressTrack}>
                        <div className={styles.progressFill} style={{ width: `${(doneCount / docs.length) * 100}%` }} />
                    </div>
                    {allMandatoryDone && (
                        <div className={styles.allDoneBanner}>✅ All mandatory documents uploaded — ready to start analysis</div>
                    )}
                </div>

                {/* Mandatory docs */}
                <div className={styles.section}>
                    <h2 className={styles.sectionTitle}>📄 Mandatory Documents</h2>
                    <div className={styles.docList}>
                        {docs.map(doc => (
                            <div key={doc.id} className={`${styles.docSlot} ${doc.files.length > 0 ? styles.docDone : ''}`}>
                                <div className={styles.docLeft}>
                                    <span className={styles.docStatus}>
                                        {doc.files.length > 0 ? '✅' : '⚠️'}
                                    </span>
                                    <div>
                                        <div className={styles.docLabel}>
                                            {doc.label}
                                            {doc.files.length === 0 && <span className={styles.reqTag}>REQUIRED</span>}
                                        </div>
                                        {doc.files.length > 0 ? (
                                            <div className={styles.fileList}>
                                                {doc.files.map((f, i) => (
                                                    <span key={i} className={styles.fileName}>📎 {f.name}</span>
                                                ))}
                                            </div>
                                        ) : (
                                            <div className={styles.docHint}>{doc.hint}</div>
                                        )}
                                    </div>
                                </div>
                                <label
                                    className={`${styles.dropZone} ${dragOver === doc.id ? styles.dropActive : ''}`}
                                    onDragOver={e => { e.preventDefault(); setDragOver(doc.id); }}
                                    onDragLeave={() => setDragOver(null)}
                                    onDrop={e => { e.preventDefault(); setDragOver(null); handleDrop(doc.id, e.dataTransfer.files); }}
                                >
                                    <input type="file" multiple accept=".pdf,.xlsx,.xls,.csv,.docx"
                                        onChange={e => handleDrop(doc.id, e.target.files)} hidden />
                                    <span className={styles.dropIcon}>📂</span>
                                    <span className={styles.dropText}>
                                        {doc.files.length > 0 ? 'Add / Replace' : 'Drag & drop or click'}
                                    </span>
                                </label>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Optional docs */}
                <div className={styles.section}>
                    <h2 className={styles.sectionTitle}>
                        📎 Additional Documents
                        <span className={styles.optTag}> · Upload if available</span>
                    </h2>
                    <div className={styles.optGrid}>
                        {optional.map(od => (
                            <label key={od.label} className={styles.optSlot}>
                                <input type="file" accept=".pdf,.xlsx,.xls,.csv,.docx"
                                    onChange={e => handleDrop(od.label, e.target.files, true)} hidden />
                                <span className={styles.optCircle}>{od.files.length > 0 ? '✅' : '○'}</span>
                                <span className={styles.optLabel}>{od.label}</span>
                                <span className={styles.optUpload}>{od.files.length > 0 ? `${od.files.length} file(s)` : '+ Upload'}</span>
                            </label>
                        ))}
                    </div>
                </div>

                {!allMandatoryDone && (
                    <div className={styles.warnBanner}>
                        ⚠️ Upload all {docs.length} mandatory documents before proceeding.
                    </div>
                )}

                {error && <div className="form-error" style={{ marginBottom: 16 }}>⚠️ {error}</div>}

                {uploading && (
                    <div className={styles.uploadProgress}>
                        <div className={styles.uploadBar} style={{ width: `${uploadPct}%` }} />
                        <span className={styles.uploadText}>
                            {uploadPct < 60 ? 'Uploading documents…' : 'Starting AI pipeline…'} {uploadPct}%
                        </span>
                    </div>
                )}

                <div className={styles.actions}>
                    <button onClick={() => router.back()} className="btn-secondary">← Edit Application</button>
                    <button
                        id="btn-start-analysis"
                        className="btn-primary"
                        disabled={!allMandatoryDone || uploading}
                        onClick={handleStart}
                    >
                        {uploading ? <><span className="spinner" /> Starting…</> : '⚡ Start AI Analysis →'}
                    </button>
                </div>
            </main>
        </div>
    );
}
