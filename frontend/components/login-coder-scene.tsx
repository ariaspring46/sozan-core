"use client";

const CODE_LINES = [
  "shop.build({ brand, style })",
  "await factory.start(prompt)",
  "dns.publish(slug)",
  "inbox.sync(telegram)",
  "studio.compose(campaign)",
];

export function LoginCoderScene() {
  return (
    <div className="login-coder-scene pointer-events-none fixed inset-0 overflow-hidden" aria-hidden>
      <div className="login-code-drift login-code-drift-a absolute right-[6%] top-[8%] rounded-lg border border-line/40 bg-paper/15 px-3 py-2 font-mono text-[10px] text-warm/70 sm:text-xs">
        {CODE_LINES[0]}
      </div>
      <div className="login-code-drift login-code-drift-b absolute left-[5%] top-[14%] rounded-lg border border-line/30 bg-paper/10 px-3 py-2 font-mono text-[10px] text-muted/80 sm:text-xs">
        {CODE_LINES[1]}
      </div>
      <div className="login-code-drift login-code-drift-c absolute right-[8%] bottom-[14%] rounded-lg border border-line/25 bg-paper/10 px-3 py-2 font-mono text-[10px] text-accent/50 sm:text-xs">
        {CODE_LINES[2]}
      </div>
      <div className="login-code-drift login-code-drift-d absolute left-[7%] bottom-[10%] rounded-lg border border-line/25 bg-paper/10 px-3 py-2 font-mono text-[10px] text-warm/60 sm:text-xs">
        {CODE_LINES[3]}
      </div>
      <div className="login-code-drift login-code-drift-e absolute right-[22%] top-[22%] hidden rounded-lg border border-line/20 bg-paper/10 px-3 py-2 font-mono text-[10px] text-muted/70 sm:block sm:text-xs">
        {CODE_LINES[4]}
      </div>

      <div className="login-robot-float absolute left-1/2 top-3 w-[min(58vw,16rem)] -translate-x-1/2 sm:top-5 sm:w-[min(38vw,18rem)]">
        <svg viewBox="0 0 280 200" className="h-auto w-full" fill="none" xmlns="http://www.w3.org/2000/svg">
          <ellipse cx="140" cy="188" rx="88" ry="10" fill="rgb(196 92 38 / 14%)" />
          <rect x="78" y="118" width="124" height="58" rx="10" fill="#3A3A40" stroke="#52525A" strokeWidth="1.5" />
          <rect x="88" y="128" width="104" height="38" rx="6" fill="#2F2F33" stroke="#C45C26" strokeOpacity="0.4" />
          <g className="login-code-typing">
            <text x="96" y="146" fill="#E8A87C" fontSize="9" fontFamily="ui-monospace, monospace" opacity="0.9">
              build_shop()
            </text>
            <rect x="168" y="138" width="2" height="12" fill="#C45C26" className="login-cursor-blink" />
          </g>
          <rect x="108" y="92" width="64" height="32" rx="8" fill="#3A3A40" stroke="#52525A" />
          <circle cx="124" cy="106" r="5" fill="#C45C26" className="login-eye-pulse" />
          <circle cx="156" cy="106" r="5" fill="#C45C26" className="login-eye-pulse" />
          <rect x="132" y="118" width="16" height="6" rx="3" fill="#52525A" />
          <rect x="118" y="78" width="44" height="10" rx="4" fill="#52525A" />
          <circle cx="140" cy="72" r="4" fill="#E8A87C" className="login-antenna-pulse" />
          <path d="M64 132 L78 132 L78 148" stroke="#52525A" strokeWidth="8" strokeLinecap="round" />
          <path d="M216 132 L202 132 L202 148" stroke="#52525A" strokeWidth="8" strokeLinecap="round" />
          <rect x="52" y="124" width="18" height="10" rx="4" fill="#3A3A40" stroke="#52525A" />
          <rect x="210" y="124" width="18" height="10" rx="4" fill="#3A3A40" stroke="#52525A" />
        </svg>
      </div>
    </div>
  );
}
