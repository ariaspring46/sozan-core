"use client";

import { MutableRefObject, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

type Rgb = [number, number, number];

/** نقطه‌ها با مارپیچ فیبوناچی روی کره پخش می‌شوند تا هیچ‌جا خوشه نشوند. */
function spherePoints(count: number) {
  const golden = Math.PI * (1 + Math.sqrt(5));
  return Array.from({ length: count }, (_, i) => ({
    theta: Math.acos(1 - (2 * (i + 0.5)) / count),
    phi: golden * i,
  }));
}

/** رنگ‌های گوی از توکن‌های تم (`--orb-front` جلو، `--orb-back` پشت کره)؛ رنگ تازه‌ای در کد نیست. */
function tone(el: Element, name: string): Rgb {
  const style = getComputedStyle(el);
  const raw = (style.getPropertyValue(name) || style.getPropertyValue("--c-accent")).trim();
  const parts = raw.split(/\s+/).map(Number);
  return parts.length === 3 && parts.every((n) => Number.isFinite(n)) ? (parts as Rgb) : [196, 92, 38];
}

function reducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * گوی نقطه‌ای سوزان: کره‌ای از نقطه‌های مسی که آرام می‌چرخد و نفس می‌کشد؛ نقطه‌های جلو روشن‌تر و درشت‌ترند.
 * `busy` تندترش می‌کند (دارد فکر می‌کند)؛ `level` (۰ تا ۱، مثلاً بلندی صدای میکروفون) بزرگ و پررنگش می‌کند.
 * با «کاهش حرکت» نمی‌چرخد و بیرون از دید صفحه چیزی نمی‌کشد.
 */
export function SozanOrb({
  size = 120,
  busy = false,
  still = false,
  level,
  className,
}: {
  size?: number;
  busy?: boolean;
  /** فقط یک بار کشیده شود (آواتار کنار پیام‌ها): بی‌حلقهٔ انیمیشن. */
  still?: boolean;
  level?: MutableRefObject<number>;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const points = spherePoints(Math.round(Math.min(560, Math.max(110, size * 3.1))));
    let front = tone(canvas, "--orb-front");
    let back = tone(canvas, "--orb-back");
    const frozen = still || reducedMotion();
    const tilt = 0.42;
    const sinT = Math.sin(tilt);
    const cosT = Math.cos(tilt);
    let visible = true;
    let frame = 0;
    let angle = 0.6;
    let shown = 0;
    let drawnLevel = -1;
    let last = performance.now();
    let lastDraw = 0;
    // نقطه‌ها بر اساس عمق در چند دسته کشیده می‌شوند: چند fill در هر فریم به‌جای صدها.
    const BUCKETS = 9;
    const xs = new Float32Array(points.length);
    const ys = new Float32Array(points.length);
    const ds = new Float32Array(points.length);

    const draw = (now: number) => {
      const target = Math.max(0, Math.min(1, level?.current || 0));
      shown += (target - shown) * 0.22;
      const breathe = frozen ? 0 : 0.018 * Math.sin(now / 1500) + (busyRef.current ? 0.035 * Math.sin(now / 240) : 0);
      const half = canvas.width / 2;
      const radius = half * 0.7 * (1 + 0.24 * shown + breathe);
      const dot = dpr * Math.max(0.85, size / 105);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      points.forEach((p, i) => {
        const phi = p.phi + angle;
        const sx = Math.sin(p.theta) * Math.cos(phi);
        const sy = Math.cos(p.theta);
        const sz = Math.sin(p.theta) * Math.sin(phi);
        // کمی کج تا حس سه‌بعدی بدهد
        xs[i] = half + sx * radius;
        ys[i] = half + (sy * cosT - sz * sinT) * radius;
        ds[i] = (sy * sinT + sz * cosT + 1) / 2;
      });
      for (let k = 0; k < BUCKETS; k++) {
        const depth = (k + 0.5) / BUCKETS;
        const mix = depth * depth;
        const r = Math.round(back[0] + (front[0] - back[0]) * mix);
        const g = Math.round(back[1] + (front[1] - back[1]) * mix);
        const b = Math.round(back[2] + (front[2] - back[2]) * mix);
        const size = dot * (0.45 + 0.85 * depth) * (1 + 0.55 * shown);
        ctx.fillStyle = `rgba(${r},${g},${b},${0.14 + 0.86 * depth})`;
        ctx.beginPath();
        for (let i = 0; i < points.length; i++) {
          if (Math.min(BUCKETS - 1, Math.floor(ds[i] * BUCKETS)) !== k) continue;
          ctx.moveTo(xs[i] + size, ys[i]);
          ctx.arc(xs[i], ys[i], size, 0, Math.PI * 2);
        }
        ctx.fill();
      }
      drawnLevel = target;
    };

    const tick = (now: number) => {
      frame = window.requestAnimationFrame(tick);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (!visible || document.hidden) return;
      if (frozen) {
        if (Math.abs((level?.current || 0) - drawnLevel) > 0.01) draw(now);
        return;
      }
      angle += dt * (busyRef.current ? 1.1 : 0.24) * (1 + 1.5 * shown);
      // حرکت آرام است؛ ۳۰ فریم در ثانیه کافی است و باتری گوشی را نگه می‌دارد.
      if (now - lastDraw < 30) return;
      lastDraw = now;
      draw(now);
    };

    // عوض شدن تم (روشن/تیره) رنگ گوی را هم عوض می‌کند.
    const retone = () => {
      front = tone(canvas, "--orb-front");
      back = tone(canvas, "--orb-back");
      draw(performance.now());
    };
    const themeWatch = new MutationObserver(retone);
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const scheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    scheme?.addEventListener?.("change", retone);

    const watch =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((rows) => {
            visible = rows.some((row) => row.isIntersecting);
          });
    draw(last);
    if (!still) {
      watch?.observe(canvas);
      frame = window.requestAnimationFrame(tick);
    }
    return () => {
      window.cancelAnimationFrame(frame);
      watch?.disconnect();
      themeWatch.disconnect();
      scheme?.removeEventListener?.("change", retone);
    };
  }, [size, level, still]);

  return <canvas ref={canvasRef} aria-hidden className={cn("pointer-events-none block", className)} style={{ width: size, height: size }} />;
}
