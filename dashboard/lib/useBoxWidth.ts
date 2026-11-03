"use client";

import { useEffect, useState } from "react";

/**
 * Width in CSS pixels of the element the returned ref is attached to, kept current. A callback ref, because the
 * element may only appear later (a chart waits for data). clientWidth is not scaled by zoom.
 */
export function useBoxWidth<T extends HTMLElement>(initial = 900) {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    if (!el) return;
    const measure = () => setWidth(Math.max(280, el.clientWidth));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, width] as const;
}
