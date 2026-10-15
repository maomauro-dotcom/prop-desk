# Mesa de micros — paper trading de MNQ y MES

Simulador **paper** para tres setups de índices CME (ORB, VWAP pullback/reclaim y liquidity sweep) sobre los micros
**MNQ** y **MES**. El ejecutor por defecto es interno: barras de 1 minuto, órdenes market/limit/stop, brackets con OCO,
posiciones, P&L y un trail EOD simulado. No hace falta broker para correrlo hoy.

```
barra TradingView o CSV → estrategia Python → riesgo (tamaño chico + colchón del trail) → filtro Claude opcional → ejecución paper → dashboard
```

> ## ⚠️ Advertencias
>
> - **El enrutado en vivo está apagado.** Los adaptadores de Tradovate e Interactive Brokers existen solo como
>   interfaces. Aunque pongas `TRADOVATE_ENABLED=true` o `IB_ENABLED=true` y tengas credenciales, **esta versión no
>   envía órdenes**: cada método lanza `LiveRoutingDisabledError` y no hace ninguna llamada de red.
> - **Apex suele prohibir bots y la automatización.** Antes de siquiera pensar en activar una ruta live, consigue
>   **permiso por escrito de Apex**. Este proyecto no implementa sigilo, ofuscación ni copy-trade oculto, y no lo hará.
> - **Los números del perfil son los elegidos para practicar, no las reglas publicadas de Apex.** El trail aquí es
>   2000 USD; el trail público de una cuenta de 50k suele ser **2500**. No se cambia en silencio: pega tus números reales
>   en el panel «Riesgo del trail EOD» del dashboard.
> - `data/sample_rth_mnq_mes.csv` es **sintético**. No es una grabación del CME.

---

## Contenido

| Ruta | Qué hay |
|---|---|
| `src/propdesk/domain` | Tipos (`Bar`, `Signal`, `Order`, `Position`, `Trade`), contratos CME, perfil de riesgo, reloj de sesión ET |
| `src/propdesk/strategies` | `orb`, `vwap_reclaim`, `liquidity_sweep` y el filtro de volatilidad |
| `src/propdesk/engine` | Risk manager, sesión (VWAP/ATR/OR/swings), motor, filtro Claude (fail closed) |
| `src/propdesk/brokers` | `PaperBroker` (funcional), `TradovateBroker` e `IbBroker` (apagados) |
| `src/propdesk/feeds` | `CsvBarFeed`, parser del webhook, `TradovateMarketData` (apagado) |
| `src/propdesk/backtest` | `python -m propdesk.backtest` |
| `src/propdesk/mcp_server` | Servidor MCP (SDK oficial o fallback JSON-RPC stdio) |
| `backend/` | FastAPI + SQLAlchemy + SQLite (`app`, `db`, `routes`, `security`, `service`) |
| `dashboard/` | Next.js 14 (App Router) + TypeScript + Tailwind + Recharts |
| `pine/` | Puente de barras v5 y overlays que solo dibujan |
| `data/` | CSV de muestra (regenerable con `scripts/make_sample_data.py`) |
| `tests/` | pytest |

## Requisitos

- Python 3.11+ y Node 20+.
- Nada más para paper. Opcional: `ANTHROPIC_API_KEY` si activas el filtro Claude.

## Instalación

```bash
cd prop-desk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,mcp]"
cp .env.example .env
```

Rellena `.env` (nunca lo subas; está en `.gitignore`):

```bash
python -c "import secrets; print('WEBHOOK_SECRET=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('DASHBOARD_TOKEN=' + secrets.token_urlsafe(32))"
```

| Variable | Uso |
|---|---|
| `WEBHOOK_SECRET` | Secreto compartido de `/webhook/bars`. **Vacío = el webhook rechaza todo.** |
| `DASHBOARD_TOKEN` | `Authorization: Bearer <token>` para `/api/*`. **Vacío = todas las rutas `/api` rechazan.** |
| `TRADOVATE_ENABLED`, `IB_ENABLED` | `false`. En `true` solo se informan en `/health`; no activan nada. |
| `ANTHROPIC_API_KEY` | Solo para el filtro Claude. Sin ella, con el filtro activo, todas las señales se rechazan. |
| `CLAUDE_MODEL` | Por defecto `claude-opus-5-5`. |
| `CLAUDE_TIMEOUT_S` | Timeout del filtro (por defecto 15 s). Timeout = rechazo. |
| `CLAUDE_TRANSPORT` | `anthropic` (llamada directa) o `mcp` (tool `analyze_setup` del servidor MCP). |
| `DATABASE_URL` | `sqlite:///./propdesk.db` por defecto. |
| `CORS_ORIGINS` | Origen del dashboard, `http://localhost:3000`. |

## Arranque

```bash
# backend
uvicorn backend.app:app --port 8000
curl localhost:8000/health
# {"status":"ok","mode":"paper","tradovate_enabled":false,"ib_enabled":false}

# dashboard (otra terminal)
cd dashboard
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                     # http://localhost:3000
```

O con Docker: `docker compose up --build` (usa tu `.env`).

En el dashboard pega el `DASHBOARD_TOKEN` y pulsa **Entrar**. El token se guarda solo en la pestaña
(`sessionStorage`), nunca en el servidor.

## Paper con el CSV de muestra

Botón **«Reproducir CSV de muestra»** o:

```bash
curl -X POST -H "Authorization: Bearer $DASHBOARD_TOKEN" localhost:8000/api/sim/replay
# {"bars":3900,"signals":39,"accepted":19,"rejected":20,"trades":19,"equity":50050.98,"balance":50050.98}
```

El replay **reinicia la cuenta paper**, procesa 5 sesiones RTH (5–9 oct 2026, MNQ y MES) y termina plano: cada día
se aplana a las 15:55 ET y se marca EOD (`flatten` → `eod_marked` en el registro). Las tres estrategias disparan.

Para regenerar el CSV (determinista): `python scripts/make_sample_data.py --seed 7`.

## Backtest

```bash
python -m propdesk.backtest --strategy orb   --symbol MNQ
python -m propdesk.backtest --strategy vwap  --symbol MES
python -m propdesk.backtest --strategy sweep --symbol MNQ --csv data/sample_rth_mnq_mes.csv
```

Corre el motor completo (riesgo, broker paper, flatten y EOD) con una sola estrategia y un solo símbolo. Imprime
las operaciones, win rate, R medio, P&L neto, max drawdown (mark-to-market), entradas bloqueadas por el
trail/colchón y si el trail habría bloqueado la cuenta.

## Cómo probar las tres estrategias

1. `pytest -q` — `tests/test_strategies_sample.py` afirma que **cada estrategia dispara al menos una vez** (y es
   aceptada) en el CSV de muestra, y que cada una emite señales en backtest aislado en MNQ y MES.
2. Backtest de cada una (arriba).
3. En el dashboard: «Reproducir CSV de muestra», y en «Señales recientes» aparecen ORB, VWAP y Sweep con su estado
   (aceptada / rechazada con motivo). Apaga una estrategia o cambia parámetros, guarda y vuelve a reproducir.

## Alerta de TradingView Premium → `/webhook/bars`

TradingView no permite cabeceras arbitrarias en los webhooks, por eso **el secreto va dentro del JSON** (`secret`).
El backend también acepta `X-Webhook-Secret` (útil para curl). La comparación es en tiempo constante (SHA-256 de
ambos lados). Un timestamp sin zona se interpreta como **America/New_York**.

1. TradingView solo envía webhooks a URLs públicas en el puerto 80/443 y exige 2FA en la cuenta. Expón el backend con
   HTTPS (por ejemplo un túnel de Cloudflare o ngrok hacia `localhost:8000`).
2. Abre un gráfico de **1 minuto** de `MNQ1!` (y otro de `MES1!`) con dato CME.
3. Pine Editor → pega `pine/tv_bar_bridge.pine` → *Add to chart*. En la configuración del indicador pon tu
   `WEBHOOK_SECRET` (queda en tu cuenta de TradingView, no en el repo).
4. Crea la alerta: condición = «Mesa de micros - bar bridge», **«Any alert() function call»**, expiración abierta.
   En *Notifications* activa **Webhook URL** = `https://<tu-host>/webhook/bars`. El mensaje lo genera el script.
5. Una alerta por símbolo. Cada cierre de vela de 1 minuto en RTH envía:

```json
{"secret":"…","symbol":"MNQZ2026","timeframe":"1","open":21000.25,"high":21004.5,"low":20998.0,
 "close":21002.75,"volume":1234,"timestamp":"2026-10-12T09:31:00"}
```

Prueba manual:

```bash
curl -X POST localhost:8000/webhook/bars -H 'Content-Type: application/json' \
  -d '{"secret":"'"$WEBHOOK_SECRET"'","symbol":"MNQ1!","timeframe":"1","open":21000,"high":21004,"low":20998,"close":21002,"volume":1200,"timestamp":"2026-10-12T09:31:00"}'
```

Respuestas: `200 accepted` (con las señales que produjo la barra), `200 ignored` (fuera de RTH), `401` secreto
incorrecto, `503` `WEBHOOK_SECRET` vacío, `422` payload inválido o timeframe distinto de 1, `409` barra duplicada o
fuera de orden. **Pine no manda órdenes**: solo reporta barras. Tampoco se scrapea TradingView ni se usan librerías
no oficiales.

Los overlays de `pine/overlays/` (`orb_range.pine`, `vwap_rth.pine`, `liquidity_levels.pine`) solo dibujan el ORB, el
VWAP RTH con bandas y los niveles de liquidez para que veas en el gráfico lo mismo que calcula Python.

## Perfil de riesgo `eod-trail-50k`

Persistido en SQLite y editable en «Riesgo del trail EOD».

| Campo | Valor | Regla |
|---|---|---|
| Saldo inicial | 50 000 USD | se aplica al «Reiniciar simulación» |
| Trail EOD | 2 000 USD | piso = pico de balance al cierre − 2 000 |
| Bloqueo del trail | 50 000 USD | cuando el piso llega al saldo inicial deja de subir |
| Pérdida diaria máx. | 500 USD | al tocarla se aplana y se bloquea el día |
| Tamaño | 1 micro por defecto, **tope duro 2 micros en total** | `max_contracts > 2` se rechaza |
| Minis NQ/ES | bloqueados | no se pueden desbloquear en esta versión |
| Consistencia | sin regla | |
| Flatten | 15:55 America/New_York | sin overnight |
| Riesgo por operación | ≤ 15 % del colchón | además, ≤ la pérdida diaria que queda |
| Colchón mínimo para abrir | 40 % del trail (800 USD) | |
| Entradas nuevas por día | 4 | |

Definiciones: **colchón** = equity actual (saldo + realizado del día + P&L abierto) − piso del trail. El piso solo se
mueve al marcar EOD, después del flatten: el P&L del día pasa al saldo, el contador del día se reinicia y, si hay
nuevo pico de balance, el trail lo sigue. Si la equity toca el piso intradía la cuenta queda bloqueada.
Una posición por símbolo a la vez.

## Estrategias

Cada estrategia es una clase con parámetros tipados y `on_bar(bar, ctx) -> list[Signal]`
(`Signal`: `strategy_id, symbol, side, price, timestamp, stop, target, metadata`). Los parámetros se editan en caliente
desde el dashboard o `PUT /api/strategies/{id}`; valores fuera de rango se rechazan con 422.

**Unidades:** en VWAP y Sweep, `trend_margin`, `min_slope`, `touch_tolerance`, `min_penetration` y `stop_buffer` son
**múltiplos del ATR(14) de 1 minuto**, para que los mismos números sirvan en MNQ y en MES.

### 1. ORB (`orb`) — MNQ prioritario, también MES
- Rango 09:30–09:45 ET (`range_minutes` 15, configurable 5–15).
- Entrada: primera vela de 1 minuto que **cierra** fuera del rango entre el fin del rango y 11:00 ET.
- Confirmación (`filter_mode`): volumen ≥ `volume_mult` (1.2) × media de 20 barras, o ATR ≥ `min_atr`, o cualquiera.
- Stop en el extremo opuesto del rango. Objetivo `target_r` 1.5 (hasta 2R). Sesgo VWAP opcional (`use_vwap_bias`, off).

### 2. VWAP pullback / reclaim (`vwap_reclaim`) — MNQ y MES
- VWAP de sesión anclado a las 09:30 ET (precio típico × volumen) con bandas de desviación.
- Tendencia: las `trend_bars` (8) barras previas cerraron a ≥ `trend_margin` (0.5 ATR) del mismo lado del VWAP y la
  pendiente del VWAP es ≥ `min_slope` (0.05 ATR/barra).
- Pullback: toque del VWAP dentro de `touch_tolerance` (0.25 ATR) con rechazo (cierre en la mitad a favor) o volumen.
- Reclaim: cruce decisivo (cuerpo ≥ 50 % del rango, cierre a ≥ `trend_margin`) y retest en ≤ `retest_bars` (5).
- Stop más allá del VWAP y de la vela + `stop_buffer` (0.5 ATR). Objetivo: banda ±`band_sigma` (2σ) o el
  máximo/mínimo de sesión, el primero que dé ≥ `min_rr`. Entradas hasta 15:45 ET.

### 3. Liquidity sweep (`liquidity_sweep`) — MNQ y MES
- Niveles: swings fractales recientes (`swing_k` 2), high/low del día previo y extremos del rango de apertura
  (`range_minutes` 15). Un nivel sigue vivo hasta que una vela cierra más allá o es barrido.
- Barrido con penetración ≥ `min_penetration` (0.25 ATR) y rechazo rápido: cierre de vuelta dentro en ≤ `reject_bars` (2).
- Stop más allá del extremo del barrido + `stop_buffer` (0.5 ATR). Objetivo 1.5R o la liquidez opuesta si da entre
  `target_r` y `max_r` (2R). Entradas hasta 15:45 ET.

### Filtro de volatilidad (todas)

ATR(14) de velas de 1 minuto, en puntos:

| Símbolo | Sesión muerta (ATR <) | Extremo (ATR >) | Vela spike (rango > k·ATR) |
|---|---|---|---|
| MNQ / NQ | 4.0 | 60.0 | 4 × ATR |
| MES / ES | 1.0 | 15.0 | 4 × ATR |

Un minuto normal de NQ en RTH mueve ~8–20 puntos (ES ~2–4). Por debajo del umbral muerto los stops quedan dentro del
ruido; por encima del extremo (noticias, CPI/FOMC) el modelo de fills deja de ser creíble.

## Motor y broker paper

- Reloj de sesión en America/New_York; solo barras RTH alimentan estrategias. `timestamp` de la barra = apertura.
- Market: fill al **cierre de la vela de la señal**. Stops y objetivos se evalúan **en las velas siguientes**.
- Limit/stop: si la vela abre más allá del precio, fill a la apertura (gap). Si stop y objetivo caen en la misma vela,
  se asume el **stop primero** (conservador; en 1 minuto no hay camino intrabarra).
- Bracket = padre + stop + objetivo con OCO. Cancelación, flatten y consulta de posiciones.
- A las 15:55 ET (primera vela ≥ 15:55, o el reloj del backend cada 15 s si no llegan barras): flatten → `eod_marked`.
- Ningún error en el camino de la orden se silencia: el broker lanza `BrokerError` y el motor lo registra como evento
  `order_rejected` y señal rechazada con motivo.
- Reiniciar el backend en mitad de la sesión conserva saldo, pico, perfil, señales y eventos, pero no las posiciones
  paper abiertas.

## Filtro Claude (apagado por defecto)

Si activas «Filtro Claude», cada señal que ya pasó el riesgo se envía a Claude (`claude-opus-5-5`, salida JSON
estructurada `approve|reject`) o al tool MCP `analyze_setup`. **Fail closed:** si falta `ANTHROPIC_API_KEY`, hay
timeout, error de Anthropic, rechazo del modelo, respuesta inválida o falla el MCP, la señal **se rechaza** y queda
registrada (evento `claude_filter` y motivo `claude_filter_fail_closed: …`). Claude nunca dimensiona posiciones.

## Servidor MCP

```bash
python -m propdesk.mcp_server        # stdio
```

Tools: `get_current_market_state(symbol)`, `get_vwap_and_orb(symbol)`, `analyze_setup(signal_context, call_model)`,
`get_risk_status()`, `get_recent_bars(symbol, limit)`, `get_liquidity_levels(symbol)`.

- Leen el backend vivo si defines `PROPDESK_API_URL` (+ `DASHBOARD_TOKEN`); si no, leen el SQLite de `DATABASE_URL`
  en solo lectura. Si no hay ninguna fuente devuelven error: **no se inventan datos ni se simula éxito de red**.
- `analyze_setup` devuelve el system prompt, el prompt construido y un `example_prompt` listo para enviar; con
  `call_model=true` llama a Claude y cualquier fallo es un error (el backend lo trata como rechazo).
- Usa el SDK oficial `mcp` si está instalado (`MCPServer` en mcp 2.x, `FastMCP` en 1.x). Si no, arranca un servidor
  JSON-RPC 2.0 por stdio con `initialize`, `tools/list` y `tools/call` (mismo formato; fuerza con
  `PROPDESK_MCP_IMPL=fallback`).

Registro en Claude Code:

```bash
claude mcp add propdesk --env DATABASE_URL=sqlite:///$PWD/propdesk.db -- python -m propdesk.mcp_server
```

## API

`GET /health` es pública. Todo `/api/*` exige `Authorization: Bearer <DASHBOARD_TOKEN>`.

| Método | Ruta | |
|---|---|---|
| GET | `/api/state` | Todo lo que pinta el dashboard |
| GET/PUT | `/api/strategies`, `/api/strategies/{id}` | `{enabled, symbols, params}` |
| GET | `/api/risk` | Saldo, equity, piso, colchón, lock, límites |
| GET/PUT | `/api/risk/profile` | `{"changes": {...}}` |
| GET | `/api/positions`, `/api/signals`, `/api/events`, `/api/trades`, `/api/equity` | |
| GET | `/api/session`, `/api/session/{symbol}`, `/api/bars/{symbol}` | ORB, VWAP, último sweep, barras |
| POST | `/api/sim/replay`, `/api/sim/reset`, `/api/flatten` | |
| GET | `/api/stream` | SSE (el dashboard lo lee con `fetch` para mandar el Bearer) |
| POST | `/webhook/bars` | Secreto en el JSON o `X-Webhook-Secret` |

## Tradovate e Interactive Brokers (apagados)

`TradovateBroker`, `TradovateMarketData` e `IbBroker` documentan en comentarios dónde irían auth, barras, órdenes,
flatten y posiciones. Todos sus métodos lanzan `LiveRoutingDisabledError` sin tocar la red, sea cual sea el valor de
`TRADOVATE_ENABLED`/`IB_ENABLED`. No confirmaste API de Tradovate ni cuenta de IB; y con Apex, **pide permiso por
escrito antes**. Ninguna orden live sale del proceso.

## Tests

```bash
pytest -q
```

Cubren: tope del 15 % y piso del 40 % del colchón; el trail sube con el pico EOD y se bloquea en el saldo inicial;
flatten a las 15:55 ET y ninguna entrada después del corte; webhook con secreto incorrecto (401) y correcto (200);
cada estrategia dispara en el CSV de muestra; minis bloqueados, nunca más de 2 micros, la pérdida diaria bloquea;
filtro Claude fail-closed (sin clave, timeout, excepción, MCP caído); broker paper (OCO, stop primero, gaps); API,
persistencia y MCP.

## Limitaciones conocidas

- Fills sin slippage ni comisiones por defecto (`PaperBroker(slippage_ticks=…)` lo permite).
- Una posición por símbolo; sin pirámides ni parciales.
- El CSV es sintético y está construido para que aparezcan los tres setups: sus resultados no dicen nada sobre el
  mercado real.
