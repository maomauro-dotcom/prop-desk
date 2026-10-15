import type { Account, Profile } from "@/lib/types";
import { usd } from "@/lib/format";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

function arc(cx: number, cy: number, r: number, from: number, to: number) {
  // angles in [0,1] along a 180° arc, left to right
  const a0 = Math.PI * (1 - from);
  const a1 = Math.PI * (1 - to);
  const x0 = cx + r * Math.cos(a0);
  const y0 = cy - r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1);
  const y1 = cy - r * Math.sin(a1);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${to - from > 0.5 ? 1 : 0} 1 ${x1} ${y1}`;
}

export function CushionGauge({ account, profile }: { account: Account; profile: Profile }) {
  const ratio = Math.max(0, Math.min(1, account.cushion_usd / profile.trail_amount));
  const floorRatio = profile.min_cushion_pct_of_trail;
  const state = account.breached
    ? { label: "Cuenta tocó el piso", cls: "text-bad", stroke: "#e66767" }
    : ratio < floorRatio
      ? { label: "Bajo el piso del colchón: sin entradas", cls: "text-bad", stroke: "#e66767" }
      : ratio < floorRatio + 0.2
        ? { label: "Colchón justo", cls: "text-warn", stroke: "#eda100" }
        : { label: "Colchón sano", cls: "text-good", stroke: "#1baf7a" };
  const cushionFloorEquity = account.trail_floor + account.cushion_floor_usd;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Colchón hasta el trail</CardTitle>
          <CardDescription>Equity − piso del trail EOD</CardDescription>
        </div>
        <span className={`text-xs font-medium ${state.cls}`}>● {state.label}</span>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-[200px_1fr]">
        <svg viewBox="0 0 200 118" className="mx-auto w-full max-w-[220px]" role="img"
          aria-label={`Colchón ${account.cushion_usd} USD, ${account.cushion_pct}% del trail`}>
          <path d={arc(100, 100, 80, 0, 1)} stroke="#2e2e2b" strokeWidth="14" fill="none" strokeLinecap="round" />
          {ratio > 0.001 && (
            <path d={arc(100, 100, 80, 0, ratio)} stroke={state.stroke} strokeWidth="14" fill="none" strokeLinecap="round" />
          )}
          {/* floor tick: minimum cushion to open trades */}
          {(() => {
            const a = Math.PI * (1 - floorRatio);
            return (
              <line x1={100 + 64 * Math.cos(a)} y1={100 - 64 * Math.sin(a)} x2={100 + 96 * Math.cos(a)} y2={100 - 96 * Math.sin(a)}
                stroke="#f0efec" strokeWidth="2" />
            );
          })()}
          <text x="100" y="86" textAnchor="middle" className="fill-ink-1 num" fontSize="22" fontWeight="600">
            {account.cushion_pct.toFixed(0)}%
          </text>
          <text x="100" y="106" textAnchor="middle" className="fill-ink-2 num" fontSize="11">
            {usd(account.cushion_usd)}
          </text>
        </svg>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <dt className="text-ink-3">Colchón</dt>
          <dd className="num text-right">{usd(account.cushion_usd)} · {account.cushion_pct.toFixed(1)} %</dd>
          <dt className="text-ink-3">Piso del trail</dt>
          <dd className="num text-right">{usd(account.trail_floor)}</dd>
          <dt className="text-ink-3">Piso del colchón</dt>
          <dd className="num text-right" title={`No se abre nada con equity por debajo de ${usd(cushionFloorEquity)}`}>
            {usd(account.cushion_floor_usd)} ({(floorRatio * 100).toFixed(0)} % del trail)
          </dd>
          <dt className="text-ink-3">Pico EOD</dt>
          <dd className="num text-right">{usd(account.peak_eod_balance)}</dd>
          <dt className="text-ink-3">Estado del trail</dt>
          <dd className={`text-right font-medium ${account.trail_locked ? "text-good" : "text-ink-1"}`}>
            {account.trail_locked ? "bloqueado" : "sigue al pico"}
          </dd>
          <dt className="text-ink-3">Riesgo máx. por operación</dt>
          <dd className="num text-right">{usd(account.max_risk_per_trade_usd)}</dd>
        </dl>
      </CardContent>
    </Card>
  );
}
