"use client";

import { useState } from "react";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { Input } from "./ui/input";

export function TokenGate({ onSubmit, error, busy }: { onSubmit: (t: string) => void; error: string | null; busy: boolean }) {
  const [value, setValue] = useState("");
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardContent className="space-y-4 p-6">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold">Mesa de micros</h1>
            <span className="inline-block rounded border border-warn/40 bg-warn/10 px-2 py-0.5 text-[11px] font-semibold tracking-wider text-warn">
              PAPER · TRADOVATE APAGADO
            </span>
          </div>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (value.trim()) onSubmit(value.trim());
            }}
          >
            <label htmlFor="token" className="block text-xs text-ink-2">
              Token del dashboard (DASHBOARD_TOKEN). Se guarda solo en esta pestaña, nunca en el servidor.
            </label>
            <Input id="token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
            {error && <p className="text-xs text-bad">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy || !value.trim()}>
              {busy ? "Comprobando…" : "Entrar"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
