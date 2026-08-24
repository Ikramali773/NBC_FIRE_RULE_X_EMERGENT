'use client';

import { useEffect, useState } from 'react';
import PlanViewer from '@/components/PlanViewer';
import type { AnalyzeResponse } from '@/types';

const API_URL = '';

interface PlanSession {
    planId: string | null;
    geometryAvailable: boolean;
    planReference: Record<string, unknown> | null;
    planReferenceConfidence?: string | null;
    fileName?: string;
    extractionPath?: string;
    floorLabel?: string;
}
interface Qty { equipment: string; quantity: number | null; unit: string; formula: string; source: string; sourceType: string }
interface PlacementResp {
    available: boolean;
    reason?: string;
    quantities?: Qty[];
    points?: Array<{ type: string; x: number; y: number; floor: string; clause: string }>;
    pipes?: Array<{ kind: string; x1: number; y1: number; x2: number; y2: number }>;
    riser?: { x: number; y: number };
    pageImage?: { base64: string; width: number; height: number };
    sideTable?: Array<{ equipment: string; floor: string; location: string; clause: string }>;
    legend?: Array<{ symbol: string; label: string }>;
    calibration?: Record<string, unknown>;
    sanity?: { ok: boolean; reference: string; note: string };
    overlayNote?: string | null;
    spacingM?: number; wallOffsetM?: number; pxPerM?: number;
    disclaimerPlacement?: string; disclaimerRouting?: string;
}

const LEGEND_SWATCH: Record<string, string> = {
    'circle-red': 'w-3 h-3 rounded-full bg-[#D50000]',
    'square-blue': 'w-3 h-3 bg-[#1565C0]',
    'dot-green': 'w-2 h-2 rounded-full bg-[#00C853]',
    'diamond-amber': 'w-3 h-3 rotate-45 bg-[#F9A825]',
    'line-solid-blue': 'w-4 h-0.5 bg-[#2962FF]',
    'line-dashed-teal': 'w-4 h-0.5 bg-[#00BFA5]',
};

export default function PlanSections() {
    const [session, setSession] = useState<PlanSession | null>(null);
    const [placement, setPlacement] = useState<PlacementResp | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const rawPlan = sessionStorage.getItem('firerulx_plan');
        const rawResult = sessionStorage.getItem('firerulx_result');
        if (!rawPlan || !rawResult) { setLoading(false); return; }
        let plan: PlanSession, result: AnalyzeResponse;
        try { plan = JSON.parse(rawPlan); result = JSON.parse(rawResult); } catch { setLoading(false); return; }
        setSession(plan);
        fetch(`${API_URL}/api/plan/placement`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                planId: plan.planId, floorLabel: plan.floorLabel || 'Ground Floor',
                buildingInput: result.extraction, analysis: result.analysis,
            }),
        }).then((r) => r.json()).then((d) => setPlacement(d)).catch(() => setPlacement({ available: false, reason: 'Placement service unavailable.' }))
            .finally(() => setLoading(false));
    }, []);

    if (!session) return null; // manual sessions render nothing (no regression)

    const ref = session.planReference;
    const quantities = placement?.quantities || [];

    return (
        <>
            {/* PLAN REFERENCE (Type 3) */}
            {ref && (
                <section data-testid="report-plan-reference" className="bg-white border border-slate-200">
                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                        <h2 className="text-sm font-bold text-slate-900 uppercase tracking-[0.15em]">Plan Reference — Sanctioned-Plan Metadata</h2>
                    </div>
                    <div className="p-5">
                        <p className="text-[11px] text-slate-500 mb-3">Administrative / traceability data extracted from the plan. Reference only — never used in any compliance calculation.</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2">
                            {Object.entries(ref).filter(([k]) => k !== 'earlier_approved_case').map(([k, v]) => (
                                <div key={k} className="flex justify-between gap-2 border-b border-slate-100 pb-1 text-xs">
                                    <span className="text-[10px] uppercase tracking-wider text-slate-500">{k.replace(/_/g, ' ')}</span>
                                    <span className="font-mono text-slate-800 text-right break-all">{String(v)}</span>
                                </div>
                            ))}
                        </div>
                        {ref.earlier_approved_case ? (
                            <div className="mt-3 pt-3 border-t border-slate-200">
                                <p className="text-[10px] uppercase tracking-wider text-[#B7791F] font-bold mb-1">Earlier approved case (linked reference)</p>
                                <p className="font-mono text-xs text-slate-700 break-all">{String((ref.earlier_approved_case as Record<string, unknown>).raw)}</p>
                            </div>
                        ) : null}
                    </div>
                </section>
            )}

            {/* SUGGESTED EQUIPMENT QUANTITIES */}
            <section data-testid="report-equipment-quantities" className="bg-white border border-slate-200">
                <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                    <h2 className="text-sm font-bold text-slate-900 uppercase tracking-[0.15em]">Suggested Equipment Quantities</h2>
                </div>
                <div className="p-5">
                    <div className="mb-3 px-3 py-2 bg-[#FFFDE7] border border-[#FFF59D] text-[11px] text-[#8a6d00] leading-relaxed">
                        Suggested quantities are advisory. Lines marked &quot;Estimated per …&quot; use industry-standard assumptions not explicit in NBC Part 4 and must be confirmed by a licensed fire protection engineer.
                    </div>
                    {loading ? <p className="text-xs text-slate-400">Computing…</p> : quantities.length === 0 ? (
                        <p className="text-xs text-slate-400">No equipment quantities were triggered for this building.</p>
                    ) : (
                        <div className="border border-slate-200 overflow-x-auto">
                            <table className="w-full text-xs" data-testid="equipment-quantities-table">
                                <thead>
                                    <tr className="bg-[#0A192F] text-white text-[10px] uppercase tracking-widest">
                                        <th className="text-left px-3 py-2">Equipment</th>
                                        <th className="text-right px-3 py-2 w-24">Qty</th>
                                        <th className="text-left px-3 py-2">Formula used</th>
                                        <th className="text-left px-3 py-2 w-64">Source</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {quantities.map((q, i) => (
                                        <tr key={i} className="border-t border-slate-100">
                                            <td className="px-3 py-2 font-semibold text-slate-900">{q.equipment}</td>
                                            <td className="px-3 py-2 text-right font-mono">{q.quantity ?? '—'} {q.unit}</td>
                                            <td className="px-3 py-2 text-slate-600">{q.formula}</td>
                                            <td className="px-3 py-2">
                                                <span className={`text-[10px] font-semibold px-1.5 py-0.5 border ${q.sourceType === 'nbc' ? 'bg-[#E8F5E9] text-[#00863b] border-[#C8E6C9]' : 'bg-[#FFF3E0] text-[#B7791F] border-[#FFE0B2]'}`}>{q.source}</span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </section>

            {/* SUGGESTED EQUIPMENT PLACEMENT */}
            <section data-testid="report-equipment-placement" className="bg-white border border-slate-200">
                <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                    <h2 className="text-sm font-bold text-slate-900 uppercase tracking-[0.15em]">Suggested Equipment Placement (on the plan)</h2>
                </div>
                <div className="p-5">
                    {loading ? (
                        <p className="text-xs text-slate-400">Preparing placement…</p>
                    ) : !placement?.available ? (
                        <div data-testid="placement-unavailable" className="px-4 py-3 bg-[#E3F2FD] border border-[#BBDEFB] text-xs text-[#1565C0] leading-relaxed">
                            <span className="font-bold uppercase tracking-wider">Placement not available — </span>{placement?.reason || 'This analysis did not originate from an uploaded plan with usable geometry.'}
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {/* calibration + sanity strip */}
                            <div className="flex flex-wrap gap-2 text-[11px]">
                                <span className="font-mono px-2 py-1 border border-slate-200 bg-slate-50">Scale: {String(placement.calibration?.scaleNote ?? '—')} · {String(placement.calibration?.confidence)} confidence ({String(placement.calibration?.source)})</span>
                                <span className="font-mono px-2 py-1 border border-slate-200 bg-slate-50">Grid: {placement.spacingM} m · wall offset {placement.wallOffsetM} m</span>
                                <span className={`font-mono px-2 py-1 border ${placement.sanity?.ok ? 'bg-[#E8F5E9] text-[#00863b] border-[#C8E6C9]' : 'bg-[#FFEBEE] text-[#D50000] border-[#FFCDD2]'}`}>{placement.sanity?.ok ? 'Spacing sanity-check: OK' : 'Spacing deviation flagged'}</span>
                            </div>
                            {placement.calibration?.conflict ? (
                                <div className="px-3 py-2 bg-[#FFEBEE] border border-[#FFCDD2] text-[11px] text-[#D50000]">Scale conflict: {String(placement.calibration.conflict)}</div>
                            ) : null}

                            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                                <div className="lg:col-span-2">
                                    {placement.pageImage && (
                                        <PlanViewer image={placement.pageImage} points={placement.points || []} pipes={placement.pipes || []} riser={placement.riser} />
                                    )}
                                    {placement.overlayNote ? (
                                        <p data-testid="placement-overlay-note" className="mt-2 text-[11px] text-slate-600 bg-slate-50 border border-slate-200 px-3 py-2 leading-relaxed">
                                            {placement.overlayNote}
                                        </p>
                                    ) : null}
                                    {/* Legend */}
                                    <div className="mt-3 border border-slate-200 p-3" data-testid="placement-legend">
                                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Legend</p>
                                        <div className="flex flex-wrap gap-x-5 gap-y-2">
                                            {(placement.legend || []).map((l, i) => (
                                                <div key={i} className="flex items-center gap-2 text-[11px] text-slate-700">
                                                    <span className={LEGEND_SWATCH[l.symbol] || 'w-3 h-3 bg-slate-400'} />{l.label}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>

                                {/* Side table */}
                                <div className="border border-slate-200 overflow-hidden">
                                    <div className="px-3 py-2 bg-slate-100 text-[10px] uppercase tracking-widest text-slate-500 font-bold">Suggested positions</div>
                                    <div className="max-h-[520px] overflow-y-auto">
                                        <table className="w-full text-[11px]" data-testid="placement-side-table">
                                            <thead>
                                                <tr className="text-[9px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
                                                    <th className="text-left px-2 py-1.5">Equipment</th>
                                                    <th className="text-left px-2 py-1.5">Location</th>
                                                    <th className="text-left px-2 py-1.5">Rule</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {(placement.sideTable || []).map((r, i) => (
                                                    <tr key={i} className="border-b border-slate-100">
                                                        <td className="px-2 py-1.5 font-semibold text-slate-800">{r.equipment}</td>
                                                        <td className="px-2 py-1.5 text-slate-600">{r.location}</td>
                                                        <td className="px-2 py-1.5 font-mono text-[#2962FF]">{r.clause}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-1.5">
                                <p className="text-[11px] text-[#B7791F] bg-[#FFFDE7] border border-[#FFF59D] px-3 py-2">{placement.disclaimerPlacement}</p>
                                <p className="text-[11px] text-[#1565C0] bg-[#E3F2FD] border border-[#BBDEFB] px-3 py-2">{placement.disclaimerRouting}</p>
                            </div>
                        </div>
                    )}
                </div>
            </section>
        </>
    );
}
