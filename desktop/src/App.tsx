import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, BarChart3, Bot, ClipboardList, Database, LineChart, Play, RefreshCw, Search, Settings, ShieldAlert } from 'lucide-react';
import { getJson, postJson, MarketReport, StockReport } from './api';
import './style.css';

type Page = 'dashboard' | 'watchlist' | 'stock' | 'market' | 'chat' | 'settings';

type Dashboard = {
  market: any;
  risk_alerts: any[];
  latest_reports: any[];
  tracking: any[];
};

const nav: Array<[Page, string, React.ReactNode]> = [
  ['dashboard', '首页', <Activity size={18} />],
  ['watchlist', '自选股', <ClipboardList size={18} />],
  ['stock', '个股报告', <BarChart3 size={18} />],
  ['market', '市场复盘', <LineChart size={18} />],
  ['chat', '问股', <Bot size={18} />],
  ['settings', '设置', <Settings size={18} />]
];

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [watchlistText, setWatchlistText] = useState('600519, HK00700, AAPL, MSFT');
  const [watchlistResult, setWatchlistResult] = useState<any>(null);
  const [stockSymbol, setStockSymbol] = useState('600519');
  const [stockReport, setStockReport] = useState<StockReport | null>(null);
  const [market, setMarket] = useState('cn');
  const [marketReport, setMarketReport] = useState<MarketReport | null>(null);
  const [chatText, setChatText] = useState('600519 can I chase it with breakout strategy?');
  const [chat, setChat] = useState<any>(null);
  const [busy, setBusy] = useState('');
  const [engineStatus, setEngineStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [searchText, setSearchText] = useState('600519');

  useEffect(() => { refreshDashboard(); }, []);

  async function run<T>(label: string, task: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    try { return await task(); } finally { setBusy(''); }
  }

  async function refreshDashboard() {
    try {
      const data = await getJson<Dashboard>('/dashboard');
      setDashboard(data);
      setEngineStatus('online');
    } catch {
      setEngineStatus('offline');
    }
  }

  async function quickAnalyze() {
    setStockSymbol(searchText);
    setPage('stock');
    await run('stock', async () => {
      const data = await postJson<StockReport>('/analyze/stock', { symbol: searchText, save: true });
      setStockReport(data);
      await refreshDashboard();
    });
  }

  async function analyzeWatchlist() {
    await run('watchlist', async () => {
      const symbols = watchlistText.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
      const data = await postJson<any>('/analyze/watchlist', { symbols, save: true });
      setWatchlistResult(data);
      setStockReport(data.items?.[0] ?? null);
      await refreshDashboard();
    });
  }

  async function analyzeStock() {
    await run('stock', async () => {
      const data = await postJson<StockReport>('/analyze/stock', { symbol: stockSymbol, save: true });
      setStockReport(data);
      await refreshDashboard();
    });
  }

  async function analyzeMarket() {
    await run('market', async () => {
      const data = await postJson<MarketReport>('/analyze/market', { market, save: true });
      setMarketReport(data);
      await refreshDashboard();
    });
  }

  async function ask() {
    await run('chat', async () => {
      setChat(await postJson<any>('/chat', { message: chatText }));
    });
  }

  return (
    <main className="app">
      <aside className="nav">
        <div className="brand"><span className="brand-mark"><Database size={18} /></span><span>Trading<br />Journal</span></div>
        {nav.map(([key, label, icon]) => (
          <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{icon}{label}</button>
        ))}
        <div className={`engine ${engineStatus}`}>
          <span />
          {busy ? `正在运行 ${busy}` : engineStatus === 'online' ? '本地引擎在线' : engineStatus === 'offline' ? '引擎未连接' : '检测引擎'}
        </div>
      </aside>

      <section className="content">
        <div className="topbar">
          <div className="searchbox">
            <Search size={18} />
            <input value={searchText} onChange={(e) => setSearchText(e.target.value)} placeholder="输入股票代码或名称，如 600519、HK00700、AAPL" />
          </div>
          <button className="primary top-action" onClick={quickAnalyze}><Play size={16} /> 分析</button>
          <button className="ghost" onClick={refreshDashboard}><RefreshCw size={16} /> 刷新</button>
        </div>

        {page === 'dashboard' && (
          <View title="研究工作台" subtitle="今日市场状态、自选股风险提醒和最新报告。">
            <div className="kpi-grid">
              <Kpi tone="blue" label="市场状态" value={dashboard?.market?.payload?.market_regime ?? '暂无报告'} />
              <Kpi tone="amber" label="风险提醒" value={String(dashboard?.risk_alerts?.length ?? 0)} />
              <Kpi tone="violet" label="追踪任务" value={String(dashboard?.tracking?.length ?? 0)} />
            </div>
            <Panel title="最新报告">
              {(dashboard?.latest_reports ?? []).map((item) => <ReportRow key={item.id} item={item} />)}
              {engineStatus === 'offline' && <Empty text="本地 Python 引擎未连接。界面可以正常使用，启动 engine.app 后数据会自动恢复。" />}
            </Panel>
          </View>
        )}

        {page === 'watchlist' && (
          <View title="自选股" subtitle="适合每日自动运行的固定分析流水线。">
            <textarea value={watchlistText} onChange={(e) => setWatchlistText(e.target.value)} />
            <button className="primary" onClick={analyzeWatchlist}><Play size={16} /> 运行自选股分析</button>
            {watchlistResult && <Panel title="评分排序">{watchlistResult.items.map((item: StockReport) => <StockCard key={item.symbol} report={item} onSelect={() => setStockReport(item)} />)}</Panel>}
          </View>
        )}

        {page === 'stock' && (
          <View title="个股报告" subtitle="决策摘要、技术面、新闻风险、策略命中和后续追踪。">
            <div className="inline-form"><input value={stockSymbol} onChange={(e) => setStockSymbol(e.target.value)} /><button className="primary" onClick={analyzeStock}>分析</button></div>
            {stockReport ? <StockReportView report={stockReport} /> : <Empty text="先运行一次个股分析。" />}
          </View>
        )}

        {page === 'market' && (
          <View title="市场复盘" subtitle="A股、港股、美股切换，输出结构化市场状态。">
            <div className="segmented">{['cn', 'hk', 'us'].map((m) => <button key={m} className={market === m ? 'active' : ''} onClick={() => setMarket(m)}>{m.toUpperCase()}</button>)}</div>
            <button className="primary" onClick={analyzeMarket}>生成市场复盘</button>
            {marketReport ? <MarketView report={marketReport} /> : <Empty text="运行一次市场复盘。" />}
          </View>
        )}

        {page === 'chat' && (
          <View title="问股" subtitle="开放式问题和报告追问会使用轻量 ReAct 工具循环。">
            <textarea value={chatText} onChange={(e) => setChatText(e.target.value)} />
            <button className="primary" onClick={ask}><Bot size={16} /> 提问</button>
            {chat && <Panel title="回答"><pre>{chat.content}</pre><pre>{JSON.stringify(chat.card, null, 2)}</pre></Panel>}
          </View>
        )}

        {page === 'settings' && (
          <View title="设置" subtitle="模型、数据源、自动任务和策略开关。">
            <div className="settings-grid">
              <Panel title="模型"><p>启动引擎前设置 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL。</p></Panel>
              <Panel title="数据源"><p>安装 <code>pip install -e .[data]</code> 可启用 akshare/yfinance。</p></Panel>
              <Panel title="策略"><p>内置 YAML 策略位于 <code>engine/strategies/builtin</code>。</p></Panel>
              <Panel title="自动任务"><p>自选股流水线是固定流程，适合后续接入本地定时任务。</p></Panel>
            </div>
          </View>
        )}
      </section>
    </main>
  );
}

function View(props: { title: string; subtitle: string; children: React.ReactNode }) {
  return <><header className="header"><div><p>{props.subtitle}</p><h1>{props.title}</h1></div></header>{props.children}</>;
}

function Panel(props: { title: string; children: React.ReactNode }) {
  return <section className="panel"><h2>{props.title}</h2>{props.children}</section>;
}

function Kpi(props: { label: string; value: string; tone?: 'blue' | 'amber' | 'violet' }) {
  return <div className={`kpi ${props.tone ?? 'blue'}`}><span>{props.label}</span><strong>{props.value}</strong></div>;
}

function ReportRow({ item }: { item: any }) {
  return <div className="report-row"><strong>{item.title}</strong><span>{item.score}/100</span><em>{item.created_at}</em></div>;
}

function StockCard({ report, onSelect }: { report: StockReport; onSelect: () => void }) {
  return <button className="stock-card" onClick={onSelect}><strong>{report.symbol}</strong><span>{report.score}/100</span><em>{report.action}</em></button>;
}

function StockReportView({ report }: { report: StockReport }) {
  return <div className="report-layout">
    <Panel title="Decision"><div className="score">{report.score}<span>/100</span></div><strong>{report.rating}</strong><p>{report.action}</p></Panel>
    <Panel title="Plan"><p>{report.operation_plan.entry}</p><ul><li>Stop: {report.operation_plan.stop}</li><li>Target: {report.operation_plan.target}</li><li>Position: {report.operation_plan.position}</li></ul></Panel>
    <Panel title="Strategies">{report.strategies.slice(0, 5).map((s) => <div className="strategy" key={s.key}><strong>{s.name}</strong><span>{s.score}/100</span><p>{s.evidence.join('; ')}</p></div>)}</Panel>
    <Panel title="Risks"><ul>{report.risk_flags.map((risk) => <li key={risk}><ShieldAlert size={14} /> {risk}</li>)}</ul></Panel>
    <Panel title="Markdown"><pre>{report.markdown}</pre></Panel>
  </div>;
}

function MarketView({ report }: { report: MarketReport }) {
  return <div className="report-layout">
    <Panel title="Regime"><div className="score">{report.score}<span>/100</span></div><strong>{report.market_regime}</strong><p>{report.strategy_bias}</p></Panel>
    <Panel title="Indices">{report.indices.map((i) => <div className="report-row" key={i.symbol}><strong>{i.symbol}</strong><span>{i.price}</span><em>{i.change_pct}%</em></div>)}</Panel>
    <Panel title="Sector rotation"><p>Leaders: {report.sector_rotation.leaders.join(', ')}</p><p>Laggards: {report.sector_rotation.laggards.join(', ')}</p></Panel>
    <Panel title="Tomorrow watch"><ul>{report.tomorrow_watch.map((item) => <li key={item}>{item}</li>)}</ul></Panel>
    <Panel title="Markdown"><pre>{report.markdown}</pre></Panel>
  </div>;
}

function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}

createRoot(document.getElementById('root')!).render(<App />);
