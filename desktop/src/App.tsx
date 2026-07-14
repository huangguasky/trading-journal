import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, BarChart3, Bot, ClipboardList, Database, LineChart, Play, RefreshCw, Settings, ShieldAlert, Trash2 } from 'lucide-react';
import { deleteJson, getJson, postJson, MarketReport, StockReport } from './api';
import './style.css';

type Page = 'dashboard' | 'watchlist' | 'stock' | 'market' | 'chat' | 'settings';

type Dashboard = {
  market: any;
  risk_alerts: TrackingItem[];
  latest_reports: any[];
  tracking: TrackingItem[];
};

type TrackingItem = {
  id: number;
  symbol: string;
  base_price: number;
  current_price: number;
  target_price?: number;
  stop_price?: number;
  pnl_pct: number;
  computed_status: 'open' | 'target_hit' | 'stop_hit';
  created_at?: string;
};

type ReportRecord = {
  id: number;
  kind: 'stock' | 'market';
  symbol?: string;
  market?: string;
  title: string;
  score: number;
  created_at: string;
  payload: StockReport | MarketReport;
};

type SystemSettings = {
  llm_enabled: string;
  openai_api_key: string;
  openai_base_url: string;
  openai_model: string;
  data_provider: string;
  data_provider_order: string;
  tushare_token: string;
  alpha_vantage_key: string;
  news_api_key: string;
  tool_timeout_s: string;
  agent_max_steps: string;
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
  const [watchlistText, setWatchlistText] = useState('600519, HK0700, AAPL, MSFT');
  const [watchlistResult, setWatchlistResult] = useState<any>(null);
  const [stockSymbol, setStockSymbol] = useState('600519');
  const [stockReport, setStockReport] = useState<StockReport | null>(null);
  const [market, setMarket] = useState('cn');
  const [marketReport, setMarketReport] = useState<MarketReport | null>(null);
  const [chatText, setChatText] = useState('600519 can I chase it with breakout strategy?');
  const [chat, setChat] = useState<any>(null);
  const [busyTasks, setBusyTasks] = useState<Record<string, boolean>>({});
  const activeTasks = useRef(new Set<string>());
  const initialMarketLoaded = useRef(false);
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [reportFilter, setReportFilter] = useState('');
  const [engineStatus, setEngineStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [systemSettings, setSystemSettings] = useState<SystemSettings>({
    llm_enabled: 'false',
    openai_api_key: '',
    openai_base_url: '',
    openai_model: 'gpt-4o-mini',
    data_provider: 'auto',
    data_provider_order: 'tushare,akshare,yfinance,alpha_vantage,sample',
    tushare_token: '',
    alpha_vantage_key: '',
    news_api_key: '',
    tool_timeout_s: '8',
    agent_max_steps: '5'
  });
  const [llmReady, setLlmReady] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState('');

  useEffect(() => { refreshDashboard(); loadSettings(); loadWatchlist(); }, []);

  async function run<T>(label: string, task: () => Promise<T>): Promise<T | undefined> {
    if (activeTasks.current.has(label)) return undefined;
    activeTasks.current.add(label);
    setBusyTasks((current) => ({ ...current, [label]: true }));
    try { return await task(); } finally {
      activeTasks.current.delete(label);
      setBusyTasks((current) => ({ ...current, [label]: false }));
    }
  }

  const isBusy = (label: string) => Boolean(busyTasks[label]);
  const busyLabels = Object.keys(busyTasks).filter((label) => busyTasks[label]);

  async function refreshDashboard() {
    try {
      const [data, reportData] = await Promise.all([
        getJson<Dashboard>('/dashboard'),
        getJson<{ items: ReportRecord[] }>('/reports')
      ]);
      setDashboard(data);
      setReports(reportData.items);
      if (!initialMarketLoaded.current) {
        initialMarketLoaded.current = true;
        setMarket('cn');
        const latestCnReport = reportData.items.find((item) => item.kind === 'market' && (item.market ?? (item.payload as MarketReport).market) === 'cn');
        setMarketReport(latestCnReport ? { ...latestCnReport.payload, id: latestCnReport.id, created_at: latestCnReport.created_at } as MarketReport : null);
      }
      setEngineStatus('online');
    } catch {
      setEngineStatus('offline');
    }
  }

  async function loadSettings() {
    try {
      const data = await getJson<{ settings: SystemSettings; llm_ready: boolean }>('/settings');
      setSystemSettings(data.settings);
      setLlmReady(data.llm_ready);
      setEngineStatus('online');
    } catch {
      setEngineStatus('offline');
    }
  }

  async function loadWatchlist() {
    try {
      const data = await getJson<{ items: Array<{ symbol: string }> }>('/watchlist');
      setWatchlistText(data.items.map((item) => item.symbol).join(', '));
    } catch {
      setEngineStatus('offline');
    }
  }

  async function saveSettings() {
    await run('settings', async () => {
      const data = await postJson<{ settings: SystemSettings; llm_ready: boolean }>('/settings', systemSettings);
      setSystemSettings(data.settings);
      setLlmReady(data.llm_ready);
      setSettingsSaved(data.llm_ready ? '已保存，LLM 问股已启用。' : '已保存。填写 Key 并启用 LLM 后，问股会使用模型。');
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

  function openReport(item: ReportRecord) {
    if (item.kind === 'stock') {
      const report = { ...item.payload, id: item.id, created_at: item.created_at } as StockReport;
      openStockReport(report);
      return;
    }
    const report = { ...item.payload, id: item.id, created_at: item.created_at } as MarketReport;
    setMarketReport(report);
    setMarket(report.market);
    setPage('market');
  }

  function openStockReport(report: StockReport) {
    setStockReport(report);
    setStockSymbol(report.symbol);
    setPage('stock');
  }

  function selectMarket(nextMarket: string) {
    setMarket(nextMarket);
    const latest = reports.find((item) => item.kind === 'market' && (item.market ?? (item.payload as MarketReport).market) === nextMarket);
    setMarketReport(latest ? { ...latest.payload, id: latest.id, created_at: latest.created_at } as MarketReport : null);
  }

  async function deleteReport(reportId: number) {
    if (!window.confirm('确定删除这份报告吗？对应的追踪任务也会一并删除。')) return;
    await run(`delete-${reportId}`, async () => {
      await deleteJson(`/reports/${reportId}`);
      if (stockReport?.id === reportId) setStockReport(null);
      if (marketReport?.id === reportId) setMarketReport(null);
      setPage('dashboard');
      await refreshDashboard();
    });
  }

  const normalizedFilter = reportFilter.trim().toLowerCase();
  const filteredReports = reports.filter((item) => !normalizedFilter || [item.title, item.symbol, item.market, item.kind]
    .some((value) => String(value ?? '').toLowerCase().includes(normalizedFilter)));

  return (
    <main className="app">
      <aside className="nav">
        <div className="brand"><span className="brand-mark"><Database size={18} /></span><span>Trading<br />Journal</span></div>
        {nav.map(([key, label, icon]) => (
          <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{icon}{label}</button>
        ))}
        <div className={`engine ${engineStatus}`}>
          <span />
          {busyLabels.length ? `正在运行 ${busyLabels.join('、')}` : engineStatus === 'online' ? '本地引擎在线' : engineStatus === 'offline' ? '引擎未连接' : '检测引擎'}
        </div>
      </aside>

      <section className="content">
        {page === 'dashboard' && (
          <View title="研究工作台" subtitle="今日市场状态、自选股风险提醒和最新报告。">
            <div className="kpi-grid">
              <Kpi tone="blue" label="市场状态" value={dashboard?.market?.payload?.market_regime ? marketRegimeLabel(dashboard.market.payload.market_regime) : '暂无报告'} />
              <Kpi tone="amber" label="风险提醒" value={String(dashboard?.risk_alerts?.length ?? 0)} />
              <Kpi tone="violet" label="追踪任务" value={String(dashboard?.tracking?.length ?? 0)} />
            </div>
            <Panel
              title="追踪结果与风险提醒"
              action={<button className="ghost" onClick={refreshDashboard}><RefreshCw size={16} /> 刷新追踪与风险状态</button>}
            >
              {(dashboard?.risk_alerts?.length ?? 0) > 0 && (
                <div className="risk-summary">
                  <strong><ShieldAlert size={16} /> 已触发的价格提醒</strong>
                  {dashboard!.risk_alerts.map((item) => <TrackingRow key={`risk-${item.id}`} item={item} />)}
                </div>
              )}
              {(dashboard?.tracking?.length ?? 0) > 0
                ? <div className="tracking-list">{dashboard!.tracking.map((item) => <TrackingRow key={item.id} item={item} />)}</div>
                : <Empty text="暂无追踪任务。完成一次个股分析后，系统会自动创建追踪任务。" />}
            </Panel>
            <Panel title={`全部报告（${filteredReports.length}）`}>
              <input className="report-filter" value={reportFilter} onChange={(event) => setReportFilter(event.target.value)} placeholder="按股票代码、标题或市场筛选报告" />
              {filteredReports.map((item) => <ReportRow key={item.id} item={item} onOpen={() => openReport(item)} />)}
              {reports.length > 0 && filteredReports.length === 0 && <Empty text="没有符合筛选条件的报告。" />}
              {reports.length === 0 && engineStatus !== 'offline' && <Empty text="暂无报告。" />}
              {engineStatus === 'offline' && <Empty text="本地 Python 引擎未连接。界面可以正常使用，启动 engine.app 后数据会自动恢复。" />}
            </Panel>
          </View>
        )}

        {page === 'watchlist' && (
          <View title="自选股" subtitle="适合每日自动运行的固定分析流水线。">
            <label className="symbol-field">
              <span>股票代码</span>
              <small>格式：A 股输入 6 位代码，如 600519；港股可输入 HK1810、HK01810 或 700.HK；美股输入字母代码，如 AAPL。多个代码用逗号或空格分隔。</small>
              <textarea value={watchlistText} onChange={(e) => setWatchlistText(e.target.value)} />
            </label>
            <button className="primary" disabled={isBusy('watchlist')} onClick={analyzeWatchlist}><Play size={16} /> {isBusy('watchlist') ? '正在分析自选股…' : '运行自选股分析'}</button>
            {watchlistResult && <Panel title="评分排序">{watchlistResult.items.map((item: StockReport) => <StockCard key={item.symbol} report={item} onSelect={() => openStockReport(item)} />)}</Panel>}
          </View>
        )}

        {page === 'stock' && (
          <View title="个股报告" subtitle="决策摘要、技术面、新闻风险、策略命中和后续追踪。">
            <label className="symbol-field compact">
              <span>股票代码</span>
              <div className="symbol-input-row">
                <input value={stockSymbol} onChange={(e) => setStockSymbol(e.target.value)} />
                <button className="primary" disabled={isBusy('stock')} onClick={analyzeStock}>{isBusy('stock') ? '生成中…' : '分析'}</button>
              </div>
              <small>A 股：6 位代码，如 600519；港股：如 HK1810、HK01810 或 700.HK；美股：字母代码，如 AAPL。</small>
            </label>
            {stockReport?.id && <button className="danger report-delete" disabled={isBusy(`delete-${stockReport.id}`)} onClick={() => deleteReport(stockReport.id!)}><Trash2 size={16} /> 删除这份报告及追踪任务</button>}
            {stockReport ? <StockReportView report={stockReport} /> : <Empty text="先运行一次个股分析或从首页选择历史报告。" />}
          </View>
        )}

        {page === 'market' && (
          <View title="市场复盘" subtitle="A股、港股、美股切换，输出结构化市场状态。">
            <div className="segmented">{['cn', 'hk', 'us'].map((m) => <button key={m} className={market === m ? 'active' : ''} onClick={() => selectMarket(m)}>{m.toUpperCase()}</button>)}</div>
            <button className="primary" disabled={isBusy('market')} onClick={analyzeMarket}>{isBusy('market') ? '生成复盘中…' : '生成市场复盘'}</button>
            {marketReport?.id && <button className="danger report-delete" disabled={isBusy(`delete-${marketReport.id}`)} onClick={() => deleteReport(marketReport.id!)}><Trash2 size={16} /> 删除这份报告</button>}
            {marketReport ? <MarketView report={marketReport} /> : <Empty text="运行一次市场复盘。" />}
          </View>
        )}

        {page === 'chat' && (
          <View title="问股" subtitle="开放式问题和报告追问会使用轻量 ReAct 工具循环。">
            <textarea value={chatText} onChange={(e) => setChatText(e.target.value)} />
            <button className="primary" disabled={isBusy('chat')} onClick={ask}><Bot size={16} /> {isBusy('chat') ? '正在回答…' : '提问'}</button>
            {chat && <Panel title="回答"><pre>{chat.content}</pre><pre>{JSON.stringify(chat.card, null, 2)}</pre></Panel>}
          </View>
        )}

        {page === 'settings' && (
          <View title="设置" subtitle="模型、数据源、自动任务和策略开关。">
            <Panel title="LLM 问股配置">
              <div className="settings-form">
                <label className="switch-row">
                  <input
                    type="checkbox"
                    checked={systemSettings.llm_enabled === 'true'}
                    onChange={(event) => setSystemSettings({ ...systemSettings, llm_enabled: event.target.checked ? 'true' : 'false' })}
                  />
                  <span>启用 LLM 综合回答</span>
                  <em>{llmReady ? '已就绪' : '未就绪'}</em>
                </label>
                <label>
                  <span>OpenAI API Key</span>
                  <input
                    type="password"
                    value={systemSettings.openai_api_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, openai_api_key: event.target.value })}
                    placeholder="sk-..."
                  />
                </label>
                <label>
                  <span>Base URL</span>
                  <input
                    value={systemSettings.openai_base_url}
                    onChange={(event) => setSystemSettings({ ...systemSettings, openai_base_url: event.target.value })}
                    placeholder="https://api.openai.com/v1"
                  />
                </label>
                <label>
                  <span>模型</span>
                  <input
                    value={systemSettings.openai_model}
                    onChange={(event) => setSystemSettings({ ...systemSettings, openai_model: event.target.value })}
                    placeholder="gpt-4o-mini"
                  />
                </label>
              </div>
            </Panel>

            <Panel title="本地执行参数">
              <div className="settings-form compact">
                <label>
                  <span>数据源</span>
                  <select
                    value={systemSettings.data_provider}
                    onChange={(event) => setSystemSettings({ ...systemSettings, data_provider: event.target.value })}
                  >
                    <option value="auto">自动选择</option>
                    <option value="sample">离线样本</option>
                    <option value="akshare">AkShare</option>
                    <option value="yfinance">Yahoo Finance</option>
                  </select>
                </label>
                <label>
                  <span>降级顺序</span>
                  <input
                    value={systemSettings.data_provider_order}
                    onChange={(event) => setSystemSettings({ ...systemSettings, data_provider_order: event.target.value })}
                    placeholder="tushare,akshare,yfinance,alpha_vantage,sample"
                  />
                </label>
                <label>
                  <span>Tushare Token</span>
                  <input
                    type="password"
                    value={systemSettings.tushare_token}
                    onChange={(event) => setSystemSettings({ ...systemSettings, tushare_token: event.target.value })}
                    placeholder="A股增强数据，可选"
                  />
                </label>
                <label>
                  <span>Alpha Vantage Key</span>
                  <input
                    type="password"
                    value={systemSettings.alpha_vantage_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, alpha_vantage_key: event.target.value })}
                    placeholder="美股/港股备用数据，可选"
                  />
                </label>
                <label>
                  <span>NewsAPI Key</span>
                  <input
                    type="password"
                    value={systemSettings.news_api_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, news_api_key: event.target.value })}
                    placeholder="新闻源，可选"
                  />
                </label>
                <label>
                  <span>工具超时（秒）</span>
                  <input
                    value={systemSettings.tool_timeout_s}
                    onChange={(event) => setSystemSettings({ ...systemSettings, tool_timeout_s: event.target.value })}
                  />
                </label>
                <label>
                  <span>Agent 最大步数</span>
                  <input
                    value={systemSettings.agent_max_steps}
                    onChange={(event) => setSystemSettings({ ...systemSettings, agent_max_steps: event.target.value })}
                  />
                </label>
              </div>
            </Panel>

            <div className="settings-actions">
              <button className="primary" disabled={isBusy('settings')} onClick={saveSettings}>{isBusy('settings') ? '保存中…' : '保存设置'}</button>
              <button className="ghost" onClick={loadSettings}>重新加载</button>
              {settingsSaved && <span>{settingsSaved}</span>}
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

function Panel(props: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return <section className="panel"><div className="panel-heading"><h2>{props.title}</h2>{props.action}</div>{props.children}</section>;
}

function Kpi(props: { label: string; value: string; tone?: 'blue' | 'amber' | 'violet' }) {
  return <div className={`kpi ${props.tone ?? 'blue'}`}><span>{props.label}</span><strong>{props.value}</strong></div>;
}

function ReportRow({ item, onOpen }: { item: ReportRecord; onOpen: () => void }) {
  return <button className="report-row" onClick={onOpen}><strong>{item.title}</strong><span>{item.score}/100</span><em>{formatLocalTime(item.created_at)}</em></button>;
}

function TrackingRow({ item }: { item: TrackingItem }) {
  return <div className={`tracking-row ${item.computed_status}`}>
    <div><strong>{item.symbol}</strong><span>{trackingStatusLabel(item.computed_status)}</span></div>
    <div><small>基准价</small><strong>{item.base_price}</strong></div>
    <div><small>当前价</small><strong>{item.current_price}</strong></div>
    <div><small>目标 / 止损</small><strong>{item.target_price ?? '-'} / {item.stop_price ?? '-'}</strong></div>
    <em className={item.pnl_pct >= 0 ? 'positive' : 'negative'}>{item.pnl_pct >= 0 ? '+' : ''}{item.pnl_pct}%</em>
  </div>;
}

function StockCard({ report, onSelect }: { report: StockReport; onSelect: () => void }) {
  return <button className="stock-card" onClick={onSelect}><strong>{report.symbol}</strong><span>{report.score}/100</span><em>{report.action}</em></button>;
}

function StockReportView({ report }: { report: StockReport }) {
  const confirmations = report.evidence?.confirmations ?? [];
  const news = report.news ?? [];
  const watchConditions = report.operation_plan.watch_conditions ?? [];
  const stockName = report.quote.name && report.quote.name !== report.symbol ? report.quote.name : '名称暂缺';
  return <div className="report-layout">
    <Panel title="决策摘要"><div className="report-identity"><span>股票代码</span><strong>{report.symbol}</strong><span>股票名称</span><strong>{stockName}</strong><small className="report-time">报告时间：{formatLocalTime(report.created_at ?? report.date) || '未知'}</small></div><div className="score">{report.score}<span>/100</span></div><strong>{report.rating}</strong><p>{report.action}</p><p>当前价格：{report.quote.price} {report.quote.currency}（{report.quote.change_pct}%）</p></Panel>
    <Panel title="核心证据">{confirmations.length ? <ul>{confirmations.map((item) => <li key={item}>{item}</li>)}</ul> : <Empty text="暂无核心证据。" />}</Panel>
    <Panel title="策略融合">{(report.selected_strategies ?? report.strategies.slice(0, 3)).map((s) => <div className="strategy" key={s.key}><strong>{s.name}</strong><span>{s.score}/100</span><p>{s.evidence.join('；')}</p></div>)}</Panel>
    <Panel title="操作计划"><p>{report.operation_plan.entry}</p><ul><li>止损：{report.operation_plan.stop}</li><li>目标：{report.operation_plan.target}</li><li>仓位：{report.operation_plan.position}</li></ul>{watchConditions.length > 0 && <><strong>后续追踪</strong><ul>{watchConditions.map((item) => <li key={item}>{item}</li>)}</ul></>}</Panel>
    <Panel title="资讯与风险">{news.length > 0 ? <><strong>相关资讯</strong><ul>{news.map((item, index) => <li key={`${item.title}-${index}`}>{item.title}{item.source ? `（${item.source}）` : ''}</li>)}</ul></> : <p>暂无相关新闻。</p>}<strong>风险提示</strong>{report.risk_flags.length > 0 ? <ul>{report.risk_flags.map((risk) => <li key={risk}><ShieldAlert size={14} /> {risk}</li>)}</ul> : <p>暂无明显风险信号。</p>}</Panel>
    <Panel title="数据质量"><QualityView data={report.data_quality} /></Panel>
  </div>;
}

function MarketView({ report }: { report: MarketReport }) {
  const breadth = report.breadth;
  const macroNews = report.macro_news ?? [];
  return <div className="report-layout">
    <Panel title="市场结论"><div className="report-identity"><span>对应市场</span><strong>{marketLabel(report.market)}</strong><small className="report-time">报告时间：{formatLocalTime(report.created_at ?? report.date) || '未知'}</small></div><div className="score">{report.score}<span>/100</span></div><strong>{marketRegimeLabel(report.market_regime)}</strong><p>策略倾向：{strategyBiasLabel(report.strategy_bias)}</p><p>上涨 {breadth.advancers ?? '-'} 家，下跌 {breadth.decliners ?? '-'} 家。</p></Panel>
    <Panel title="主要指数">{report.indices.map((i) => <div className="report-row" key={i.symbol}><strong>{i.symbol}</strong><span>{i.price}</span><em>{i.change_pct}%</em></div>)}</Panel>
    <Panel title="市场宽度与情绪"><ul><li>涨停家数：{breadth.limit_up ?? '-'}</li><li>跌停家数：{breadth.limit_down ?? '-'}</li><li>成交额：{breadth.turnover_billion ?? '-'} 亿（估算）</li><li>情绪描述：{report.market_context?.sentiment ?? '中性'}</li></ul></Panel>
    <Panel title="板块轮动"><p>领涨方向：{report.sector_rotation.leaders.join('、')}</p><p>落后方向：{report.sector_rotation.laggards.join('、')}</p></Panel>
    <Panel title="宏观与事件">{macroNews.length > 0 ? <ul>{macroNews.map((item, index) => <li key={`${item.title}-${index}`}>{item.title}{item.source ? `（${item.source}）` : ''}</li>)}</ul> : <p>暂无宏观或事件资讯。</p>}</Panel>
    <Panel title="风险提示">{report.risk_flags.length > 0 ? <ul>{report.risk_flags.map((item) => <li key={item}><ShieldAlert size={14} /> {item}</li>)}</ul> : <p>暂无明显风险信号。</p>}</Panel>
    <Panel title="明日关注">{report.tomorrow_watch.length > 0 ? <ul>{report.tomorrow_watch.map((item) => <li key={item}>{item}</li>)}</ul> : <p>暂无待关注事项。</p>}</Panel>
    <Panel title="数据质量"><QualityView data={{ market: report.data_quality }} /></Panel>
  </div>;
}

function QualityView({ data }: { data?: Record<string, any> }) {
  const entries = Object.entries(data ?? {}).filter(([, value]) => value);
  if (!entries.length) return <Empty text="暂无数据质量记录。" />;
  return <div className="quality-list">{entries.map(([key, value]) => (
    <div className="quality-item" key={key}>
      <strong>{qualityLabel(key)}</strong>
      <span>{value.status ?? 'unknown'} · {value.source ?? value.sources?.join(', ') ?? 'unknown'} · {value.confidence ?? 'unknown'}</span>
    </div>
  ))}</div>;
}

function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}

createRoot(document.getElementById('root')!).render(<App />);

function marketRegimeLabel(value: string) {
  return { risk_on: '风险偏好升温', neutral: '震荡均衡', risk_off: '防守优先', volatile: '高波动震荡' }[value] ?? value;
}

function marketLabel(value: string) {
  return { cn: 'A股', hk: '港股', us: '美股' }[value] ?? value.toUpperCase();
}

function strategyBiasLabel(value: string) {
  return { trend: '趋势跟随', defensive: '防守优先', wait: '等待确认', event: '事件驱动' }[value] ?? value;
}

function qualityLabel(value: string) {
  return { history: 'K线', price: '行情', news: '资讯', market: '市场快照' }[value] ?? value;
}

function trackingStatusLabel(value: TrackingItem['computed_status']) {
  return { open: '追踪中', target_hit: '已达到目标价', stop_hit: '已触及止损价' }[value];
}

function formatLocalTime(value: string | undefined) {
  if (!value) return '';
  return value.replace('T', ' ').replace(/\+08:00$/, '').replace(/Z$/, '').slice(0, 19);
}
