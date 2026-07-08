const BASE = import.meta.env.DEV ? '/engine' : 'http://127.0.0.1:8765';

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export type StockReport = {
  id?: number;
  symbol: string;
  market: string;
  score: number;
  rating: string;
  action: string;
  quote: { price: number; currency: string; change_pct: number; source: string };
  risk_flags: string[];
  operation_plan: { entry: string; stop: number; target: number; position: string };
  strategies: Array<{ key: string; name: string; score: number; stance: string; evidence: string[]; risks: string[] }>;
  markdown: string;
};

export type MarketReport = {
  market: string;
  market_regime: string;
  score: number;
  indices: Array<{ symbol: string; price: number; change_pct: number; currency: string }>;
  breadth: Record<string, number | null>;
  sector_rotation: { leaders: string[]; laggards: string[] };
  risk_flags: string[];
  tomorrow_watch: string[];
  strategy_bias: string;
  markdown: string;
};

