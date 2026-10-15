export interface ParamSpec {
  name: string;
  type: "int" | "float" | "bool" | "str" | string;
  value: number | boolean | string;
  default: number | boolean | string | null;
  label: string;
  min: number | null;
  max: number | null;
  choices: string[] | null;
  help: string;
}

export interface StrategyInfo {
  strategy_id: string;
  name: string;
  enabled: boolean;
  symbols: string[];
  params: Record<string, number | boolean | string>;
  param_specs: ParamSpec[];
}

export interface EodRecord {
  day: string;
  day_pnl: number;
  balance: number;
  peak: number;
  floor: number;
  locked: boolean;
}

export interface Account {
  profile: string;
  balance: number;
  equity: number;
  day_realized: number;
  day_pnl: number;
  unrealized: number;
  peak_eod_balance: number;
  trail_floor: number;
  trail_locked: boolean;
  trail_status: string;
  cushion_usd: number;
  cushion_pct: number;
  cushion_floor_usd: number;
  max_risk_per_trade_usd: number;
  entries_today: number;
  max_entries_per_day: number;
  daily_loss_limit: number;
  day_lock_reason: string | null;
  breached: boolean;
  can_open: boolean;
  current_day: string | null;
  open_contracts: number;
  eod_history: EodRecord[];
}

export interface Profile {
  name: string;
  starting_balance: number;
  trail_amount: number;
  trail_lock_level: number;
  daily_loss_limit: number;
  default_contracts: number;
  max_contracts: number;
  block_minis: boolean;
  consistency_rule: boolean;
  flatten_time: string;
  allow_overnight: boolean;
  max_risk_pct_of_cushion: number;
  min_cushion_pct_of_trail: number;
  max_entries_per_day: number;
  claude_filter_enabled: boolean;
}

export interface PositionView {
  symbol: string;
  side: "long" | "short";
  qty: number;
  avg_price: number;
  opened_at: string;
  strategy_id: string | null;
  stop: number | null;
  target: number | null;
  mark?: number;
  unrealized_usd?: number;
}

export interface SignalRecord {
  id: number;
  strategy_id: string;
  symbol: string;
  side: "long" | "short";
  price: number;
  timestamp: string;
  stop: number;
  target: number;
  status: "accepted" | "rejected";
  reason: string;
  qty: number;
}

export interface EventRecord {
  id: number;
  ts: string;
  level: "info" | "warning" | "error";
  event: string;
  message: string;
  data: Record<string, unknown>;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  balance: number;
  floor: number;
  eod: boolean;
}

export interface LiquidityLevel {
  kind: "high" | "low";
  price: number;
  source: string;
}

export interface SessionCtx {
  symbol: string;
  day: string | null;
  bars: number;
  last_time: string | null;
  last_close: number | null;
  vwap: number | null;
  vwap_upper_2sd: number | null;
  vwap_lower_2sd: number | null;
  atr: number | null;
  orb_minutes: number;
  orb_high: number | null;
  orb_low: number | null;
  day_high: number | null;
  day_low: number | null;
  prev_day_high: number | null;
  prev_day_low: number | null;
  last_sweep: { time: string; kind: string; source: string; level: number; extreme: number } | null;
  liquidity_levels: LiquidityLevel[];
}

export interface Meta {
  mode: "paper";
  tradovate_enabled: boolean;
  ib_enabled: boolean;
  live_routing: boolean;
  notice: string;
  claude_key_present: boolean;
  claude_transport: string;
  claude_model: string;
  sample_csv: string;
}

export interface DeskState {
  account: Account;
  positions: PositionView[];
  working_orders: unknown[];
  strategies: StrategyInfo[];
  signals: SignalRecord[];
  events: EventRecord[];
  trades: unknown[];
  equity_curve: EquityPoint[];
  session: Record<string, SessionCtx>;
  profile: Profile;
  bars_processed: number;
  last_bar_time: string | null;
  meta: Meta;
}
