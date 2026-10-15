"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CushionGauge } from "@/components/CushionGauge";
import { EquityChart } from "@/components/EquityChart";
import { EventLog, PositionsPanel, SessionPanel, SignalsTable } from "@/components/Panels";
import { RiskPanel } from "@/components/RiskPanel";
import { StrategyCard } from "@/components/StrategyCard";
import { TokenGate } from "@/components/TokenGate";
import { Button } from "@/components/ui/button";
import { api, ApiError, openStream } from "@/lib/api";
import type { DeskState, Profile } from "@/lib/types";

const TOKEN_KEY = "mesa-de-micros-token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export default function Page() {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<DeskState | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ ok: boolean; text: string } | null>(null);
  const [live, setLive] = useState(false);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (t: string) => {
    try {
      const s = await api.state(t);
      setState(s);
      return true;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 503)) {
        try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
        setToken(null);
        setState(null);
        setGateError(e.status === 401 ? "Token inválido." : e.message);
      } else {
        setBanner({ ok: false, text: (e as Error).message });
      }
      return false;
    }
  }, []);

  useEffect(() => {
    const t = readToken();
    if (t) {
      setToken(t);
      void load(t);
    }
  }, [load]);

  useEffect(() => {
    if (!token) return;
    const close = openStream(
      token,
      (msg) => {
        if (msg.type === "ping" || msg.type === "hello") return;
        if (refreshTimer.current) clearTimeout(refreshTimer.current);
        refreshTimer.current = setTimeout(() => void load(token), 250);
      },
      setLive,
    );
    return close;
  }, [token, load]);

  const enter = async (t: string) => {
    setBusy("gate");
    setGateError(null);
    try {
      const s = await api.state(t);
      try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable: token lives in memory */ }
      setToken(t);
      setState(s);
    } catch (e) {
      setGateError(e instanceof ApiError && e.status === 401 ? "Token inválido." : (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const act = async (name: string, fn: () => Promise<unknown>, okText: (r: unknown) => string) => {
    if (!token) return;
    setBusy(name);
    setBanner(null);
    try {
      const r = await fn();
      setBanner({ ok: true, text: okText(r) });
      await load(token);
    } catch (e) {
      setBanner({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  if (!token || !state) {
    return <TokenGate onSubmit={(t) => void enter(t)} error={gateError} busy={busy === "gate" || (!!token && !state)} />;
  }

  const t = token;
  const counts = state.signals.reduce<Record<string, number>>((acc, s) => {
    acc[s.strategy_id] = (acc[s.strategy_id] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <main className="mx-auto max-w-7xl space-y-4 px-4 py-4 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">Mesa de micros</h1>
          <span className="rounded border border-warn/40 bg-warn/10 px-2 py-0.5 text-[11px] font-semibold tracking-wider text-warn">
            PAPER · TRADOVATE APAGADO
          </span>
          <span className={`text-[11px] ${live ? "text-good" : "text-ink-3"}`}>{live ? "● en vivo" : "○ sin stream"}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() =>
              void act("replay", () => api.replay(t), (r) => {
                const x = r as Record<string, number>;
                return `Replay: ${x.signals} señales, ${x.accepted} aceptadas, ${x.trades} operaciones. Equity ${x.equity.toFixed(2)} USD.`;
              })
            }
            disabled={busy !== null}
          >
            {busy === "replay" ? "Reproduciendo…" : "Reproducir CSV de muestra"}
          </Button>
          <Button variant="outline" onClick={() => void act("flatten", () => api.flatten(t), () => "Aplanado: sin posiciones.")}
            disabled={busy !== null}>
            Aplanar
          </Button>
          <Button variant="ghost" onClick={() => {
            try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
            setToken(null);
            setState(null);
          }}>
            Salir
          </Button>
        </div>
      </header>

      <div role="note" className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-ink-1">
        <strong className="text-warn">Aviso:</strong> estos números son los elegidos para la simulación, no las reglas
        publicadas de Apex; un trail de una cuenta de 50k suele ser 2500 (aquí: {state.profile.trail_amount}). Pega los números
        reales en «Riesgo del trail EOD». El enrutado en vivo sigue apagado: ninguna orden sale del simulador. Apex suele
        prohibir bots; confirma permiso por escrito antes de pensar en activar una ruta live.
      </div>

      {banner && (
        <div className={`rounded-md border px-3 py-2 text-xs ${banner.ok ? "border-good/40 text-good" : "border-bad/40 text-bad"}`}>
          {banner.text}
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        <CushionGauge account={state.account} profile={state.profile} />
        <EquityChart points={state.equity_curve} account={state.account} start={state.profile.starting_balance} />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        {state.strategies.map((s) => (
          <StrategyCard
            key={s.strategy_id}
            strategy={s}
            signalsCount={counts[s.strategy_id] ?? 0}
            onToggle={async (enabled) => {
              await act("strategy", () => api.updateStrategy(t, s.strategy_id, { enabled }),
                () => `${s.name}: ${enabled ? "activada" : "apagada"}`);
            }}
            onSymbols={async (symbols) => {
              await act("strategy", () => api.updateStrategy(t, s.strategy_id, { symbols }),
                () => `${s.name}: símbolos ${symbols.join(", ") || "ninguno"}`);
            }}
            onSave={async (params) => {
              await api.updateStrategy(t, s.strategy_id, { params });
              await load(t);
            }}
          />
        ))}
      </section>

      <RiskPanel
        profile={state.profile}
        account={state.account}
        meta={state.meta}
        onSave={async (changes: Partial<Profile>) => {
          await api.updateProfile(t, changes);
          await load(t);
        }}
        onReset={async () => {
          await api.reset(t);
          await load(t);
        }}
      />

      <section className="grid gap-4 lg:grid-cols-2">
        <PositionsPanel positions={state.positions} />
        <SessionPanel session={state.session} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SignalsTable signals={state.signals} />
        <EventLog events={state.events} />
      </section>

      <footer className="pb-6 text-[11px] text-ink-3">
        Datos de muestra sintéticos ({state.meta.sample_csv}), no grabación del CME · barras procesadas {state.bars_processed}
        {" · "}Tradovate {state.meta.tradovate_enabled ? "flag on (sin envío)" : "apagado"} · IB{" "}
        {state.meta.ib_enabled ? "flag on (sin envío)" : "apagado"}
      </footer>
    </main>
  );
}
