'use client';

import { useEffect, useRef, useState } from 'react';

interface Pt { type: string; x: number; y: number; floor: string; clause: string }
interface Pipe { kind: string; x1: number; y1: number; x2: number; y2: number }

interface PlanViewerProps {
    image: { base64: string; width: number; height: number };
    points: Pt[];
    pipes: Pipe[];
    riser?: { x: number; y: number };
    focusBox?: number[]; // [x0,y0,x1,y1] in image pixels — auto-zoom target
}

const POINT_STYLE: Record<string, { fill: string; stroke: string; shape: string; r: number }> = {
    extinguisher: { fill: '#D50000', stroke: '#7f0000', shape: 'circle', r: 9 },
    hose_reel: { fill: '#1565C0', stroke: '#0d3c78', shape: 'square', r: 9 },
    sprinkler: { fill: '#00C853', stroke: '#00702f', shape: 'dot', r: 4 },
    riser: { fill: '#F9A825', stroke: '#996f00', shape: 'diamond', r: 10 },
};

// The image AND the SVG overlay live inside the same transformed wrapper,
// so pan/zoom keeps markers anchored to the drawing (Part 4, point 4).
export default function PlanViewer({ image, points, pipes, riser, focusBox }: PlanViewerProps) {
    const [scale, setScale] = useState(1);
    const [tx, setTx] = useState(0);
    const [ty, setTy] = useState(0);
    const dragging = useRef<{ x: number; y: number } | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [mode, setMode] = useState<'block' | 'sheet'>(focusBox ? 'block' : 'sheet');

    // Fit-to-block: compute the initial pan/zoom so the analysed floor-plan
    // block is centred and enlarged in the viewport (Part 4 readability).
    const fitToBox = (box?: number[]) => {
        const el = containerRef.current;
        if (!el || !box) { setScale(1); setTx(0); setTy(0); return; }
        const W = el.clientWidth, H = el.clientHeight;
        const dispImgW = Math.min(W, H * (image.width / image.height));
        const dispImgH = dispImgW * (image.height / image.width);
        const k = dispImgW / image.width; // image-px → displayed-px
        const [x0, y0, x1, y1] = box;
        const pad = 1.25; // padding around the block
        const boxW = Math.max(1, (x1 - x0) * k * pad), boxH = Math.max(1, (y1 - y0) * k * pad);
        const imgLeft = (W - dispImgW) / 2, imgTop = (H - dispImgH) / 2;
        const cx = imgLeft + ((x0 + x1) / 2) * k;
        const cy = imgTop + ((y0 + y1) / 2) * k;
        const s = Math.max(1, Math.min(6, Math.min(W / boxW, H / boxH)));
        // desired translate to centre the block, then CLAMP so the scaled
        // image always covers the viewport (no dead space / one-side clipping)
        let ntx = -(cx - W / 2) * s;
        let nty = -(cy - H / 2) * s;
        const scaledW = dispImgW * s, scaledH = dispImgH * s;
        const maxX = Math.max(0, (scaledW - W) / 2), maxY = Math.max(0, (scaledH - H) / 2);
        ntx = Math.max(-maxX, Math.min(maxX, ntx));
        nty = Math.max(-maxY, Math.min(maxY, nty));
        setScale(s); setTx(ntx); setTy(nty);
    };

    useEffect(() => {
        const t = setTimeout(() => { if (focusBox && mode === 'block') fitToBox(focusBox); }, 60);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusBox, image.base64]);

    const onDown = (e: React.MouseEvent) => { dragging.current = { x: e.clientX - tx, y: e.clientY - ty }; };
    const onMove = (e: React.MouseEvent) => {
        if (!dragging.current) return;
        setTx(e.clientX - dragging.current.x);
        setTy(e.clientY - dragging.current.y);
    };
    const onUp = () => { dragging.current = null; };

    return (
        <div ref={containerRef} data-testid="plan-viewer" className="relative border border-slate-300 bg-slate-900 overflow-hidden select-none" style={{ height: 520 }}>
            {/* Zoom controls */}
            <div className="absolute top-2 right-2 z-20 flex flex-col gap-1">
                <button data-testid="viewer-zoom-in" onClick={() => setScale((s) => Math.min(6, s * 1.25))}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 font-bold border border-slate-300">+</button>
                <button data-testid="viewer-zoom-out" onClick={() => setScale((s) => Math.max(0.3, s / 1.25))}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 font-bold border border-slate-300">−</button>
                {focusBox && (
                    <button data-testid="viewer-fit-block" title="Fit to floor-plan block"
                        onClick={() => { setMode('block'); fitToBox(focusBox); }}
                        className="w-8 h-8 bg-[#0A192F] hover:bg-slate-700 text-white text-[9px] font-bold border border-slate-700">BLK</button>
                )}
                <button data-testid="viewer-reset" title="Fit whole sheet" onClick={() => { setMode('sheet'); setScale(1); setTx(0); setTy(0); }}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 text-[10px] font-bold border border-slate-300">⤢</button>
            </div>

            <div
                className="absolute inset-0 cursor-grab active:cursor-grabbing flex items-center justify-center"
                onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}
            >
                <div style={{ transform: `translate(${tx}px, ${ty}px) scale(${scale})`, transformOrigin: 'center center', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    {/* aspect-ratio box: image + SVG overlay share EXACTLY the same bounds */}
                    <div className="relative" style={{ height: '100%', aspectRatio: `${image.width} / ${image.height}`, maxWidth: '100%' }}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                            src={`data:image/png;base64,${image.base64}`}
                            alt="Uploaded building plan"
                            draggable={false}
                            className="absolute inset-0"
                            style={{ width: '100%', height: '100%', display: 'block' }}
                        />
                        <svg
                            viewBox={`0 0 ${image.width} ${image.height}`}
                            className="absolute inset-0"
                            style={{ width: '100%', height: '100%' }}
                            preserveAspectRatio="none"
                        >
                            {pipes.map((p, i) => (
                                <line key={`pipe-${i}`} x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2}
                                    stroke={p.kind === 'riser' ? '#2962FF' : '#00BFA5'}
                                    strokeWidth={p.kind === 'riser' ? 4 : 2.5}
                                    strokeDasharray={p.kind === 'riser' ? '' : '10,6'} />
                            ))}
                            {points.map((pt, i) => {
                                const st = POINT_STYLE[pt.type] || POINT_STYLE.sprinkler;
                                if (st.shape === 'square') {
                                    return <rect key={i} x={pt.x - st.r} y={pt.y - st.r} width={st.r * 2} height={st.r * 2}
                                        fill={st.fill} stroke={st.stroke} strokeWidth={2} />;
                                }
                                if (st.shape === 'diamond') {
                                    const r = st.r;
                                    return <polygon key={i} points={`${pt.x},${pt.y - r} ${pt.x + r},${pt.y} ${pt.x},${pt.y + r} ${pt.x - r},${pt.y}`}
                                        fill={st.fill} stroke={st.stroke} strokeWidth={2} />;
                                }
                                return <circle key={i} cx={pt.x} cy={pt.y} r={st.r} fill={st.fill}
                                    stroke={st.stroke} strokeWidth={st.shape === 'dot' ? 1 : 2} fillOpacity={st.shape === 'dot' ? 0.85 : 1} />;
                            })}
                        </svg>
                    </div>
                </div>
            </div>
            <div className="absolute bottom-2 left-2 z-20 text-[10px] text-white bg-black/70 px-2 py-1 font-mono rounded-sm">
                Drag to pan · +/− zoom · BLK = fit block · ⤢ = whole sheet
            </div>
        </div>
    );
}
