'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import type { OccupancyGroupInfo } from '@/types';

const API_URL = '';

interface ExtractField {
    group: string; key: string; label: string;
    value: unknown; unit: string; confidence: 'high' | 'medium' | 'low';
    source: string; note?: string;
}
interface ExtractResponse {
    planId: string | null;
    fileName: string;
    originalFormat: string;
    pageCount?: number;
    extractionPath: string;
    tablesFound: { type1: boolean; type2: boolean; type3: boolean };
    fields: ExtractField[];
    prefill: Record<string, unknown>;
    planReference: Record<string, unknown> | null;
    planReferenceConfidence?: string | null;
    areaStatement: Record<string, unknown> | null;
    geometryAvailable: boolean;
    floorPageIndex?: number;
    blocks: Array<Record<string, unknown>>;
    pageImage: { base64: string; width: number; height: number } | null;
    warnings: string[];
    aiOcr: string;
}

const CONF_BADGE: Record<string, string> = {
    high: 'bg-[#E8F5E9] text-[#00863b] border-[#C8E6C9]',
    medium: 'bg-[#FFFDE7] text-[#B7791F] border-[#FFF59D]',
    low: 'bg-[#FFEBEE] text-[#D50000] border-[#FFCDD2]',
};

export default function UploadPage() {
    const router = useRouter();
    const inputRef = useRef<HTMLInputElement>(null);

    const [file, setFile] = useState<File | null>(null);
    const [dragOver, setDragOver] = useState(false);
    const [phase, setPhase] = useState<'upload' | 'review'>('upload');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [ext, setExt] = useState<ExtractResponse | null>(null);
    const [groups, setGroups] = useState<OccupancyGroupInfo[]>([]);

    // editable confirmed form state
    const [form, setForm] = useState<Record<string, unknown>>({});
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        fetch(`${API_URL}/api/occupancies`).then((r) => r.json()).then((d) => setGroups(d.groups || [])).catch(() => {});
    }, []);

    const confOf = (key: string): 'high' | 'medium' | 'low' | null => {
        const f = ext?.fields.find((x) => x.key === key);
        return f ? f.confidence : null;
    };

    const pickFile = (f: File) => {
        const ok = /\.(pdf|dwg|dxf|png|jpe?g)$/i.test(f.name);
        if (!ok) { setError('Unsupported file. Use PDF, DWG, DXF, PNG or JPG.'); return; }
        if (f.size > 12 * 1024 * 1024) { setError('File too large (max 12MB).'); return; }
        setError(null); setFile(f);
    };

    const runExtract = async () => {
        if (!file) return;
        setLoading(true); setError(null);
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch(`${API_URL}/api/plan/extract`, { method: 'POST', body: fd, signal: AbortSignal.timeout(120000) });
            const data: ExtractResponse & { error?: string } = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Extraction failed');
            setExt(data);
            // seed editable form with prefill + sensible defaults
            const pf = data.prefill || {};
            setForm({
                projectName: pf.projectName || '',
                city: pf.city || '',
                state: pf.state || '',
                primaryOccupancy: pf.primaryOccupancy || '',
                buildingHeight: pf.buildingHeight || 0,
                numberOfFloors: pf.numberOfFloors || (Array.isArray(pf.floorAreas) ? (pf.floorAreas as number[]).length : 1),
                floorAreas: pf.floorAreas || [0],
                basementArea: pf.basementArea || 0,
                basementCount: pf.basementCount || 0,
                constructionType: 'type12',
                hasKitchen: !!pf.hasKitchen,
                sprinklerProposed: !!pf.sprinklerProposed,
            });
            setPhase('review');
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Extraction failed');
        } finally {
            setLoading(false);
        }
    };

    const setField = (k: string, v: unknown) => setForm((p) => ({ ...p, [k]: v }));
    const setFloorCount = (n: number) => {
        const count = Math.max(1, Math.min(200, n || 1));
        setForm((p) => {
            const prev = (p.floorAreas as number[]) || [];
            const arr = [...prev];
            const last = arr[arr.length - 1] || 0;
            while (arr.length < count) arr.push(last);
            arr.length = count;
            return { ...p, numberOfFloors: count, floorAreas: arr };
        });
    };

    const confirmAndAnalyze = async () => {
        setError(null);
        if (!form.primaryOccupancy) { setError('Please confirm the occupancy before analysis.'); return; }
        const areas = (form.floorAreas as number[]) || [];
        if (!form.buildingHeight || (form.buildingHeight as number) <= 0) { setError('Please enter building height.'); return; }
        if (areas.length === 0 || areas.some((a) => !a || a <= 0)) { setError('Every floor area must be greater than 0.'); return; }
        setSubmitting(true);
        try {
            const body = {
                projectName: form.projectName, city: form.city, state: form.state,
                buildingHeight: form.buildingHeight, numberOfFloors: form.numberOfFloors,
                floorAreas: form.floorAreas, basementArea: form.basementArea, basementCount: form.basementCount,
                constructionType: form.constructionType, hasKitchen: form.hasKitchen, sprinklerProposed: form.sprinklerProposed,
                occupancySelection: { mode: 'single', primaryOccupancy: form.primaryOccupancy, secondaryOccupancies: [], occupancyZones: [] },
            };
            const res = await fetch(`${API_URL}/api/analyze-mixed`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Analysis failed');
            sessionStorage.setItem('firerulx_result', JSON.stringify(data));
            // stash plan session so the report can render plan-only sections
            sessionStorage.setItem('firerulx_plan', JSON.stringify({
                planId: ext?.planId, geometryAvailable: ext?.geometryAvailable,
                planReference: ext?.planReference, planReferenceConfidence: ext?.planReferenceConfidence,
                fileName: ext?.fileName, extractionPath: ext?.extractionPath, floorLabel: 'Ground Floor',
            }));
            router.push('/results');
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Analysis failed');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <main className="min-h-screen bg-[#F8F9FA]">
            <Navbar />
            <div className="pt-24 pb-16 px-4 sm:px-6 lg:px-10">
                <div className="max-w-5xl mx-auto">
                    <header className="mb-6 flex flex-col md:flex-row md:items-end md:justify-between gap-3">
                        <div>
                            <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.25em]">FireRuleX · NBC Part 4</p>
                            <h1 className="text-3xl font-bold text-slate-900 tracking-tight mt-1">Upload Building Plan</h1>
                            <p className="text-sm text-slate-500 mt-1">
                                We read the plan, show every value found with a confidence level, and let you correct anything
                                before the existing compliance engine runs. Nothing is auto-applied.
                            </p>
                        </div>
                        <button data-testid="back-home-btn" onClick={() => router.push('/')}
                            className="text-xs font-semibold text-slate-600 hover:text-slate-900 underline underline-offset-4">← Back to home</button>
                    </header>

                    {phase === 'upload' && (
                        <div className="bg-white border border-slate-200 p-6">
                            <div
                                data-testid="plan-dropzone"
                                onClick={() => inputRef.current?.click()}
                                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                                onDragLeave={() => setDragOver(false)}
                                onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files?.[0]) pickFile(e.dataTransfer.files[0]); }}
                                className={`border-2 border-dashed p-12 text-center cursor-pointer transition-colors ${dragOver ? 'border-[#2962FF] bg-blue-50' : 'border-slate-300 hover:border-slate-400'}`}
                            >
                                <input ref={inputRef} type="file" accept=".pdf,.dwg,.dxf,.png,.jpg,.jpeg" className="hidden"
                                    data-testid="plan-file-input"
                                    onChange={(e) => e.target.files?.[0] && pickFile(e.target.files[0])} />
                                {file ? (
                                    <div>
                                        <p className="text-lg font-semibold text-slate-800">{file.name}</p>
                                        <p className="text-xs text-slate-500 mt-1">{(file.size / 1024 / 1024).toFixed(1)} MB · ready</p>
                                    </div>
                                ) : (
                                    <div>
                                        <p className="text-lg font-semibold text-slate-600">Drop a building plan here</p>
                                        <p className="text-sm text-slate-400 mt-1">or click to browse · PDF / DWG / DXF / PNG / JPG · max 12MB</p>
                                    </div>
                                )}
                            </div>
                            {error && <p className="mt-3 text-xs text-red-600 border-l-2 border-red-500 pl-2">{error}</p>}
                            <button data-testid="extract-btn" disabled={!file || loading} onClick={runExtract}
                                className="w-full mt-4 bg-[#0A192F] text-white py-3 text-sm font-bold uppercase tracking-widest hover:bg-slate-800 disabled:opacity-40">
                                {loading ? 'Reading plan…' : 'Read Plan'}
                            </button>
                            <p className="mt-3 text-[11px] text-slate-400 leading-relaxed">
                                Works fully at zero cost using on-device PDF/vector extraction. Optional AI-vision OCR for scanned
                                sheets activates only if a key is configured by the operator.
                            </p>
                        </div>
                    )}

                    {phase === 'review' && ext && (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                            <section className="lg:col-span-2 space-y-6">
                                {/* Extraction summary */}
                                <div className="bg-white border border-slate-200" data-testid="extract-summary">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Extraction summary</p>
                                        <span className="text-[10px] font-mono text-slate-500">{ext.extractionPath} · {ext.originalFormat} · AI OCR: {ext.aiOcr}</span>
                                    </div>
                                    <div className="p-5 flex flex-wrap gap-2">
                                        {(['type1', 'type2', 'type3'] as const).map((t) => (
                                            <span key={t} data-testid={`table-chip-${t}`}
                                                className={`text-[11px] font-mono px-2 py-1 border ${ext.tablesFound[t] ? 'bg-[#E8F5E9] text-[#00863b] border-[#C8E6C9]' : 'bg-slate-50 text-slate-400 border-slate-200'}`}>
                                                Table {t.replace('type', 'Type ')}: {ext.tablesFound[t] ? 'found' : 'not found'}
                                            </span>
                                        ))}
                                        <span className={`text-[11px] font-mono px-2 py-1 border ${ext.geometryAvailable ? 'bg-[#E3F2FD] text-[#1565C0] border-[#BBDEFB]' : 'bg-slate-50 text-slate-400 border-slate-200'}`}>
                                            Vector geometry: {ext.geometryAvailable ? 'usable' : 'none'}
                                        </span>
                                    </div>
                                    {ext.warnings.length > 0 && (
                                        <div className="px-5 pb-4">
                                            <p className="text-[10px] font-bold text-[#B7791F] uppercase tracking-widest mb-1">Please review</p>
                                            <ul className="text-xs text-slate-600 space-y-1">
                                                {ext.warnings.map((w, i) => <li key={i} className="border-l-2 border-amber-300 pl-2">{w}</li>)}
                                            </ul>
                                        </div>
                                    )}
                                </div>

                                {/* Editable fields grouped like the manual form */}
                                <div className="bg-white border border-slate-200" data-testid="review-fields">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Review & correct — values feed the existing engine only after you confirm</p>
                                    </div>
                                    <div className="p-5 space-y-5">
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <Editable label="Project Name" conf={confOf('projectName')}>
                                                <input data-testid="rv-projectName" value={String(form.projectName || '')} onChange={(e) => setField('projectName', e.target.value)} className="inp" />
                                            </Editable>
                                            <Editable label="City" conf={confOf('city')}>
                                                <input data-testid="rv-city" value={String(form.city || '')} onChange={(e) => setField('city', e.target.value)} className="inp" />
                                            </Editable>
                                            <Editable label="Primary Occupancy (NBC)" conf={confOf('primaryOccupancy')}>
                                                <select data-testid="rv-occupancy" value={String(form.primaryOccupancy || '')} onChange={(e) => setField('primaryOccupancy', e.target.value)} className="inp bg-white font-mono">
                                                    <option value="">— select —</option>
                                                    {groups.map((g) => (
                                                        <optgroup key={g.group} label={`${g.group} · ${g.label}`}>
                                                            {g.subdivisions.map((s) => <option key={s.code} value={s.code}>{s.code} — {s.label}</option>)}
                                                        </optgroup>
                                                    ))}
                                                </select>
                                            </Editable>
                                            <Editable label="Construction Type" conf={null}>
                                                <select data-testid="rv-construction" value={String(form.constructionType)} onChange={(e) => setField('constructionType', e.target.value)} className="inp bg-white">
                                                    <option value="type12">Type 1/2 — fire-resistive</option>
                                                    <option value="type34">Type 3/4 — ordinary</option>
                                                </select>
                                            </Editable>
                                            <Editable label="Building Height (m)" conf={confOf('buildingHeight')}>
                                                <input type="number" data-testid="rv-height" value={String(form.buildingHeight || '')} onChange={(e) => setField('buildingHeight', Number(e.target.value))} className="inp font-mono text-right" />
                                            </Editable>
                                            <Editable label="Number of Floors" conf={confOf('numberOfFloors')}>
                                                <input type="number" data-testid="rv-floors" value={String(form.numberOfFloors || '')} onChange={(e) => setFloorCount(Number(e.target.value))} className="inp font-mono text-right" />
                                            </Editable>
                                        </div>

                                        <div>
                                            <div className="flex items-center gap-2 mb-2">
                                                <label className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Per-floor Areas (m²)</label>
                                                {confOf('floorAreas') && <ConfBadge conf={confOf('floorAreas')!} />}
                                            </div>
                                            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-56 overflow-y-auto pr-1">
                                                {((form.floorAreas as number[]) || []).map((a, idx) => (
                                                    <div key={idx} className="flex items-center gap-2">
                                                        <span className="text-[10px] text-slate-500 font-mono w-10 shrink-0">{idx === 0 ? 'GF' : `F${idx}`}</span>
                                                        <input type="number" data-testid={`rv-floor-area-${idx}`} value={a || ''}
                                                            onChange={(e) => { const arr = [...(form.floorAreas as number[])]; arr[idx] = Number(e.target.value); setField('floorAreas', arr); }}
                                                            className="inp font-mono text-right text-xs !py-1" />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 border-t border-slate-100">
                                            <Editable label="Basement Area (m²)" conf={confOf('basementArea')}>
                                                <input type="number" data-testid="rv-basement-area" value={String(form.basementArea || '')} onChange={(e) => setField('basementArea', Number(e.target.value))} className="inp font-mono text-right" />
                                            </Editable>
                                            <Editable label="Basement Levels" conf={confOf('basementCount')}>
                                                <input type="number" data-testid="rv-basement-count" value={String(form.basementCount || '')} onChange={(e) => setField('basementCount', Number(e.target.value))} className="inp font-mono text-right" />
                                            </Editable>
                                            <div className="flex items-center gap-4 pt-6">
                                                <label className="flex items-center gap-2 text-xs cursor-pointer">
                                                    <input type="checkbox" data-testid="rv-kitchen" checked={!!form.hasKitchen} onChange={(e) => setField('hasKitchen', e.target.checked)} className="w-3.5 h-3.5 accent-[#0A192F]" />
                                                    Kitchen {confOf('hasKitchen') && <ConfBadge conf={confOf('hasKitchen')!} />}
                                                </label>
                                                <label className="flex items-center gap-2 text-xs cursor-pointer">
                                                    <input type="checkbox" data-testid="rv-sprinkler" checked={!!form.sprinklerProposed} onChange={(e) => setField('sprinklerProposed', e.target.checked)} className="w-3.5 h-3.5 accent-[#0A192F]" />
                                                    Sprinklers {confOf('sprinklerProposed') && <ConfBadge conf={confOf('sprinklerProposed')!} />}
                                                </label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            {/* Right column: Plan Reference + confirm */}
                            <aside className="lg:col-span-1 space-y-6">
                                {ext.planReference && (
                                    <div className="bg-white border border-slate-200" data-testid="plan-reference-panel">
                                        <div className="px-5 py-3 border-b border-slate-200 bg-[#0A192F]">
                                            <p className="text-xs font-bold text-white uppercase tracking-[0.2em]">Plan Reference (Type 3)</p>
                                            <p className="text-[10px] text-slate-300 mt-0.5">Approval metadata — reference only, never used in calculations.</p>
                                        </div>
                                        <div className="p-4 text-xs space-y-1.5">
                                            {Object.entries(ext.planReference).filter(([k]) => k !== 'earlier_approved_case').map(([k, v]) => (
                                                <div key={k} className="flex justify-between gap-2 border-b border-slate-100 pb-1">
                                                    <span className="text-[10px] uppercase tracking-wider text-slate-500">{k.replace(/_/g, ' ')}</span>
                                                    <span className="font-mono text-slate-800 text-right break-all">{String(v)}</span>
                                                </div>
                                            ))}
                                            {ext.planReference.earlier_approved_case && (
                                                <div className="mt-2 pt-2 border-t border-slate-200">
                                                    <p className="text-[10px] uppercase tracking-wider text-[#B7791F] font-bold mb-1">Earlier approved case (linked)</p>
                                                    <p className="font-mono text-slate-700 break-all">{String((ext.planReference.earlier_approved_case as Record<string, unknown>).raw)}</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                <div className="bg-white border border-slate-200 sticky top-24">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Confirm</p>
                                    </div>
                                    <div className="p-5 space-y-3">
                                        <p className="text-xs text-slate-600 leading-relaxed">
                                            You are confirming the corrected values above. The existing, unmodified NBC Part 4 engine
                                            then runs exactly as in Manual Entry.
                                        </p>
                                        {error && <p className="text-xs text-red-600 border-l-2 border-red-500 pl-2">{error}</p>}
                                        <button data-testid="confirm-analyze-btn" disabled={submitting} onClick={confirmAndAnalyze}
                                            className="w-full bg-[#0A192F] text-white py-3 text-sm font-bold uppercase tracking-widest hover:bg-slate-800 disabled:opacity-40">
                                            {submitting ? 'Analyzing…' : 'Confirm & Run Analysis'}
                                        </button>
                                        <button data-testid="reupload-btn" onClick={() => { setPhase('upload'); setExt(null); setFile(null); }}
                                            className="w-full border border-slate-300 text-slate-700 py-2 text-xs font-bold uppercase tracking-widest hover:border-slate-800">
                                            Upload a different file
                                        </button>
                                    </div>
                                </div>
                            </aside>
                        </div>
                    )}
                </div>
            </div>
            <Footer />
            <style jsx>{`
                :global(.inp) { width: 100%; padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1; outline: none; font-size: 0.875rem; }
                :global(.inp:focus) { border-color: #0A192F; }
            `}</style>
        </main>
    );
}

function ConfBadge({ conf }: { conf: 'high' | 'medium' | 'low' }) {
    return <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 border ${CONF_BADGE[conf]}`}>{conf}</span>;
}

function Editable({ label, conf, children }: { label: string; conf: 'high' | 'medium' | 'low' | null; children: React.ReactNode }) {
    return (
        <div>
            <div className="flex items-center gap-2 mb-1.5">
                <label className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{label}</label>
                {conf && <ConfBadge conf={conf} />}
            </div>
            {children}
        </div>
    );
}
