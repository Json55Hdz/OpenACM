'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useTamagotchiStore } from '@/stores/tamagotchi-store';
import { TamagotchiWidget } from './tamagotchi-widget';

const WIDGET_SIZE = 200;
const FLOAT_SCALE = 90 / WIDGET_SIZE; // apparent size when floating free

// Invisible spacer that lives inside the daemon page and reports its
// screen rect to the store so GlobalTamagotchi can dock onto it.
export function TamaPlaceholder({ size }: { size: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const setTamaDockedRect = useTamagotchiStore((s) => s.setTamaDockedRect);

  const report = useCallback(() => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setTamaDockedRect({ x: r.left, y: r.top, w: r.width, h: r.height });
  }, [setTamaDockedRect]);

  useEffect(() => {
    report();
    const ro = new ResizeObserver(report);
    if (ref.current) ro.observe(ref.current);
    window.addEventListener('scroll', report, true);
    window.addEventListener('resize', report);
    return () => {
      ro.disconnect();
      window.removeEventListener('scroll', report, true);
      window.removeEventListener('resize', report);
      setTamaDockedRect(null);
    };
  }, [report, setTamaDockedRect]);

  return <div ref={ref} style={{ width: size, height: size }} aria-hidden />;
}

// Global fixed overlay: floats freely when away from daemon, docks
// into TamaPlaceholder's rect when the daemon page is mounted.
export function GlobalTamagotchi() {
  const { tamaFloatX, tamaFloatY, tamaDockedRect, setTamaFloat } =
    useTamagotchiStore();
  const isDocked = tamaDockedRect !== null;

  const [dragging, setDragging] = useState(false);
  const isDraggingRef = useRef(false);
  const dragStart = useRef({ mx: 0, my: 0, fx: 0, fy: 0 });

  // The fixed div is always WIDGET_SIZE × WIDGET_SIZE at left:0/top:0.
  // We position it with translate + scale so the content never re-renders.
  let tx: number, ty: number, scale: number;
  if (isDocked && tamaDockedRect) {
    tx = tamaDockedRect.x;
    ty = tamaDockedRect.y;
    scale = tamaDockedRect.w / WIDGET_SIZE;
  } else {
    scale = FLOAT_SCALE;
    const half = (WIDGET_SIZE * scale) / 2;
    tx = tamaFloatX - half;
    ty = tamaFloatY - half;
  }

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (isDocked) return;
      e.preventDefault();
      isDraggingRef.current = true;
      dragStart.current = {
        mx: e.clientX, my: e.clientY,
        fx: tamaFloatX, fy: tamaFloatY,
      };
      setDragging(true);
    },
    [isDocked, tamaFloatX, tamaFloatY],
  );

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return;
      const dx = e.clientX - dragStart.current.mx;
      const dy = e.clientY - dragStart.current.my;
      setTamaFloat(dragStart.current.fx + dx, dragStart.current.fy + dy);
    };
    const onUp = () => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      setDragging(false);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [setTamaFloat]);

  const transition = dragging
    ? 'none'
    : isDocked
      ? 'transform 0.38s cubic-bezier(0.4, 0, 0.2, 1)'
      : 'transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1)';

  return (
    <div
      onMouseDown={onMouseDown}
      style={{
        position: 'fixed',
        left: 0,
        top: 0,
        width: WIDGET_SIZE,
        height: WIDGET_SIZE,
        transformOrigin: 'top left',
        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
        transition,
        zIndex: 9999,
        cursor: isDocked ? 'default' : dragging ? 'grabbing' : 'grab',
        pointerEvents: isDocked ? 'none' : 'auto',
        userSelect: 'none',
        overflow: 'hidden',
      }}
    >
      <TamagotchiWidget size={WIDGET_SIZE} />
    </div>
  );
}
