import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, TrendingUp, TrendingDown, Minus, RefreshCw, Clock, Shield } from 'lucide-react';
import { toast } from 'sonner';

function fmtDate(iso) { if (!iso) return '—'; const s = String(iso); if (/^\d{8}$/.test(s)) return `${s.substring(6,8)}/${s.substring(4,6)}/${s.substring(0,4)}`; const [y,m,d]=(s||'').substring(0,10).split('-'); return d&&m&&y?`${d}/${m}/${y}`:s.substring(0,10); }

const TREND_COLORS = { up: 'text-emerald-400', down: 'text-rose-400', stable: 'text-zinc-400' };
const TREND_ICONS = { up: TrendingUp, down: TrendingDown, stable: Minus };
const STRENGTH_OPACITY = { strong: 'opacity-100', moderate: 'opacity-80', weak: 'opacity-60' };
const IMPACT_LABELS = {
  positive_for_financing: 'Favorable para financiacion', negative_for_financing: 'Desfavorable para financiacion',
  positive_for_valuation: 'Favorable para valoracion', negative_for_valuation: 'Presion sobre valoraciones',
  neutral: 'Neutral', mixed: 'Mixto',
};
const SIGNAL_LABELS = {
  financing_conditions_improving: 'Condiciones de financiacion mejorando',
  financing_conditions_tightening: 'Condiciones de financiacion restrictivas',
  rate_cut_cycle: 'Ciclo de bajadas de tipos', rate_hike_cycle: 'Ciclo de subidas de tipos',
  rate_stable: 'Tipos estables', credit_expansion: 'Expansion del credito',
  credit_contraction: 'Contraccion del credito', credit_stable: 'Credito estable',
  market_stabilizing: 'Mercado estabilizandose', market_uncertain: 'Incertidumbre de mercado',
};

function Sparkline({ points, color = 'stroke-blue-400' }) {
  if (!points || points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const w = 80; const h = 24;
  const path = points.map((v, i) => {
    const x = (i / (points.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${i === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');
  return <svg viewBox={`0 0 ${w} ${h}`} className="w-20 h-6"><path d={path} fill="none" className={color} strokeWidth="1.5" /></svg>;
}

function MacroCard({ indicator, size = 'normal' }) {
  if (!indicator) return null;
  const TrendIcon = TREND_ICONS[indicator.trend_direction] || Minus;
  const trendColor = TREND_COLORS[indicator.trend_direction] || 'text-zinc-400';
  const strength = STRENGTH_OPACITY[indicator.trend_strength] || 'opacity-60';

  const fmtVal = (v, unit) => {
    if (v === null || v === undefined) return 'No disponible';
    if (unit === 'M EUR' || unit === 'M  EUR') return `${(v / 1000).toFixed(0)} MM`;
    if (typeof v === 'number') return v.toFixed(v < 10 ? 3 : v < 100 ? 2 : 0);
    return String(v);
  };

  return (
    <Card className={`bg-zinc-900 border-zinc-800 ${size === 'featured' ? '' : 'opacity-90'}`}>
      <CardContent className={size === 'featured' ? 'p-5' : 'p-4'}>
        <div className="flex items-start justify-between mb-2">
          <div>
            <p className={`text-zinc-500 ${size === 'featured' ? 'text-[10px]' : 'text-[9px]'} uppercase tracking-wider`}>{indicator.indicator_name}</p>
            <div className="flex items-baseline gap-2 mt-1">
              <span className={`font-bold font-mono ${size === 'featured' ? 'text-2xl' : 'text-lg'} text-zinc-100`}>{fmtVal(indicator.value, indicator.unit)}</span>
              <span className="text-[10px] text-zinc-500">{indicator.unit === 'M EUR' || indicator.unit === 'M  EUR' ? 'EUR' : indicator.unit}</span>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className={`flex items-center gap-1 ${trendColor} ${strength}`}>
              <TrendIcon className="w-4 h-4" />
              {indicator.yoy_change_pct != null && <span className="text-[11px] font-mono font-semibold">{indicator.yoy_change_pct > 0 ? '+' : ''}{indicator.yoy_change_pct.toFixed(1)}%</span>}
            </div>
            <Sparkline points={indicator.sparkline_points} color={indicator.trend_direction === 'down' ? 'stroke-rose-400' : indicator.trend_direction === 'up' ? 'stroke-emerald-400' : 'stroke-zinc-500'} />
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[8px] text-zinc-600">{fmtDate(indicator.date)}</span>
          {indicator.semantic && (
            <Badge variant="outline" className={`text-[7px] border-zinc-700 ${
              indicator.semantic.impact?.includes('positive') ? 'text-emerald-400' :
              indicator.semantic.impact?.includes('negative') ? 'text-rose-400' : 'text-zinc-500'
            }`}>{IMPACT_LABELS[indicator.semantic?.impact] || indicator.semantic?.impact}</Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function MacroIntelligencePage() {
  const [data, setData] = useState(null);
  const [signals, setSignals] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get('/public/macro-indicators'),
      api.get('/public/macro/signals'),
    ]).then(([indR, sigR]) => {
      setData(indR.data);
      setSignals(sigR.data);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      // El refresco corre en segundo plano en el backend (tarda > 120 s de proxy si
      // se espera en la propia peticion): lanzamos y consultamos /status.
      await api.post('/admin/data-sources/banco-espana/refresh');
      let st = null;
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 2000));
        st = (await api.get('/admin/data-sources/banco-espana/status')).data;
        if (st.status !== 'running') break;
      }
      if (!st || st.status === 'running') { toast.info('La actualizacion sigue en curso, recarga en unos minutos'); return; }
      if (st.status === 'error') { toast.error(st.last_error || 'Error al actualizar'); return; }
      toast.success('Indicadores actualizados');
      const [indR, sigR] = await Promise.all([api.get('/public/macro-indicators'), api.get('/public/macro/signals')]);
      setData(indR.data); setSignals(sigR.data);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Error al actualizar'); }
    finally { setRefreshing(false); }
  };

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-zinc-400" /></div>;

  const featured = (data?.indicators || []).filter(i => i.homepage);
  const secondary = (data?.indicators || []).filter(i => !i.homepage);
  const ctx = signals?.macro_context;

  // `generated_at` is when the API RESPONSE was built (always "now"), NOT when the
  // underlying Banco de Espana data was last refreshed — showing it next to a clock
  // icon was misleading (looked like a freshness indicator but always said "today").
  // Banco de Espana has no scheduler (manual "Actualizar" only), so real staleness
  // is exactly what's worth surfacing here: the most recent last_updated_at across
  // all indicators actually returned.
  const lastDataUpdate = (data?.indicators || [])
    .map(i => i.last_updated_at).filter(Boolean).sort().slice(-1)[0];

  return (
    <div className="space-y-6" data-testid="macro-intelligence-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-zinc-50 font-heading">Contexto Macro-Financiero</h1>
          <p className="text-xs text-zinc-400">Indicadores oficiales del Banco de Espana — fuente de contexto para valoraciones y financiacion</p>
        </div>
        <div className="flex items-center gap-3">
          {data?.response_time_ms && <span className="text-[9px] text-zinc-600">{data.response_time_ms}ms</span>}
          <span className="text-[10px] text-zinc-500 flex items-center gap-1" title="Fecha del dato mas reciente del Banco de Espana (no hay sincronizacion automatica, solo el boton Actualizar)">
            <Clock className="w-3 h-3" />Datos al {fmtDate(lastDataUpdate)}
          </span>
          <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-[10px]" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}Actualizar
          </Button>
        </div>
      </div>

      {/* Empty state */}
      {featured.length === 0 && secondary.length === 0 && !loading && (
        <Card className="bg-zinc-900 border-zinc-800">
          <CardContent className="p-8 text-center">
            <p className="text-sm text-zinc-300 mb-2">Indicadores no disponibles</p>
            <p className="text-xs text-zinc-500 mb-4">Los datos del Banco de Espana no se han cargado todavia. Pulsa "Actualizar" para sincronizar por primera vez.</p>
            <Button size="sm" className="bg-blue-600 hover:bg-blue-500 text-white" onClick={handleRefresh} disabled={refreshing}>
              {refreshing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}Cargar indicadores del Banco de Espana
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Macro Context Summary */}
      {ctx && featured.length > 0 && (
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-4">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-zinc-500" />
                <span className="text-[11px] text-zinc-300 font-medium">Contexto macro</span>
              </div>
              <Badge variant="outline" className={`text-[9px] ${ctx.financing_conditions === 'improving' ? 'text-emerald-400 border-emerald-500/20' : ctx.financing_conditions === 'tightening' ? 'text-rose-400 border-rose-500/20' : 'text-zinc-400 border-zinc-700'}`}>
                Financiacion: {ctx.financing_conditions === 'improving' ? 'mejorando' : ctx.financing_conditions === 'tightening' ? 'restrictiva' : 'estable'}
              </Badge>
              <Badge variant="outline" className="text-[9px] text-zinc-400 border-zinc-700">Tipos: {ctx.interest_rate_trend === 'declining' ? 'bajando' : ctx.interest_rate_trend === 'rising' ? 'subiendo' : 'estables'}</Badge>
              <Badge variant="outline" className="text-[9px] text-zinc-400 border-zinc-700">Valoraciones: {ctx.valuation_pressure === 'supportive' ? 'favorable' : ctx.valuation_pressure === 'compressing' ? 'presion' : 'neutral'}</Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Featured Indicators */}
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold mb-3">Indicadores principales</p>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {featured.map(ind => <MacroCard key={ind.indicator_key} indicator={ind} size="featured" />)}
        </div>
      </div>

      {/* Secondary */}
      {secondary.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold mb-3">Indicadores secundarios</p>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {secondary.map(ind => <MacroCard key={ind.indicator_key} indicator={ind} size="normal" />)}
          </div>
        </div>
      )}

      {/* Signals */}
      {signals?.signals?.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold mb-3">Senales semanticas</p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {signals.signals.map(sig => (
              <Card key={sig.indicator_key} className="bg-zinc-900/30 border-zinc-800">
                <CardContent className="p-3 flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${sig.impact?.includes('positive') ? 'bg-emerald-500' : sig.impact?.includes('negative') ? 'bg-rose-500' : 'bg-zinc-500'}`} />
                  <div className="flex-1">
                    <p className="text-[11px] text-zinc-200">{sig.indicator_name}</p>
                    <p className="text-[9px] text-zinc-500">{SIGNAL_LABELS[sig.signal] || sig.signal}</p>
                  </div>
                  <div className="flex gap-1">
                    {sig.tags?.slice(0, 3).map(tag => <Badge key={tag} variant="outline" className="text-[7px] text-zinc-500 border-zinc-700">{tag}</Badge>)}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Source */}
      <p className="text-[8px] text-zinc-600 text-center">Fuente: {data?.source_attribution} · v{data?.contract_version}</p>
    </div>
  );
}
