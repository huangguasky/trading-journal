import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { invoke } from '@tauri-apps/api/core';
import { Activity, ArrowLeft, BarChart3, Bot, ClipboardList, Database, LineChart, Plus, RefreshCw, Send, Settings, ShieldAlert, Trash2, X } from 'lucide-react';
import { deleteJson, getJson, postJson, setEngineBase, MarketReport, StockReport } from './api';
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

type AnalyzeResponse<T> = { status: 'exists' | 'generated'; report: T };

type WatchlistItem = {
  symbol: string;
  latest_report: StockReport | null;
};

type SystemSettings = {
  openai_api_key: string;
  openai_base_url: string;
  openai_model: string;
  alpha_vantage_key: string;
  news_api_key: string;
  tavily_api_key: string;
  brave_search_api_key: string;
  social_sentiment_enabled: string;
  tool_timeout_s: string;
  agent_max_steps: string;
  agent_complexity: 'quick' | 'standard' | 'deep';
};

type AgentProfile = {
  key: 'quick' | 'standard' | 'deep';
  name: string;
  description: string;
  agents: string[];
  max_steps: number;
};

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  status?: string;
  card?: { intent?: string; pending_code?: string; agents?: string[]; complexity?: string; symbols?: string[]; tools?: Array<{ name: string; ok: boolean }> };
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
  const [watchlistSymbol, setWatchlistSymbol] = useState('');
  const watchlistComposing = useRef(false);
  const watchlistCompositionEnterHandled = useRef(false);
  const watchlistCompositionEndedAt = useRef(0);
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>([]);
  const [watchlistMessage, setWatchlistMessage] = useState('');
  const [stockSymbol, setStockSymbol] = useState('');
  const [stockReport, setStockReport] = useState<StockReport | null>(null);
  const [market, setMarket] = useState('cn');
  const [marketReport, setMarketReport] = useState<MarketReport | null>(null);
  const [chatText, setChatText] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const chatComposing = useRef(false);
  const chatCompositionEnterHandled = useRef(false);
  const chatCompositionEndedAt = useRef(0);
  const [busyTasks, setBusyTasks] = useState<Record<string, boolean>>({});
  const activeTasks = useRef(new Set<string>());
  const initialMarketLoaded = useRef(false);
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [reportFilter, setReportFilter] = useState('');
  const [engineStatus, setEngineStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [engineReady, setEngineReady] = useState(false);
  const [engineProblem, setEngineProblem] = useState('');
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [existingPrompt, setExistingPrompt] = useState<{ kind: 'stock' | 'market'; report: StockReport | MarketReport } | null>(null);
  const [systemSettings, setSystemSettings] = useState<SystemSettings>({
    openai_api_key: '',
    openai_base_url: '',
    openai_model: 'gpt-4o-mini',
    alpha_vantage_key: '',
    news_api_key: '',
    tavily_api_key: '',
    brave_search_api_key: '',
    social_sentiment_enabled: 'true',
    tool_timeout_s: '8',
    agent_max_steps: '5',
    agent_complexity: 'standard'
  });
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
  const [llmReady, setLlmReady] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState('');

  useEffect(() => { initializeEngine(); }, []);

  async function initializeEngine() {
    setEngineReady(false);
    setEngineStatus('checking');
    try {
      if (!import.meta.env.DEV) {
        setEngineBase(await invoke<string>('engine_endpoint'));
      }
      try {
        await waitForEngine(240);
      } catch {
        if (!import.meta.env.DEV) {
          await invoke('restart_engine');
          setEngineBase(await invoke<string>('engine_endpoint'));
        }
        await waitForEngine(240);
      }
      const results = await Promise.all([refreshDashboard(), loadSettings(), loadWatchlist()]);
      if (results.some((ready) => !ready)) throw new Error('引擎初始化数据尚未加载完成。');
      setEngineReady(true);
      setEngineStatus('online');
      setEngineProblem('');
    } catch (error) {
      setEngineReady(false);
      setEngineStatus('offline');
      let message = error instanceof Error ? error.message : '本地 Python 引擎未连接。';
      if (!import.meta.env.DEV) {
        try {
          const detail = await invoke<string | null>('engine_problem');
          if (detail) message = `本地引擎启动失败：${detail}`;
        } catch {
          // Keep the network error when the desktop bridge cannot provide diagnostics.
        }
      }
      setEngineProblem(message);
    }
  }

  async function waitForEngine(maxAttempts: number) {
    let lastError: unknown;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const health = await getJson<{ ok: boolean }>('/health');
        if (health.ok) return;
      } catch (error) {
        lastError = error;
        if (!import.meta.env.DEV && attempt % 4 === 3) {
          const detail = await invoke<string | null>('engine_problem');
          if (detail) throw new Error(`本地引擎启动失败：${detail}`);
        }
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    throw lastError instanceof Error ? lastError : new Error('本地引擎启动超时，请完全退出后重试。');
  }

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
      const reportData = await getJson<{ items: ReportRecord[] }>('/reports');
      setReports(reportData.items);
      if (!initialMarketLoaded.current) {
        initialMarketLoaded.current = true;
        setMarket('cn');
        const latestCnReport = reportData.items.find((item) => item.kind === 'market' && (item.market ?? (item.payload as MarketReport).market) === 'cn');
        setMarketReport(latestCnReport ? { ...latestCnReport.payload, id: latestCnReport.id, created_at: latestCnReport.created_at } as MarketReport : null);
      }
    } catch (error) {
      setEngineProblem(error instanceof Error ? error.message : '本地 Python 引擎未连接。');
      return false;
    }

    try {
      setDashboard(await getJson<Dashboard>('/dashboard'));
    } catch {
      // Reports remain usable when quote refresh for dashboard tracking fails.
      setDashboard(null);
    }
    return true;
  }

  async function loadSettings() {
    try {
      const data = await getJson<{ settings: SystemSettings; llm_ready: boolean; agent_profiles: AgentProfile[] }>('/settings');
      setSystemSettings(data.settings);
      setLlmReady(data.llm_ready);
      setAgentProfiles(data.agent_profiles);
      return true;
    } catch {
      return false;
    }
  }

  async function loadWatchlist() {
    try {
      const data = await getJson<{ items: WatchlistItem[] }>('/watchlist');
      setWatchlistItems(data.items);
      return true;
    } catch {
      return false;
    }
  }

  async function saveSettings() {
    await run('settings', async () => {
      const data = await postJson<{ settings: SystemSettings; llm_ready: boolean; agent_profiles: AgentProfile[] }>('/settings', systemSettings);
      setSystemSettings(data.settings);
      setLlmReady(data.llm_ready);
      setAgentProfiles(data.agent_profiles);
      setSettingsSaved(data.llm_ready ? '已保存。问股时会验证 LLM，调用失败将自动使用本地回答。' : '已保存。未配置 LLM Key，将使用本地回答。');
    });
  }

  async function addWatchlistSymbol() {
    if (!engineReady) return;
    const symbol = watchlistSymbol.trim();
    if (!symbol) return;
    await run('watchlist-add', async () => {
      const data = await postJson<{ items: WatchlistItem[]; symbol: string; created_report: boolean }>('/watchlist/add', { symbol });
      setWatchlistItems(data.items);
      setWatchlistSymbol('');
      setWatchlistMessage(data.created_report ? `已添加 ${data.symbol} 并生成报告。` : `已添加 ${data.symbol}，已载入最新报告。`);
      await refreshDashboard();
    });
  }

  async function removeWatchlistSymbol(symbol: string) {
    await run(`watchlist-remove-${symbol}`, async () => {
      const data = await deleteJson<{ items: WatchlistItem[] }>(`/watchlist/${encodeURIComponent(symbol)}`);
      setWatchlistItems(data.items);
      setWatchlistMessage(`已将 ${symbol} 移出自选。`);
    });
  }

  async function refreshWatchlistSymbol(symbol: string) {
    if (!engineReady) return;
    await run(`watchlist-refresh-${symbol}`, async () => {
      await postJson<AnalyzeResponse<StockReport>>('/analyze/stock', { symbol, save: true, force: true });
      await Promise.all([loadWatchlist(), refreshDashboard()]);
      setWatchlistMessage(`已刷新 ${symbol} 的报告。`);
    });
  }

  async function refreshAllWatchlist() {
    if (!engineReady || watchlistItems.length === 0) return;
    await run('watchlist-refresh-all', async () => {
      await postJson('/analyze/watchlist', { symbols: watchlistItems.map((item) => item.symbol), save: true });
      await Promise.all([loadWatchlist(), refreshDashboard()]);
      setWatchlistMessage('已刷新全部自选报告。');
    });
  }

  async function analyzeStock() {
    if (!engineReady) return;
    const symbol = stockSymbol.trim();
    if (!symbol) return;
    await run('stock', async () => {
      const data = await postJson<AnalyzeResponse<StockReport>>('/analyze/stock', { symbol, save: true });
      setStockSymbol('');
      if (data.status === 'exists') setExistingPrompt({ kind: 'stock', report: data.report });
      else {
        setStockReport(data.report);
        await refreshDashboard();
      }
    });
  }

  async function analyzeMarket() {
    if (!engineReady) return;
    await run('market', async () => {
      const data = await postJson<AnalyzeResponse<MarketReport>>('/analyze/market', { market, save: true });
      if (data.status === 'exists') setExistingPrompt({ kind: 'market', report: data.report });
      else {
        setMarketReport(data.report);
        await refreshDashboard();
      }
    });
  }

  async function regenerateExisting() {
    if (!engineReady) return;
    const prompt = existingPrompt;
    if (!prompt) return;
    setExistingPrompt(null);
    await run(prompt.kind, async () => {
      if (prompt.kind === 'stock') {
        const report = prompt.report as StockReport;
        const data = await postJson<AnalyzeResponse<StockReport>>('/analyze/stock', { symbol: report.symbol, save: true, force: true });
        setStockReport(data.report);
      } else {
        const report = prompt.report as MarketReport;
        const data = await postJson<AnalyzeResponse<MarketReport>>('/analyze/market', { market: report.market, save: true, force: true });
        setMarketReport(data.report);
      }
      await refreshDashboard();
    });
  }

  function viewExisting() {
    if (!existingPrompt) return;
    const { kind, report } = existingPrompt;
    setExistingPrompt(null);
    if (kind === 'stock') openStockReport(report as StockReport);
    else {
      const marketItem = report as MarketReport;
      setMarketReport(marketItem);
      setMarket(marketItem.market);
      setPage('market');
    }
  }

  async function ask() {
    if (!engineReady) return;
    const message = chatText.trim();
    if (!message) return;
    const history = chatMessages.map(({ role, content, status, card }) => ({ role, content, status, card }));
    setChatMessages((current) => [...current, { role: 'user', content: message }]);
    setChatText('');
    await run('chat', async () => {
      try {
        const result = await postJson<any>('/chat', { message, history });
        setChatMessages((current) => [...current, { role: 'assistant', content: result.content, status: result.status, card: result.card }]);
      } catch {
        setChatMessages((current) => [...current, { role: 'assistant', content: '暂时无法连接本地分析引擎，请稍后重试。', status: 'error' }]);
      }
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
    setPage('stock');
  }

  function navigateTo(nextPage: Page) {
    if (nextPage === 'stock') setStockReport(null);
    setPage(nextPage);
  }

  function selectMarket(nextMarket: string) {
    setMarket(nextMarket);
    const latest = reports.find((item) => item.kind === 'market' && (item.market ?? (item.payload as MarketReport).market) === nextMarket);
    setMarketReport(latest ? { ...latest.payload, id: latest.id, created_at: latest.created_at } as MarketReport : null);
  }

  async function deleteReport(reportId: number) {
    if (pendingDeleteId !== reportId) {
      setDeleteError('');
      setPendingDeleteId(reportId);
      return;
    }
    const deletingStockReport = stockReport?.id === reportId;
    await run(`delete-${reportId}`, async () => {
      try {
        const result = await deleteJson<{ deleted: boolean }>(`/reports/${reportId}`);
        if (!result.deleted) throw new Error('引擎未删除该报告，报告可能已经不存在。');
        setReports((current) => current.filter((item) => item.id !== reportId));
        if (stockReport?.id === reportId) setStockReport(null);
        if (marketReport?.id === reportId) setMarketReport(null);
        setPendingDeleteId(null);
        setDeleteError('');
        setPage(deletingStockReport ? 'stock' : 'dashboard');
        await refreshDashboard();
      } catch (error) {
        setPendingDeleteId(null);
        const message = error instanceof Error ? error.message : '未知错误';
        setDeleteError(`删除报告失败：${message}`);
      }
    });
  }

  const normalizedFilter = reportFilter.trim().toLowerCase();
  const filteredReports = reports.filter((item) => !normalizedFilter || [item.title, item.symbol, item.market, item.kind]
    .some((value) => String(value ?? '').toLowerCase().includes(normalizedFilter)));
  const stockReports = reports.filter((item) => item.kind === 'stock');
  const filteredStockReports = stockReports.filter((item) => !normalizedFilter || [item.title, item.symbol, item.market, item.kind]
    .some((value) => String(value ?? '').toLowerCase().includes(normalizedFilter)));

  return (
    <main className="app">
      {existingPrompt && <div className="confirm-overlay"><section className="confirm-dialog"><strong>已有报告</strong><p>该{existingPrompt.kind === 'stock' ? '股票' : '市场'}已有 {formatLocalTime(existingPrompt.report.created_at ?? existingPrompt.report.date)} 生成的报告。</p><div><button className="primary" disabled={!engineReady} onClick={regenerateExisting}>重新生成</button><button className="ghost" onClick={viewExisting}>直接查看</button><button className="ghost" onClick={() => setExistingPrompt(null)}>取消</button></div></section></div>}
      <aside className="nav">
        <div className="brand"><span className="brand-mark"><Database size={18} /></span><span>Trading<br />Journal</span></div>
        {nav.map(([key, label, icon]) => (
          <button key={key} className={page === key ? 'active' : ''} onClick={() => navigateTo(key)}>{icon}{label}</button>
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
              action={<button className="ghost" disabled={!engineReady} onClick={refreshDashboard}><RefreshCw size={16} /> 刷新追踪与风险状态</button>}
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
              {engineStatus === 'offline' && <Empty text={engineProblem || '本地 Python 引擎未连接。完全退出并重新打开应用后数据会自动恢复。'} />}
            </Panel>
          </View>
        )}

        {page === 'watchlist' && (
          <View title="自选股" subtitle="逐只维护关注标的，随时刷新最新分析报告。">
            <label className="symbol-field compact">
              <span>股票代码</span>
              <div className="symbol-input-row">
                <input
                  value={watchlistSymbol}
                  onChange={(event) => setWatchlistSymbol(event.target.value)}
                  onCompositionStart={() => {
                    watchlistComposing.current = true;
                    watchlistCompositionEnterHandled.current = false;
                  }}
                  onCompositionEnd={() => {
                    watchlistComposing.current = false;
                    watchlistCompositionEndedAt.current = watchlistCompositionEnterHandled.current ? 0 : performance.now();
                    watchlistCompositionEnterHandled.current = false;
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter') return;
                    const nativeEvent = event.nativeEvent;
                    if (watchlistComposing.current || nativeEvent.isComposing || nativeEvent.keyCode === 229) {
                      watchlistCompositionEnterHandled.current = true;
                      return;
                    }
                    const justCommittedComposition = watchlistCompositionEndedAt.current > 0 && performance.now() - watchlistCompositionEndedAt.current < 120;
                    if (justCommittedComposition) {
                      watchlistCompositionEndedAt.current = 0;
                      event.preventDefault();
                      return;
                    }
                    event.preventDefault();
                    addWatchlistSymbol();
                  }}
                  placeholder="例如 600519、HK0700 或 AAPL"
                />
                <button className="primary" disabled={!engineReady || isBusy('watchlist-add') || !watchlistSymbol.trim()} onClick={addWatchlistSymbol}><Plus size={16} /> 添加</button>
              </div>
              <small>每次添加一只股票；已有报告会直接载入，没有报告时会自动生成。</small>
            </label>
            {watchlistMessage && <p className="inline-status">{watchlistMessage}</p>}
            <Panel
              title={`自选列表（${watchlistItems.length}）`}
              action={<button className="ghost" disabled={!engineReady || isBusy('watchlist-refresh-all') || watchlistItems.length === 0} onClick={refreshAllWatchlist}><RefreshCw size={16} /> {isBusy('watchlist-refresh-all') ? '刷新中…' : '全部刷新'}</button>}
            >
              {watchlistItems.length > 0
                ? <div className="watchlist-list">{watchlistItems.map((item) => <WatchlistRow
                    key={item.symbol}
                    item={item}
                    refreshing={isBusy(`watchlist-refresh-${item.symbol}`)}
                    engineReady={engineReady}
                    removing={isBusy(`watchlist-remove-${item.symbol}`)}
                    onOpen={() => item.latest_report && openStockReport(item.latest_report)}
                    onRefresh={() => refreshWatchlistSymbol(item.symbol)}
                    onRemove={() => removeWatchlistSymbol(item.symbol)}
                  />)}</div>
                : <Empty text="暂无自选股票，请先添加一个股票代码。" />}
            </Panel>
          </View>
        )}

        {page === 'stock' && (
          <View title="个股报告" subtitle="决策摘要、技术面、新闻风险、策略命中和后续追踪。">
            <label className="symbol-field compact">
              <span>股票代码</span>
              <div className="symbol-input-row">
                <input value={stockSymbol} onChange={(e) => setStockSymbol(e.target.value)} placeholder="输入一个股票代码" />
                <button className="primary" disabled={!engineReady || isBusy('stock') || !stockSymbol.trim()} onClick={analyzeStock}>{isBusy('stock') ? '生成中…' : '分析'}</button>
              </div>
              <small>A 股：6 位代码，如 600519；港股：如 HK1810、HK01810 或 700.HK；美股：字母代码，如 AAPL。</small>
            </label>
            {stockReport && (
              <div className="report-actions">
                <button className="ghost" onClick={() => setStockReport(null)}><ArrowLeft size={16} /> 返回列表</button>
                {stockReport.id && <button className="danger report-delete" disabled={isBusy(`delete-${stockReport.id}`)} onClick={() => deleteReport(stockReport.id!)}><Trash2 size={16} /> 删除这份报告及追踪任务</button>}
                {deleteError && <p>{deleteError}</p>}
              </div>
            )}
            {stockReport
              ? <StockReportView report={stockReport} />
              : stockReports.length > 0
                ? <Panel title={`个股报告（${filteredStockReports.length}）`}>
                    <input className="report-filter" value={reportFilter} onChange={(event) => setReportFilter(event.target.value)} placeholder="按股票代码、标题或市场筛选报告" />
                    {filteredStockReports.map((item) => <ReportRow key={item.id} item={item} onOpen={() => openReport(item)} />)}
                    {filteredStockReports.length === 0 && <Empty text="没有符合筛选条件的个股报告。" />}
                  </Panel>
                : <Empty text="先运行一次个股报告。" />}
          </View>
        )}

        {page === 'market' && (
          <View title="市场复盘" subtitle="A股、港股、美股切换，输出结构化市场状态。">
            <div className="segmented">{['cn', 'hk', 'us'].map((m) => <button key={m} className={market === m ? 'active' : ''} onClick={() => selectMarket(m)}>{m.toUpperCase()}</button>)}</div>
            <button className="primary" disabled={!engineReady || isBusy('market')} onClick={analyzeMarket}>{isBusy('market') ? '生成复盘中…' : '生成市场复盘'}</button>
            {marketReport?.id && <button className="danger report-delete" disabled={isBusy(`delete-${marketReport.id}`)} onClick={() => deleteReport(marketReport.id!)}><Trash2 size={16} /> 删除这份报告</button>}
            {deleteError && <p>{deleteError}</p>}
            {marketReport ? <MarketView report={marketReport} /> : <Empty text="运行一次市场复盘。" />}
          </View>
        )}

        {page === 'chat' && (
          <View title="问股" subtitle="围绕股票、市场和持仓连续追问，系统会自动继承当前对话。">
            <section className="chat-shell">
              <div className="chat-toolbar">
                <div><Bot size={18} /><strong>{complexityLabel(systemSettings.agent_complexity)}分析</strong><span>{formatAgentNames(activeProfile(agentProfiles, systemSettings.agent_complexity)?.agents)}</span></div>
                {chatMessages.length > 0 && <button className="ghost icon-button" title="清空对话" onClick={() => setChatMessages([])}><Trash2 size={16} /></button>}
              </div>
              <div className="chat-thread">
                {chatMessages.length === 0 && <Empty text="可以从股票代码开始，例如“600519 最近风险大吗？”，回答后继续问“那止损放哪里？”即可。" />}
                {chatMessages.map((message, index) => (
                  <article key={index} className={`chat-message ${message.role} ${message.status === 'refused' ? 'refused' : ''}`}>
                    <span>{message.role === 'user' ? '你' : '研究助手'}</span>
                    {message.role === 'assistant' ? <MarkdownContent content={message.content} /> : <p>{message.content}</p>}
                    {message.card?.agents?.length ? <small>参与分析：{formatAgentNames(message.card.agents, '、')}</small> : null}
                  </article>
                ))}
                {isBusy('chat') && <article className="chat-message assistant pending"><span>研究助手</span><p>正在整理行情、技术与风险证据…</p></article>}
              </div>
              <div className="chat-composer">
                <textarea
                  value={chatText}
                  onChange={(event) => setChatText(event.target.value)}
                  onCompositionStart={() => {
                    chatComposing.current = true;
                    chatCompositionEnterHandled.current = false;
                  }}
                  onCompositionEnd={() => {
                    chatComposing.current = false;
                    chatCompositionEndedAt.current = chatCompositionEnterHandled.current ? 0 : performance.now();
                    chatCompositionEnterHandled.current = false;
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter') return;
                    const nativeEvent = event.nativeEvent;
                    const justCommittedComposition = chatCompositionEndedAt.current > 0 && performance.now() - chatCompositionEndedAt.current < 120;
                    const isActiveComposition = chatComposing.current || nativeEvent.isComposing || nativeEvent.keyCode === 229;
                    if (isActiveComposition) {
                      chatCompositionEnterHandled.current = true;
                      return;
                    }
                    if (justCommittedComposition) {
                      chatCompositionEndedAt.current = 0;
                      event.preventDefault();
                      return;
                    }
                    if (!event.shiftKey) { event.preventDefault(); ask(); }
                  }}
                  placeholder="输入股票代码和问题，Enter 发送，Shift + Enter 换行"
                />
                <button className="primary icon-button" title="发送" disabled={!engineReady || isBusy('chat') || !chatText.trim()} onClick={ask}><Send size={18} /></button>
              </div>
            </section>
          </View>
        )}

        {page === 'settings' && (
          <View title="设置" subtitle="模型、数据源、自动任务和策略开关。">
            <Panel title="LLM 配置">
              <div className="settings-form">
                <p>用于问股回答和分析报告的自然语言增强；失败时自动回退到规则分析。<em>{llmReady ? ' 已配置' : ' 未配置'}</em></p>
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

            <Panel title="问股分析复杂度">
              <div className="agent-profile-grid">
                {agentProfiles.map((profile) => (
                  <button
                    key={profile.key}
                    className={`agent-profile ${systemSettings.agent_complexity === profile.key ? 'active' : ''}`}
                    onClick={() => setSystemSettings({ ...systemSettings, agent_complexity: profile.key, agent_max_steps: String(profile.max_steps) })}
                  >
                    <span><strong>{profile.name}</strong><em>最多 {profile.max_steps} 步</em></span>
                    <p>{profile.description}</p>
                    <small>{formatAgentNames(profile.agents)}</small>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="本地执行参数">
              <div className="settings-form compact">
                <p>数据源会按可用性自动降级：A 股 Yahoo → AkShare；港/美股 Yahoo → Alpha Vantage。</p>
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
                  <span>NewsAPI.org Key</span>
                  <input
                    type="password"
                    value={systemSettings.news_api_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, news_api_key: event.target.value })}
                    placeholder="NewsAPI.org 新闻源（可选）"
                  />
                </label>
                <label>
                  <span>Tavily Key</span>
                  <input
                    type="password"
                    value={systemSettings.tavily_api_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, tavily_api_key: event.target.value })}
                    placeholder="补充新闻与网页检索（可选）"
                  />
                </label>
                <label>
                  <span>Brave Search Key</span>
                  <input
                    type="password"
                    value={systemSettings.brave_search_api_key}
                    onChange={(event) => setSystemSettings({ ...systemSettings, brave_search_api_key: event.target.value })}
                    placeholder="备用网页搜索（可选）"
                  />
                </label>
                <label className="toggle-row">
                  <span>美股社交情绪</span>
                  <input
                    type="checkbox"
                    checked={systemSettings.social_sentiment_enabled === 'true'}
                    onChange={(event) => setSystemSettings({ ...systemSettings, social_sentiment_enabled: event.target.checked ? 'true' : 'false' })}
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

        {pendingDeleteId !== null && (
          <div className="modal-backdrop" role="presentation" onClick={() => setPendingDeleteId(null)}>
            <div className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" onClick={(event) => event.stopPropagation()}>
              <div className="confirm-modal-icon"><Trash2 size={22} /></div>
              <h3 id="delete-dialog-title">确认删除报告？</h3>
              <p>删除后无法恢复，对应的追踪任务也会一并删除。</p>
              <div className="confirm-modal-actions">
                <button className="ghost" onClick={() => setPendingDeleteId(null)}>取消</button>
                <button className="danger" disabled={isBusy(`delete-${pendingDeleteId}`)} onClick={() => deleteReport(pendingDeleteId)}>
                  {isBusy(`delete-${pendingDeleteId}`) ? '删除中…' : '确认删除'}
                </button>
              </div>
            </div>
          </div>
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

function activeProfile(profiles: AgentProfile[], complexity: SystemSettings['agent_complexity']) {
  return profiles.find((profile) => profile.key === complexity);
}

function complexityLabel(value: SystemSettings['agent_complexity']) {
  return { quick: '快速', standard: '标准', deep: '深度' }[value] ?? '标准';
}

function formatAgentNames(agents: string[] | undefined, separator = ' · ') {
  return (agents ?? []).map((name) => name.replace(/\s*Agent$/i, '')).join(separator);
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const children = renderMarkdownInline(heading[2], `h-${index}`);
      blocks.push(level === 1 ? <h2 key={index}>{children}</h2> : level === 2 ? <h3 key={index}>{children}</h3> : <h4 key={index}>{children}</h4>);
      index += 1;
      continue;
    }

    if (line.startsWith('```')) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) code.push(lines[index++]);
      index += 1;
      blocks.push(<pre key={`code-${index}`}><code>{code.join('\n')}</code></pre>);
      continue;
    }

    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const headers = splitMarkdownTableRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) rows.push(splitMarkdownTableRow(lines[index++]));
      blocks.push(<div className="markdown-table-wrap" key={`table-${index}`}><table><thead><tr>{headers.map((cell, cellIndex) => <th key={cellIndex}>{renderMarkdownInline(cell, `th-${cellIndex}`)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{renderMarkdownInline(cell, `td-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody></table></div>);
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) items.push(lines[index++].trim().replace(/^[-*]\s+/, ''));
      blocks.push(<ul key={`ul-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{renderMarkdownInline(item, `ul-${itemIndex}`)}</li>)}</ul>);
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) items.push(lines[index++].trim().replace(/^\d+\.\s+/, ''));
      blocks.push(<ol key={`ol-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{renderMarkdownInline(item, `ol-${itemIndex}`)}</li>)}</ol>);
      continue;
    }

    if (/^---+$/.test(line)) {
      blocks.push(<hr key={`hr-${index}`} />);
      index += 1;
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,3})\s+|^```|^[-*]\s+|^\d+\.\s+|^---+$/.test(lines[index].trim())) {
      if (lines[index].includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) break;
      paragraph.push(lines[index++].trim());
    }
    blocks.push(<p key={`p-${index}`}>{renderMarkdownInline(paragraph.join(' '), `p-${index}`)}</p>);
  }

  return <div className="markdown-content">{blocks}</div>;
}

function splitMarkdownTableRow(line: string) {
  return line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
}

function renderMarkdownInline(text: string, keyPrefix: string) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={`${keyPrefix}-${index}`}>{part.slice(1, -1)}</code>;
    return <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>;
  });
}

function Kpi(props: { label: string; value: string; tone?: 'blue' | 'amber' | 'violet' }) {
  return <div className={`kpi ${props.tone ?? 'blue'}`}><span>{props.label}</span><strong>{props.value}</strong></div>;
}

function ReportRow({ item, onOpen }: { item: ReportRecord; onOpen: () => void }) {
  return <button className="report-row" onClick={onOpen}><strong>{item.title}</strong><span>{item.score}/100</span><em>{formatLocalTime(item.created_at)}</em></button>;
}

function WatchlistRow(props: {
  item: WatchlistItem;
  refreshing: boolean;
  engineReady: boolean;
  removing: boolean;
  onOpen: () => void;
  onRefresh: () => void;
  onRemove: () => void;
}) {
  const report = props.item.latest_report;
  return <article className="watchlist-row">
    <button className="watchlist-report" disabled={!report} onClick={props.onOpen}>
      <span><strong>{props.item.symbol}</strong><small>{report ? `更新于 ${formatLocalTime(report.created_at ?? report.date)}` : '暂无报告'}</small></span>
      {report && <><em>{report.score}/100</em><p>{report.action}</p></>}
    </button>
    <div className="watchlist-actions">
      <button className="ghost" disabled={!props.engineReady || props.refreshing} onClick={props.onRefresh}><RefreshCw size={15} /> {props.refreshing ? '刷新中…' : '刷新报告'}</button>
      <button className="ghost remove" disabled={props.removing} onClick={props.onRemove}><X size={15} /> 移出</button>
    </div>
  </article>;
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

function StockReportView({ report }: { report: StockReport }) {
  const confirmations = report.evidence?.confirmations ?? [];
  const news = report.news ?? [];
  const watchConditions = report.operation_plan.watch_conditions ?? [];
  const stockName = report.quote.name && report.quote.name !== report.symbol ? report.quote.name : '名称暂缺';
  return <div className="report-layout">
    <Panel title="决策摘要"><div className="report-identity"><span>股票代码</span><strong>{report.symbol}</strong><span>股票名称</span><strong>{stockName}</strong><small className="report-time">报告时间：{formatLocalTime(report.created_at ?? report.date) || '未知'}</small></div><div className="score">{report.score}<span>/100</span></div><strong>{report.rating}</strong><p>{report.action}</p><p>当前价格：{report.quote.price} {report.quote.currency}（{report.quote.change_pct}%）</p></Panel>
    <Panel title="核心结论"><p>{report.core_conclusion ?? `${report.action}。请结合核心证据与操作计划执行。`}</p></Panel>
    <Panel title="核心证据">{confirmations.length ? <ul>{confirmations.map((item) => <li key={item}>{item}</li>)}</ul> : <Empty text="暂无核心证据。" />}</Panel>
    <Panel title="策略融合">{(report.selected_strategies ?? report.strategies.slice(0, 3)).map((s) => <div className="strategy" key={s.key}><strong>{s.name}</strong><span>{s.score}/100</span><p>{s.evidence.join('；')}</p></div>)}</Panel>
    <Panel title="操作计划"><p>{report.operation_plan.entry}</p><ul><li>理想买入价：{report.operation_plan.ideal_buy ?? '-'}</li><li>止损：{report.operation_plan.stop ?? '-'}</li><li>目标：{report.operation_plan.target ?? '-'}</li><li>仓位：{report.operation_plan.position}</li></ul>{watchConditions.length > 0 && <><strong>后续追踪</strong><ul>{watchConditions.map((item) => <li key={item}>{item}</li>)}</ul></>}</Panel>
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
