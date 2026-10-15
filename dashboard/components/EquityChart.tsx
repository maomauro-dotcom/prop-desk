"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Account, EquityPoint } from "@/lib/types";
import { etTime, signedUsd, usd } from "@/lib/format";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

export function EquityChart({ points, account, start }: { points: EquityPoint[]; account: Account; start: number }) {
  const data = points.map((p, i) => ({ ...p, i, label: etTime(p.ts) }));
  const values = data.flatMap((d) => [d.equity, d.floor]).concat(start);
  const min = values.length ? Math.min(...values) : start - 2500;
  const max = values.length ? Math.max(...values) : start + 500;
  const pad = Math.max(50, (max - min) * 0.08);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Equity paper</CardTitle>
          <CardDescription className="num">
            Equity {usd(account.equity)} · día {signedUsd(account.day_pnl)}
          </CardDescription>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-ink-2">
          <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-accent" />Equity</span>
          <span className="flex items-center gap-1"><span className="inline-block h-0 w-4 border-t-2 border-dashed border-bad" />Piso del trail</span>
        </div>
      </CardHeader>
      <CardContent className="h-64 pt-2">
        {data.length < 2 ? (
          <div className="flex h-full items-center justify-center text-sm text-ink-3">Aún no hay barras de la sesión.</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#2e2e2b" strokeDasharray="0" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#8f8e86", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#34342f" }}
                minTickGap={48} />
              <YAxis domain={[Math.floor(min - pad), Math.ceil(max + pad)]} tick={{ fill: "#8f8e86", fontSize: 10 }}
                tickLine={false} axisLine={false} width={56}
                tickFormatter={(v: number) => v.toLocaleString("es-ES", { maximumFractionDigits: 0 })} />
              <ReferenceLine y={start} stroke="#52514e" strokeDasharray="2 4"
                label={{ value: "saldo inicial", fill: "#8f8e86", fontSize: 10, position: "insideTopLeft" }} />
              <Tooltip
                contentStyle={{ background: "#232321", border: "1px solid #34342f", borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: "#c3c2b7" }}
                formatter={(v: number, name: string) => [usd(v), name === "equity" ? "Equity" : "Piso del trail"]}
                labelFormatter={(l: string) => `${l} ET`}
              />
              <Line type="stepAfter" dataKey="floor" stroke="#e66767" strokeWidth={1.5} strokeDasharray="5 4" dot={false}
                isAnimationActive={false} />
              <Line type="linear" dataKey="equity" stroke="#3987e5" strokeWidth={2} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: "#1a1a19", strokeWidth: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
