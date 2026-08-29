import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DEFAULT_PANE_WIDTH,
  MAX_PANE_WIDTH,
  MIN_PANE_WIDTH,
  useResizablePane,
} from './use-resizable-pane';

describe('useResizablePane', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts at the width the pane had before it was resizable', () => {
    const { result } = renderHook(() => useResizablePane());
    expect(result.current.width).toBe(DEFAULT_PANE_WIDTH);
  });

  it('clamps a drag to the pane bounds instead of collapsing either side', () => {
    const { result } = renderHook(() => useResizablePane());
    act(() => result.current.beginDrag(0));
    act(() => result.current.dragTo(-500));
    expect(result.current.width).toBe(MIN_PANE_WIDTH);
    act(() => result.current.dragTo(99_999));
    expect(result.current.width).toBe(MAX_PANE_WIDTH);
  });

  it('moves by the pointer delta, and keeps the width the drag ended on', () => {
    const { result } = renderHook(() => useResizablePane());
    act(() => result.current.beginDrag(400));
    act(() => result.current.dragTo(460));
    expect(result.current.width).toBe(DEFAULT_PANE_WIDTH + 60);
    expect(result.current.dragging).toBe(true);
    act(() => result.current.endDrag());
    expect(result.current.dragging).toBe(false);
    expect(renderHook(() => useResizablePane()).result.current.width).toBe(DEFAULT_PANE_WIDTH + 60);
  });

  it('keeps the landed width in memory when browser storage rejects writes', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage is blocked', 'SecurityError');
    });
    const { result } = renderHook(() => useResizablePane());

    act(() => result.current.beginDrag(400));
    act(() => result.current.dragTo(460));
    act(() => result.current.endDrag());

    expect(result.current.dragging).toBe(false);
    expect(result.current.width).toBe(DEFAULT_PANE_WIDTH + 60);

    setItem.mockRestore();
    act(() => result.current.reset());
  });

  it('nudges by keyboard and remembers the result', () => {
    const { result } = renderHook(() => useResizablePane());
    act(() => result.current.nudge(result.current.keyboardStep));
    expect(result.current.width).toBe(DEFAULT_PANE_WIDTH + result.current.keyboardStep);

    // A second hook — a fresh mount — restores what the first one stored.
    const restored = renderHook(() => useResizablePane());
    expect(restored.result.current.width).toBe(DEFAULT_PANE_WIDTH + result.current.keyboardStep);
  });

  it('restores the default, and persists that too', () => {
    const { result } = renderHook(() => useResizablePane());
    act(() => result.current.nudge(64));
    act(() => result.current.reset());
    expect(result.current.width).toBe(DEFAULT_PANE_WIDTH);
    expect(renderHook(() => useResizablePane()).result.current.width).toBe(DEFAULT_PANE_WIDTH);
  });

  it('ignores a stored width that is out of bounds or not a number', () => {
    window.localStorage.setItem('citeladder:commerce:catalog-pane-width', 'not-a-width');
    expect(renderHook(() => useResizablePane()).result.current.width).toBe(DEFAULT_PANE_WIDTH);
    window.localStorage.setItem('citeladder:commerce:catalog-pane-width', '99999');
    expect(renderHook(() => useResizablePane()).result.current.width).toBe(MAX_PANE_WIDTH);
  });
});
