"use client";

import { useEffect, useState } from "react";
import type { Account, Meta, Profile } from "@/lib/types";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";

type NumField = {
  key: keyof Profile;
  label: string;
  pct?: boolean;
  int?: boolean;
};

const FIELDS: NumField[] = [
  { key: "starting_balance", label: "Saldo inicial (USD)" },
  { key: "trail_amount", label: "Trail EOD (USD)" },
  { key: "trail_lock_level", label: "El piso se bloquea en (USD)" },
  { key: "daily_loss_limit", label: "Pérdida diaria máx. (USD)" },
  { key: "default_contracts", label: "Tamaño por defecto (micros)", int: true },
  { key: "max_contracts", label: "Tope total (micros, máx. 2)", int: true },
  { key: "max_risk_pct_of_cushion", label: "Riesgo por operación (% del colchón)", pct: true },
  { key: "min_cushion_pct_of_trail", label: "Colchón mínimo para abrir (% del trail)", pct: true },
  { key: "max_entries_per_day", label: "Entradas nuevas por día", int: true },
];

type Draft = Record<string, string>;

function toDraft(p: Profile): Draft {
  const d: Draft = {};
  for (const f of FIELDS) {
    const v = p[f.key] as number;
    d[f.key] = f.pct ? String(+(v * 100).toFixed(4)) : String(v);
  }
  d.flatten_time = p.flatten_time;
  return d;
}

export function RiskPanel({
  profile,
  account,
  meta,
  onSave,
  onReset,
}: {
  profile: Profile;
  account: Account;
  meta: Meta;
  onSave: (changes: Partial<Profile>) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(profile));
  const [claude, setClaude] = useState(profile.claude_filter_enabled);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify(profile);
  useEffect(() => {
    setDraft(toDraft(profile));
    setClaude(profile.claude_filter_enabled);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    const changes: Record<string, unknown> = { claude_filter_enabled: claude, flatten_time: draft.flatten_time };
    for (const f of FIELDS) {
      const n = Number(draft[f.key]);
      if (!Number.isFinite(n)) {
        setMsg({ ok: false, text: `${f.label}: número inválido` });
        return;
      }
      changes[f.key] = f.pct ? n / 100 : f.int ? Math.trunc(n) : n;
    }
    setBusy(true);
    try {
      await onSave(changes as Partial<Profile>);
      setMsg({ ok: true, text: "Reglas guardadas. Saldo inicial nuevo se aplica al reiniciar." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Riesgo del trail EOD</CardTitle>
          <CardDescription>
            Perfil <code className="font-mono">{profile.name}</code> · pega aquí los números reales de tu cuenta
          </CardDescription>
        </div>
        <span className="num text-xs text-ink-2">
          Entradas hoy {account.entries_today}/{account.max_entries_per_day}
          {account.day_lock_reason && <span className="ml-2 text-bad">día bloqueado: {account.day_lock_reason}</span>}
        </span>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {FIELDS.map((f) => (
            <label key={f.key} className="flex flex-col gap-1 text-[11px] text-ink-2">
              {f.label}
              <Input inputMode="decimal" value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
            </label>
          ))}
          <label className="flex flex-col gap-1 text-[11px] text-ink-2">
            Flatten forzado (hora ET)
            <Input value={draft.flatten_time} onChange={(e) => setDraft({ ...draft, flatten_time: e.target.value })} />
          </label>
          <div className="flex flex-col gap-1 text-[11px] text-ink-2">
            Overnight
            <span className="flex h-8 items-center text-sm text-ink-1">No (siempre plano a la hora de flatten)</span>
          </div>
          <div className="flex flex-col gap-1 text-[11px] text-ink-2">
            Regla de consistencia
            <span className="flex h-8 items-center text-sm text-ink-1">Sin regla de consistencia</span>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex items-start gap-3 rounded-md border border-line bg-surface-2 p-3">
            <Switch checked={claude} onCheckedChange={setClaude} label="Filtro Claude" id="claude-filter" />
            <div className="text-xs">
              <label htmlFor="claude-filter" className="font-medium text-ink-1">Filtro Claude</label>
              <p className="text-ink-3">
                Revisa cada señal antes de entrar ({meta.claude_transport}, {meta.claude_model}). Si falta la clave, hay
                timeout o error, la señal se rechaza.
                {!meta.claude_key_present && <span className="text-warn"> ANTHROPIC_API_KEY no está configurada: con el filtro activo se rechazará todo.</span>}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-md border border-line bg-surface-2 p-3">
            <Switch checked={profile.block_minis} onCheckedChange={() => undefined} disabled label="Minis bloqueados" id="minis" />
            <div className="text-xs">
              <label htmlFor="minis" className="font-medium text-ink-1">Minis bloqueados</label>
              <p className="text-ink-3">NQ y ES quedan bloqueados en esta versión: solo micros MNQ/MES, tope duro de 2.</p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className={`text-xs ${msg ? (msg.ok ? "text-good" : "text-bad") : "text-ink-3"}`}>{msg?.text ?? ""}</span>
          <div className="flex flex-wrap gap-2">
            {confirmReset ? (
              <>
                <span className="self-center text-xs text-warn">Se borra la cuenta paper. ¿Seguro?</span>
                <Button size="sm" variant="ghost" onClick={() => setConfirmReset(false)}>Cancelar</Button>
                <Button size="sm" variant="danger" disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await onReset();
                      setMsg({ ok: true, text: "Simulación reiniciada" });
                    } catch (e) {
                      setMsg({ ok: false, text: (e as Error).message });
                    } finally {
                      setBusy(false);
                      setConfirmReset(false);
                    }
                  }}>
                  Sí, reiniciar
                </Button>
              </>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setConfirmReset(true)}>Reiniciar simulación</Button>
            )}
            <Button size="sm" onClick={() => void save()} disabled={busy}>Guardar reglas</Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
