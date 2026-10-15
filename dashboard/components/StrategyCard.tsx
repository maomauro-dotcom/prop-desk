"use client";

import { useEffect, useState } from "react";
import type { ParamSpec, StrategyInfo } from "@/lib/types";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";

const SYMBOLS = ["MNQ", "MES"];

type Draft = Record<string, string | boolean>;

function toDraft(s: StrategyInfo): Draft {
  const d: Draft = {};
  for (const p of s.param_specs) d[p.name] = typeof p.value === "boolean" ? p.value : String(p.value);
  return d;
}

function parse(spec: ParamSpec, raw: string | boolean): unknown {
  if (spec.type === "bool") return raw;
  if (spec.type === "int") return Number.parseInt(String(raw), 10);
  if (spec.type === "float") return Number.parseFloat(String(raw));
  return raw;
}

export function StrategyCard({
  strategy,
  signalsCount,
  onToggle,
  onSymbols,
  onSave,
}: {
  strategy: StrategyInfo;
  signalsCount: number;
  onToggle: (enabled: boolean) => Promise<void>;
  onSymbols: (symbols: string[]) => Promise<void>;
  onSave: (params: Record<string, unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(strategy));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const paramsKey = JSON.stringify(strategy.params);
  useEffect(() => setDraft(toDraft(strategy)), [paramsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    const params: Record<string, unknown> = {};
    for (const spec of strategy.param_specs) {
      const v = parse(spec, draft[spec.name]);
      if (typeof v === "number" && Number.isNaN(v)) {
        setMsg({ ok: false, text: `${spec.label}: número inválido` });
        return;
      }
      params[spec.name] = v;
    }
    setBusy(true);
    try {
      await onSave(params);
      setMsg({ ok: true, text: "Parámetros guardados" });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div>
          <CardTitle>{strategy.name}</CardTitle>
          <CardDescription>
            <code className="font-mono">{strategy.strategy_id}</code> · {signalsCount} señales recientes
          </CardDescription>
        </div>
        <Switch checked={strategy.enabled} onCheckedChange={(v) => void onToggle(v)} label={`Activar ${strategy.name}`} />
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex gap-4 text-sm">
          {SYMBOLS.map((sym) => (
            <label key={sym} className="flex items-center gap-2">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[#3987e5]"
                checked={strategy.symbols.includes(sym)}
                onChange={(e) => {
                  const next = e.target.checked
                    ? Array.from(new Set([...strategy.symbols, sym]))
                    : strategy.symbols.filter((s) => s !== sym);
                  void onSymbols(next);
                }}
              />
              {sym}
            </label>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          {strategy.param_specs.map((spec) => (
            <label key={spec.name} className="flex flex-col gap-1 text-[11px] text-ink-2" title={spec.name}>
              <span className="truncate">
                {spec.label}
                {spec.min != null && spec.max != null && <span className="text-ink-3"> ({spec.min}–{spec.max})</span>}
              </span>
              {spec.type === "bool" ? (
                <Switch
                  checked={Boolean(draft[spec.name])}
                  onCheckedChange={(v) => setDraft({ ...draft, [spec.name]: v })}
                  label={spec.label}
                />
              ) : spec.choices ? (
                <select
                  className="h-8 rounded-md border border-line bg-surface-0 px-2 text-sm text-ink-1"
                  value={String(draft[spec.name])}
                  onChange={(e) => setDraft({ ...draft, [spec.name]: e.target.value })}
                >
                  {spec.choices.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              ) : (
                <Input
                  inputMode={spec.type === "str" ? "text" : "decimal"}
                  value={String(draft[spec.name] ?? "")}
                  onChange={(e) => setDraft({ ...draft, [spec.name]: e.target.value })}
                />
              )}
            </label>
          ))}
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 pt-2">
          <span className={`text-xs ${msg ? (msg.ok ? "text-good" : "text-bad") : "text-ink-3"}`}>{msg?.text ?? ""}</span>
          <Button size="sm" variant="outline" onClick={() => void save()} disabled={busy}>
            Guardar parámetros
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
