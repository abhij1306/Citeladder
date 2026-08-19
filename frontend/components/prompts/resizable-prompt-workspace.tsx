'use client';

import type {
  CSSProperties,
  KeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from 'react';
import { useEffect, useRef, useState } from 'react';

const DEFAULT_RAIL_WIDTH = 240;
const MIN_RAIL_WIDTH = 208;
const MAX_RAIL_WIDTH = 400;
const MIN_CONTENT_WIDTH = 560;
const HANDLE_WIDTH = 12;

type DragState = {
  pointerId: number;
  startX: number;
  startWidth: number;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function ResizablePromptWorkspace({
  rail,
  children,
  railId,
}: Readonly<{ rail: ReactNode; children: ReactNode; railId: string }>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const widthRef = useRef(DEFAULT_RAIL_WIDTH);
  const [railWidth, setRailWidth] = useState(DEFAULT_RAIL_WIDTH);
  const [maxRailWidth, setMaxRailWidth] = useState(MAX_RAIL_WIDTH);
  const [dragging, setDragging] = useState(false);

  const bounds = () => {
    const containerWidth = containerRef.current?.getBoundingClientRect().width ?? 0;
    const responsiveMax = containerWidth
      ? containerWidth - MIN_CONTENT_WIDTH - HANDLE_WIDTH
      : MAX_RAIL_WIDTH;
    return {
      min: MIN_RAIL_WIDTH,
      max: Math.max(MIN_RAIL_WIDTH, Math.min(MAX_RAIL_WIDTH, responsiveMax)),
    };
  };

  const updateWidth = (next: number) => {
    const { min, max } = bounds();
    setMaxRailWidth(max);
    const clamped = clamp(next, min, max);
    widthRef.current = clamped;
    setRailWidth(clamped);
  };

  const restoreDocumentInteraction = () => {
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };

  const finishDrag = (pointerId?: number) => {
    const handle = handleRef.current;
    if (
      pointerId !== undefined &&
      handle?.hasPointerCapture?.(pointerId) &&
      handle.releasePointerCapture
    ) {
      handle.releasePointerCapture(pointerId);
    }
    dragRef.current = null;
    setDragging(false);
    restoreDocumentInteraction();
  };

  useEffect(() => {
    const container = containerRef.current;
    const { max } = bounds();
    setMaxRailWidth(max);
    updateWidth(widthRef.current);
    const observer =
      container && typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            const { max } = bounds();
            setMaxRailWidth(max);
            updateWidth(widthRef.current);
          })
        : null;
    if (container) observer?.observe(container);
    return () => {
      observer?.disconnect();
      restoreDocumentInteraction();
    };
    // The width helpers intentionally read live refs and DOM geometry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: widthRef.current,
    };
    setDragging(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    updateWidth(drag.startWidth + event.clientX - drag.startX);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 48 : 16;
    let next: number | null = null;
    if (event.key === 'ArrowLeft') next = widthRef.current - step;
    if (event.key === 'ArrowRight') next = widthRef.current + step;
    if (event.key === 'Home') next = bounds().min;
    if (event.key === 'End') next = bounds().max;
    if (next === null) return;
    event.preventDefault();
    updateWidth(next);
  };

  const workspaceStyle = {
    '--topic-rail-width': `${railWidth}px`,
  } as CSSProperties;

  return (
    <div
      ref={containerRef}
      className="flex min-w-0 flex-col items-start gap-3 lg:flex-row lg:gap-0"
      style={workspaceStyle}
    >
      <div className="w-full min-w-0 lg:w-[var(--topic-rail-width)] lg:shrink-0">{rail}</div>
      <div
        ref={handleRef}
        role="separator"
        aria-label="Resize topics panel"
        aria-orientation="vertical"
        aria-controls={railId}
        aria-valuemin={MIN_RAIL_WIDTH}
        aria-valuemax={maxRailWidth}
        aria-valuenow={railWidth}
        aria-describedby="topic-rail-resize-help"
        tabIndex={0}
        title="Drag to resize. Double-click to reset."
        onDoubleClick={() => updateWidth(DEFAULT_RAIL_WIDTH)}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => finishDrag(event.pointerId)}
        onPointerCancel={(event) => finishDrag(event.pointerId)}
        onLostPointerCapture={() => finishDrag()}
        className="focus-ring group relative hidden w-3 shrink-0 cursor-col-resize touch-none items-stretch justify-center self-stretch lg:flex"
        data-dragging={dragging || undefined}
      >
        <span
          className="bg-border-strong group-hover:bg-accent group-focus-visible:bg-accent group-data-[dragging]:bg-accent my-2 w-px transition-colors motion-reduce:transition-none"
          aria-hidden
        />
        <span id="topic-rail-resize-help" className="sr-only">
          Use left and right arrow keys to resize. Hold Shift for larger steps.
        </span>
      </div>
      <div className="w-full min-w-0 flex-1 lg:ps-3">{children}</div>
    </div>
  );
}
