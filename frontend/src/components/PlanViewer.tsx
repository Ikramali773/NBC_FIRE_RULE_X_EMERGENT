'use client';

import { useRef, useState } from 'react';

interface Pt { type: string; x: number; y: number; floor: string; clause: string }
interface Pipe { kind: string; x1: number; y1: number; x2: number; y2: number }

interface PlanViewerProps {
    image: { base64: string; width: number; height: number };
    points: Pt[];
    pipes: Pipe[];
    riser?: { x: number; y: number };
}

const POINT_STYLE: Record<string, { fill: string; stroke: string; shape: string; r: number }> = {
    extinguisher: { fill: '#D50000', stroke: '#7f0000', shape: 'circle', r: 9 },
    hose_reel: { fill: '#1565C0', stroke: '#0d3c78', shape: 'square', r: 9 },
    sprinkler: { fill: '#00C853', stroke: '#00702f', shape: 'dot', r: 4 },
    riser: { fill: '#F9A825', stroke: '#996f00', shape: 'diamond', r: 10 },
};

// The image AND the SVG overlay live inside the same transformed wrapper,
// so pan/zoom keeps markers anchored to the drawing (Part 4, point 4).
export default function PlanViewer({ image, points, pipes, riser }: PlanViewerProps) {
    const [scale, setScale] = useState(1);
    const [tx, setTx] = useState(0);
    const [ty, setTy] = useState(0);
    const dragging = useRef<{ x: number; y: number } | null>(null);

    const onDown = (e: React.MouseEvent) => { dragging.current = { x: e.clientX - tx, y: e.clientY - ty }; };
    const onMove = (e: React.MouseEvent) => {
        if (!dragging.current) return;
        setTx(e.clientX - dragging.current.x);
        setTy(e.clientY - dragging.current.y);
    };
    const onUp = () => { dragging.current = null; };

    return (
        <div data-testid="plan-viewer" className="relative border border-slate-300 bg-slate-900 overflow-hidden select-none" style={{ height: 520 }}>
            {/* Zoom controls */}
            <div className="absolute top-2 right-2 z-20 flex flex-col gap-1">
                <button data-testid="viewer-zoom-in" onClick={() => setScale((s) => Math.min(6, s * 1.25))}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 font-bold border border-slate-300">+</button>
                <button data-testid="viewer-zoom-out" onClick={() => setScale((s) => Math.max(0.3, s / 1.25))}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 font-bold border border-slate-300">−</button>
                <button data-testid="viewer-reset" onClick={() => { setScale(1); setTx(0); setTy(0); }}
                    className="w-8 h-8 bg-white/90 hover:bg-white text-slate-900 text-[10px] font-bold border border-slate-300">⟳</button>
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
            <div className="absolute bottom-2 left-2 z-20 text-[10px] text-white/70 bg-black/40 px-2 py-1 font-mono">
                Drag to pan · +/− to zoom · markers stay anchored to the drawing
            </div>
        </div>
    );
}
