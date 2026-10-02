import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { AlertTriangle, Cpu, Download, FlaskConical, Loader2, Plus, Save, Square, Trash2, TrendingDown } from 'lucide-react';
import { toast } from 'sonner';
import api from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

const V2 = `${process.env.REACT_APP_BACKEND_URL}/api/v2/ai-usage`;
const get = (path, params) => api.get(path, { baseURL: V2, params }).then((r) => r.data);

const APPS = { '': 'Todo', intel: 'Intel', 'beta-copilot': 'Copilot de Beta', 'intel-shadow': 'Intel · pruebas en sombra' };
const RISK = {
  low: { label: 'Riesgo bajo', cls: 'text-emerald-400 border-emerald-500/30' },
  medium: { label: 'Riesgo medio', cls: 'text-amber-400 border-amber-500/30' },
  high: { label: 'Riesgo alto', cls: 'text-rose-400 border-rose-500/30' },
};

const n = (v) => (v ?? 0).toLocaleString('es-ES');
const usd = (v) => `${(v ?? 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;
const pct = (v) => `${((v ?? 0) * 100).toLocaleString('es-ES', { maximumFractionDigits: 1 })} %`;

function Kpi({ label, value, hint, testid }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/50" data-testid={testid}>
      <CardContent className="p-4">
        <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
        <div className="text-2xl font-semibold text-zinc-100 mt-1">{value}</div>
        {hint && <div className="text-[11px] text-zinc-500 mt-1">{hint}</div>}
      </CardContent>
    </Card>
  );
}

function Table({ rows, labelOf, testid }) {
  if (!rows?.length) return <p className="text-sm text-zinc-500 p-4">Sin llamadas en este periodo.</p>;
  return (
    <div className="overflow-x-auto" data-testid={testid}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-zinc-500">
            <th className="py-2 px-3">Nombre</th><th className="px-3 text-right">Llamadas</th>
            <th className="px-3 text-right">Tokens ent.</th><th className="px-3 text-right">Tokens sal.</th>
            <th className="px-3 text-right">Errores</th><th className="px-3 text-right">Coste</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-zinc-800/70 text-zinc-300">
              <td className="py-2 px-3">{labelOf ? labelOf(r.key) : r.key}</td>
              <td className="px-3 text-right">{n(r.calls)}</td>
              <td className="px-3 text-right">{n(r.in_tokens)}</td>
              <td className="px-3 text-right">{n(r.out_tokens)}</td>
              <td className="px-3 text-right">{r.errors ? `${n(r.errors)} (${pct(r.error_rate)})` : '—'}</td>
              <td className="px-3 text-right">
                {usd(r.cost_usd)}
                {r.unpriced_calls ? <span className="text-amber-400 text-[10px] ml-1" title="Hay llamadas de un modelo sin tarifa">sin precio</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PricesEditor({ prices, onSave, saving }) {
  const [draft, setDraft] = useState(prices);
  useEffect(() => setDraft(prices), [prices]);
  const set = (model, key, value) => setDraft((d) => ({ ...d, [model]: { ...d[model], [key]: value } }));
  return (
    <div data-testid="ai-usage-prices">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-zinc-500">
              <th className="py-2 px-3">Modelo</th><th className="px-3">Nivel</th>
              <th className="px-3 text-right">$ / M entrada</th><th className="px-3 text-right">$ / M salida</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(draft || {}).map(([model, p]) => (
              <tr key={model} className="border-t border-zinc-800/70 text-zinc-300">
                <td className="py-1.5 px-3 font-mono text-xs">{model}</td>
                <td className="px-3">
                  <select className="bg-zinc-900 border border-zinc-700 rounded px-1 py-0.5 text-xs" value={p.tier}
                    onChange={(e) => set(model, 'tier', e.target.value)}>
                    <option value="small">pequeño</option><option value="medium">medio</option><option value="large">grande</option>
                  </select>
                </td>
                {['in', 'out'].map((k) => (
                  <td key={k} className="px-3 text-right">
                    <input type="number" step="0.01" min="0" value={p[k]} onChange={(e) => set(model, k, parseFloat(e.target.value) || 0)}
                      className="w-20 bg-zinc-900 border border-zinc-700 rounded px-1 py-0.5 text-right text-xs" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between mt-3">
        <p className="text-[11px] text-zinc-500">Tarifas públicas aproximadas en USD por millón de tokens. Corrígelas si tu contrato es distinto.</p>
        <Button size="sm" onClick={() => onSave(draft)} disabled={saving} data-testid="ai-usage-save-prices">
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}Guardar tarifas
        </Button>
      </div>
    </div>
  );
}

const STATE = {
  ok: { label: 'En orden', cls: 'text-emerald-400 border-emerald-500/30' },
  warning: { label: 'Cerca del tope', cls: 'text-amber-400 border-amber-500/30' },
  exceeded: { label: 'Superado', cls: 'text-rose-400 border-rose-500/30' },
  off: { label: 'Desactivado', cls: 'text-zinc-400 border-zinc-600' },
};
const VERDICT = {
  equivalent: { label: 'Equivalente', cls: 'text-emerald-400 border-emerald-500/30' },
  not_recommended: { label: 'No recomendado', cls: 'text-rose-400 border-rose-500/30' },
  insufficient_data: { label: 'Recogiendo datos', cls: 'text-amber-400 border-amber-500/30' },
};

function BudgetsPanel({ info, features, onSave, saving }) {
  const [draft, setDraft] = useState([]);
  useEffect(() => setDraft((info?.items || []).map(({ scope, key, period, limit_usd, action, enabled }) => ({ scope, key, period, limit_usd, action, enabled }))), [info]);
  const statusOf = (i) => info?.items?.[i];
  const set = (i, patch) => setDraft((d) => d.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const sel = 'bg-zinc-900 border border-zinc-700 rounded px-1 py-0.5 text-xs';
  return (
    <div data-testid="ai-usage-budgets" className="space-y-2">
      {draft.length === 0 && <p className="text-sm text-zinc-500">Aún no hay presupuestos. Añade uno para que te avisemos al llegar al 80 % y al 100 %.</p>}
      {draft.map((b, i) => {
        const st = statusOf(i);
        return (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded border border-zinc-800 p-2 text-sm text-zinc-300">
            <select className={sel} value={b.scope} onChange={(e) => set(i, { scope: e.target.value, key: '' })}>
              <option value="total">Total</option><option value="app">Aplicación</option><option value="feature">Función</option>
            </select>
            {b.scope === 'app' && (
              <select className={sel} value={b.key} onChange={(e) => set(i, { key: e.target.value })}>
                <option value="">— elige —</option><option value="intel">Intel</option><option value="beta-copilot">Copilot de Beta</option>
              </select>
            )}
            {b.scope === 'feature' && (
              <select className={sel} value={b.key} onChange={(e) => set(i, { key: e.target.value })}>
                <option value="">— elige —</option>
                {Object.entries(features || {}).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            )}
            <select className={sel} value={b.period} onChange={(e) => set(i, { period: e.target.value })}>
              <option value="day">al día</option><option value="month">al mes</option>
            </select>
            <input type="number" min="0" step="0.5" className={`${sel} w-20 text-right`} value={b.limit_usd}
              onChange={(e) => set(i, { limit_usd: parseFloat(e.target.value) || 0 })} /><span>$</span>
            <select className={sel} value={b.action} onChange={(e) => set(i, { action: e.target.value })}
              title="Bloquear deja de llamar al modelo en las funciones de Intel hasta que acabe el periodo">
              <option value="alert">Solo avisar</option><option value="block">Bloquear al superar</option>
            </select>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={b.enabled} onChange={(e) => set(i, { enabled: e.target.checked })} />activo</label>
            {st && <Badge variant="outline" className={`text-[10px] ${(STATE[st.state] || STATE.ok).cls}`}>
              {(STATE[st.state] || STATE.ok).label} · {usd(st.spent_usd)} de {usd(st.limit_usd)}</Badge>}
            <button type="button" aria-label="Quitar" className="ml-auto text-zinc-500 hover:text-rose-400" onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}><Trash2 className="w-4 h-4" /></button>
          </div>
        );
      })}
      <div className="flex items-center justify-between pt-1">
        <Button variant="outline" size="sm" onClick={() => setDraft((d) => [...d, { scope: 'total', key: '', period: 'month', limit_usd: 50, action: 'alert', enabled: true }])} data-testid="ai-usage-add-budget">
          <Plus className="w-4 h-4 mr-1" />Añadir presupuesto</Button>
        <Button size="sm" onClick={() => onSave(draft)} disabled={saving} data-testid="ai-usage-save-budgets">
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Save className="w-4 h-4 mr-1" />}Guardar presupuestos</Button>
      </div>
      <p className="text-[11px] text-zinc-500">{info?.note}</p>
    </div>
  );
}

function ShadowPanel({ info, onStop }) {
  const items = info?.items || [];
  if (!items.length) return <p className="text-sm text-zinc-500" data-testid="ai-usage-shadow">No hay pruebas en marcha. Lánzalas desde las recomendaciones con «Probar en sombra».</p>;
  return (
    <div className="space-y-2" data-testid="ai-usage-shadow">
      {items.map((t) => {
        const v = t.result || {};
        const meta = VERDICT[v.state] || VERDICT.insufficient_data;
        return (
          <div key={`${t.feature}:${t.candidate_model}`} className="rounded border border-zinc-800 p-3 text-sm text-zinc-300">
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-zinc-100">{info.labels?.[t.feature] || t.feature}</b>
              <span className="font-mono text-xs text-emerald-300">{t.candidate_model}</span>
              <Badge variant="outline" className={`text-[10px] ${meta.cls}`}>{meta.label}</Badge>
              <span className="text-xs text-zinc-500">{n(v.runs)} de {t.max_runs} pruebas · {t.sample_pct} % de las llamadas · {t.enabled ? 'en marcha' : 'parada'}</span>
              {t.enabled && <button type="button" className="ml-auto text-zinc-400 hover:text-rose-400 flex items-center gap-1 text-xs" onClick={() => onStop(t)}><Square className="w-3 h-3" />Parar</button>}
            </div>
            {v.state && v.state !== 'insufficient_data' && (
              <p className="text-xs text-zinc-500 mt-1">
                Coincidencia media {pct(v.agreement)} (mínimo {pct(v.floor)}) · respuestas válidas {pct(v.valid_rate)} · errores {pct(v.error_rate)}.
                {v.state === 'equivalent' ? ' Puedes cambiar de modelo sin pérdida apreciable.' : ' No cambies de modelo: el candidato se queda corto.'}
              </p>
            )}
            {v.state === 'insufficient_data' && <p className="text-xs text-zinc-500 mt-1">Hacen falta al menos {v.needed} pruebas para dar un veredicto.</p>}
          </div>
        );
      })}
      <p className="text-[11px] text-zinc-500">{info?.note}</p>
    </div>
  );
}

export default function AIUsagePage() {
  const [days, setDays] = useState(30);
  const [app, setApp] = useState('');
  const [data, setData] = useState(null);
  const [recs, setRecs] = useState([]);
  const [prices, setPrices] = useState(null);
  const [budgets, setBudgets] = useState(null);
  const [shadow, setShadow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, r, p, b, sh] = await Promise.all([
        get('/summary', { days, ...(app ? { app } : {}) }), get('/recommendations', { days }), get('/prices'),
        get('/budgets'), get('/shadow'),
      ]);
      setData(s); setRecs(r.items || []); setPrices(p.prices); setBudgets(b);
      setShadow({ ...sh, labels: s.features ? Object.fromEntries(Object.entries(s.features).map(([k, v]) => [k, v.label])) : {} });
    } catch (e) {
      setError(e?.response?.status === 403 ? 'Solo los administradores pueden ver el consumo de IA.' : 'No se pudo cargar el consumo de IA.');
    } finally {
      setLoading(false);
    }
  }, [days, app]);

  useEffect(() => { load(); }, [load]);

  const featureLabel = useMemo(() => (k) => data?.features?.[k]?.label || k, [data]);
  const totalSaving = recs.reduce((a, r) => a + (r.monthly_saving_usd || 0), 0);

  const savePrices = async (draft) => {
    setSaving(true);
    try {
      await api.put('/prices', { prices: draft }, { baseURL: V2 });
      toast.success('Tarifas guardadas');
      await load();
    } catch { toast.error('No se pudieron guardar las tarifas'); } finally { setSaving(false); }
  };

  const saveBudgets = async (items) => {
    setSaving(true);
    try { await api.put('/budgets', { items }, { baseURL: V2 }); toast.success('Presupuestos guardados'); await load(); }
    catch { toast.error('No se pudieron guardar los presupuestos'); } finally { setSaving(false); }
  };

  const putShadow = async (items, okMsg) => {
    try { await api.put('/shadow', { items }, { baseURL: V2 }); toast.success(okMsg); await load(); }
    catch { toast.error('No se pudo actualizar la prueba en sombra'); }
  };
  const startShadow = (r) => putShadow([
    ...(shadow?.items || []).filter((t) => !(t.feature === r.feature && t.candidate_model === r.suggested_model))
      .map(({ feature, candidate_model, sample_pct, max_runs, enabled }) => ({ feature, candidate_model, sample_pct, max_runs, enabled })),
    { feature: r.feature, candidate_model: r.suggested_model, sample_pct: 10, max_runs: 200, enabled: true },
  ], 'Prueba en sombra iniciada (10 % de las llamadas)');
  const stopShadow = (t) => putShadow((shadow?.items || []).map(({ feature, candidate_model, sample_pct, max_runs, enabled }) => (
    feature === t.feature && candidate_model === t.candidate_model ? { feature, candidate_model, sample_pct, max_runs, enabled: false } : { feature, candidate_model, sample_pct, max_runs, enabled })), 'Prueba parada');
  const shadowOf = (r) => (shadow?.items || []).find((t) => t.feature === r.feature && t.candidate_model === r.suggested_model);

  const exportCsv = async () => {
    const res = await api.get('/export.csv', { baseURL: V2, params: { days }, responseType: 'blob' });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a'); a.href = url; a.download = `consumo_ia_${days}d.csv`; a.click(); URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6" data-testid="ai-usage-page">
      <div className="flex flex-wrap items-center gap-3">
        <Cpu className="w-6 h-6 text-indigo-400" />
        <div className="flex-1 min-w-[240px]">
          <h1 className="text-xl font-semibold text-zinc-100">Consumo de IA</h1>
          <p className="text-sm text-zinc-500">Llamadas a modelos de Intel y del Copilot de Beta. No se guarda ningún texto, solo cifras.</p>
        </div>
        <select value={app} onChange={(e) => setApp(e.target.value)} data-testid="ai-usage-app"
          className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1.5 text-sm text-zinc-200">
          {Object.entries(APPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} data-testid="ai-usage-days"
          className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1.5 text-sm text-zinc-200">
          {[1, 7, 30, 90].map((d) => <option key={d} value={d}>{d === 1 ? 'Hoy (24 h)' : `Últimos ${d} días`}</option>)}
        </select>
        <Button variant="outline" size="sm" onClick={exportCsv} data-testid="ai-usage-export"><Download className="w-4 h-4 mr-1" />CSV</Button>
      </div>

      {error && <div className="text-sm text-rose-400 border border-rose-500/30 rounded p-3">{error}</div>}
      {(budgets?.alerts || []).map((a, i) => (
        <div key={i} data-testid="ai-usage-alert" className={`flex items-center gap-2 text-sm rounded border p-3 ${a.state === 'exceeded' ? 'text-rose-300 border-rose-500/40 bg-rose-500/10' : 'text-amber-300 border-amber-500/40 bg-amber-500/10'}`}>
          <AlertTriangle className="w-4 h-4" />
          <span>
            Presupuesto {a.period === 'day' ? 'diario' : 'mensual'} {a.state === 'exceeded' ? 'superado' : 'al ' + Math.round(a.ratio * 100) + ' %'}:
            {' '}{a.scope === 'total' ? 'total' : a.scope === 'app' ? (APPS[a.key] || a.key) : (budgets.features?.[a.key] || a.key)}
            {' '}({usd(a.spent_usd)} de {usd(a.limit_usd)}){a.action === 'block' && a.state === 'exceeded' ? ' · llamadas bloqueadas en Intel' : ''}
          </span>
        </div>
      ))}
      {loading && !data && <div className="flex items-center gap-2 text-zinc-400"><Loader2 className="w-4 h-4 animate-spin" />Cargando…</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi testid="kpi-calls" label="Llamadas" value={n(data.calls)} hint={`${n(data.turns_without_model_call)} turnos resueltos sin modelo`} />
            <Kpi testid="kpi-tokens" label="Tokens" value={n(data.in_tokens + data.out_tokens)}
              hint={data.tokens_are_estimates ? 'estimados por longitud' : 'reales'} />
            <Kpi testid="kpi-cost" label="Coste estimado" value={usd(data.cost_usd)}
              hint={data.unpriced_calls ? `${n(data.unpriced_calls)} llamadas sin tarifa (no incluidas)` : 'tarifas públicas'} />
            <Kpi testid="kpi-errors" label="Errores" value={pct(data.error_rate)} hint={`${n(data.errors)} llamadas`} />
          </div>

          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader><CardTitle className="text-sm text-zinc-300">Coste por día (USD)</CardTitle></CardHeader>
            <CardContent style={{ height: 220 }}>
              {data.by_day?.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.by_day}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="day" tick={{ fill: '#71717a', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#71717a', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: '#18181b', border: '1px solid #3f3f46' }} />
                    <Area type="monotone" dataKey="cost_usd" name="Coste $" stroke="#818cf8" fill="#6366f133" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <p className="text-sm text-zinc-500">Sin llamadas en este periodo.</p>}
            </CardContent>
          </Card>

          <Card className="border-zinc-800 bg-zinc-900/50" data-testid="ai-usage-recs">
            <CardHeader>
              <CardTitle className="text-sm text-zinc-300 flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-emerald-400" />Recomendaciones de modelo
                {recs.length > 0 && <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">hasta {usd(totalSaving)} al mes</Badge>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {recs.length === 0 ? (
                <p className="text-sm text-zinc-500">Sin sugerencias: cada función ya usa el modelo más económico de su nivel o aún no hay datos.</p>
              ) : (
                <div className="space-y-2">
                  {recs.map((r) => (
                    <div key={`${r.feature}:${r.current_model}`} className="rounded border border-zinc-800 p-3 text-sm text-zinc-300">
                      <div className="flex flex-wrap items-center gap-2">
                        <b className="text-zinc-100">{r.label}</b>
                        <span className="font-mono text-xs">{r.current_model}</span><span>→</span>
                        <span className="font-mono text-xs text-emerald-300">{r.suggested_model}</span>
                        <Badge variant="outline" className={`text-[10px] ${RISK[r.risk].cls}`}>{RISK[r.risk].label}</Badge>
                        <span className="ml-auto text-emerald-400">−{usd(r.monthly_saving_usd)}/mes ({r.saving_pct} %)</span>
                      </div>
                      {r.feature.startsWith('copilot_') ? null : (() => {
                        const t = shadowOf(r);
                        const meta = t && (VERDICT[t.result?.state] || VERDICT.insufficient_data);
                        return (
                          <div className="flex items-center gap-2 mt-2">
                            {t ? <Badge variant="outline" className={`text-[10px] ${meta.cls}`}>Prueba en sombra: {meta.label}</Badge>
                              : <Button size="sm" variant="outline" onClick={() => startShadow(r)} data-testid={`shadow-start-${r.feature}`}>
                                <FlaskConical className="w-3.5 h-3.5 mr-1" />Probar en sombra</Button>}
                          </div>
                        );
                      })()}
                      <p className="text-xs text-zinc-500 mt-1">{r.note} · {n(r.calls)} llamadas medidas · necesita nivel «{r.needs === 'small' ? 'pequeño' : r.needs === 'medium' ? 'medio' : 'grande'}».</p>
                    </div>
                  ))}
                  <p className="text-[11px] text-zinc-500">Solo son sugerencias: nada se cambia solo. Prueba el modelo más barato en una copia antes de aplicarlo.</p>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="grid md:grid-cols-2 gap-4">
            <Card className="border-zinc-800 bg-zinc-900/50">
              <CardHeader><CardTitle className="text-sm text-zinc-300">Por función</CardTitle></CardHeader>
              <CardContent className="p-0"><Table rows={data.by_feature} labelOf={featureLabel} testid="ai-usage-by-feature" /></CardContent>
            </Card>
            <Card className="border-zinc-800 bg-zinc-900/50">
              <CardHeader><CardTitle className="text-sm text-zinc-300">Por modelo y aplicación</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table rows={data.by_model} testid="ai-usage-by-model" />
                <div className="border-t border-zinc-800" />
                <Table rows={data.by_app} labelOf={(k) => APPS[k] || k} testid="ai-usage-by-app" />
              </CardContent>
            </Card>
          </div>

          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader><CardTitle className="text-sm text-zinc-300">Presupuestos y avisos</CardTitle></CardHeader>
            <CardContent>{budgets && <BudgetsPanel info={budgets} features={budgets.features} onSave={saveBudgets} saving={saving} />}</CardContent>
          </Card>

          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader><CardTitle className="text-sm text-zinc-300 flex items-center gap-2"><FlaskConical className="w-4 h-4 text-indigo-400" />Pruebas en sombra</CardTitle></CardHeader>
            <CardContent><ShadowPanel info={shadow} onStop={stopShadow} /></CardContent>
          </Card>

          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader><CardTitle className="text-sm text-zinc-300">Tarifas</CardTitle></CardHeader>
            <CardContent>{prices && <PricesEditor prices={prices} onSave={savePrices} saving={saving} />}</CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
