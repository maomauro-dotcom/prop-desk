import type { EventRecord, PositionView, SessionCtx, SignalRecord } from "@/lib/types";
import { etTime, px, SIDE_LABEL, signedUsd, STRATEGY_LABEL } from "@/lib/format";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

export function PositionsPanel({ positions }: { positions: PositionView[] }) {
  return (
    <Card>
      <CardHeader><CardTitle>Posiciones</CardTitle></CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <p className="text-sm text-ink-3">Sin posición abierta.</p>
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-xs num">
              <thead className="text-left text-ink-3">
                <tr><th className="py-1">Símbolo</th><th>Lado</th><th>Qty</th><th>Entrada</th><th>Stop</th><th>Objetivo</th><th className="text-right">P&L abierto</th></tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.symbol} className="border-t border-line">
                    <td className="py-1.5 font-medium">{p.symbol}</td>
                    <td className={p.side === "long" ? "text-good" : "text-bad"}>{SIDE_LABEL[p.side]}</td>
                    <td>{p.qty}</td>
                    <td>{px(p.avg_price)}</td>
                    <td>{px(p.stop)}</td>
                    <td>{px(p.target)}</td>
                    <td className={`text-right ${(p.unrealized_usd ?? 0) >= 0 ? "text-good" : "text-bad"}`}>{signedUsd(p.unrealized_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SessionPanel({ session }: { session: Record<string, SessionCtx> }) {
  const entries = Object.values(session).filter((s) => s.bars > 0);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Contexto de sesión</CardTitle>
          <CardDescription>ORB, VWAP RTH (anclado 09:30 ET) y último sweep</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-ink-3">Aún no hay barras de la sesión.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {entries.map((s) => (
              <div key={s.symbol} className="rounded-md border border-line bg-surface-2 p-3 text-xs">
                <div className="mb-2 flex items-baseline justify-between">
                  <span className="text-sm font-semibold">{s.symbol}</span>
                  <span className="num text-ink-3">{s.day} · {etTime(s.last_time, false)} ET · {s.bars} barras</span>
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 num">
                  <dt className="text-ink-3">Último</dt><dd className="text-right">{px(s.last_close)}</dd>
                  <dt className="text-ink-3">VWAP</dt><dd className="text-right">{px(s.vwap)}</dd>
                  <dt className="text-ink-3">Bandas ±2σ</dt><dd className="text-right">{px(s.vwap_lower_2sd)} / {px(s.vwap_upper_2sd)}</dd>
                  <dt className="text-ink-3">ORB {s.orb_minutes}m</dt><dd className="text-right">{px(s.orb_low)} – {px(s.orb_high)}</dd>
                  <dt className="text-ink-3">Día alto/bajo</dt><dd className="text-right">{px(s.day_high)} / {px(s.day_low)}</dd>
                  <dt className="text-ink-3">Previo alto/bajo</dt><dd className="text-right">{px(s.prev_day_high)} / {px(s.prev_day_low)}</dd>
                  <dt className="text-ink-3">ATR(14) 1m</dt><dd className="text-right">{px(s.atr)}</dd>
                  <dt className="text-ink-3">Último sweep</dt>
                  <dd className="text-right">
                    {s.last_sweep ? `${s.last_sweep.kind === "high" ? "↑" : "↓"} ${px(s.last_sweep.level)} (${s.last_sweep.source}) ${etTime(s.last_sweep.time, false)}` : "—"}
                  </dd>
                </dl>
                {s.liquidity_levels.length > 0 && (
                  <p className="mt-2 text-[11px] text-ink-3">
                    Liquidez viva: {s.liquidity_levels.slice(0, 6).map((l) => `${l.kind === "high" ? "▲" : "▼"}${px(l.price)}`).join("  ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SignalsTable({ signals }: { signals: SignalRecord[] }) {
  return (
    <Card>
      <CardHeader><CardTitle>Señales recientes</CardTitle></CardHeader>
      <CardContent>
        {signals.length === 0 ? (
          <p className="text-sm text-ink-3">Sin señales.</p>
        ) : (
          <div className="max-h-96 overflow-auto scroll-thin">
            <table className="w-full text-xs num">
              <thead className="sticky top-0 bg-surface-1 text-left text-ink-3">
                <tr><th className="py-1">Hora (ET)</th><th>Estrategia</th><th>Símbolo</th><th>Lado</th><th className="text-right">Precio</th><th className="pl-3">Estado</th></tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.id} className="border-t border-line align-top">
                    <td className="py-1.5 whitespace-nowrap">{etTime(s.timestamp)}</td>
                    <td>{STRATEGY_LABEL[s.strategy_id] ?? s.strategy_id}</td>
                    <td>{s.symbol}</td>
                    <td className={s.side === "long" ? "text-good" : "text-bad"}>{SIDE_LABEL[s.side]}</td>
                    <td className="text-right">{px(s.price)}</td>
                    <td className="pl-3">
                      {s.status === "accepted" ? (
                        <span className="text-good">✓ aceptada</span>
                      ) : (
                        <span className="text-ink-2" title={s.reason}>✕ rechazada <span className="text-ink-3">· {s.reason}</span></span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const LEVEL_CLS: Record<string, string> = { info: "text-ink-3", warning: "text-warn", error: "text-bad" };

export function EventLog({ events }: { events: EventRecord[] }) {
  return (
    <Card>
      <CardHeader><CardTitle>Registro de eventos</CardTitle></CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-ink-3">Sin eventos todavía.</p>
        ) : (
          <ul className="max-h-96 space-y-1 overflow-auto font-mono text-[11px] scroll-thin">
            {events.map((e) => (
              <li key={e.id} className="flex gap-2 border-b border-line/60 pb-1">
                <span className="shrink-0 text-ink-3">{etTime(e.ts)}</span>
                <span className={`shrink-0 w-28 truncate ${LEVEL_CLS[e.level] ?? ""}`}>{e.event}</span>
                <span className="text-ink-2">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
