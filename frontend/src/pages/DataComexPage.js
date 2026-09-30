import { useState, useEffect, useCallback } from 'react';
import api from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, RefreshCw, TrendingUp, TrendingDown, Minus, Upload, BarChart3, ArrowRightLeft, AlertTriangle, Clock } from 'lucide-react';
import { toast } from 'sonner';

function fmtEur(v) {
  if (!v && v !== 0) return '—';
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toFixed(0);
}

function fmtPct(v) {
  if (v === null || v === undefined) return '—';
  const color = v > 0 ? 'text-emerald-400' : v < 0 ? 'text-rose-400' : 'text-zinc-400';
  return <span className={`${color} tabular-nums`}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>;
}

const SIGNAL_CONFIG = {
  export_boom: { label: 'Export Boom', color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20', icon: TrendingUp },
  export_decline: { label: 'Export Decline', color: 'bg-rose-500/15 text-rose-400 border-rose-500/20', icon: TrendingDown },
  trend_reversal_positive: { label: 'Reversion positiva', color: 'bg-blue-500/15 text-blue-400 border-blue-500/20', icon: TrendingUp },
  trend_reversal_negative: { label: 'Reversion negativa', color: 'bg-amber-500/15 text-amber-400 border-amber-500/20', icon: TrendingDown },
};

export default function DataComexPage() {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState('dashboard');

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/datacomex/dashboard');
      setDashboard(data);
    } catch (e) {
      toast.error('Error cargando DataComex');
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      // OJO: el backend devuelve { sync: {...}, rebuild: {...} } anidado, no
      // los campos en el nivel superior. Leer data.records_imported directamente
      // siempre daba "undefined" — daba igual si el sync habia funcionado o no.
      let { data } = await api.post('/datacomex/sync?years=2022,2023,2024,2025');
      if (data.status === 'running') {
        // El sync corre en segundo plano en el backend: consultamos /sync-state (max 10 min)
        let st = null;
        for (let i = 0; i < 200; i++) {
          await new Promise(r => setTimeout(r, 3000));
          st = (await api.get('/datacomex/sync-state')).data;
          if (st.status !== 'running') break;
        }
        if (!st || st.status === 'running') {
          toast.info('El sync de DataComex sigue en curso, recarga en unos minutos');
          setSyncing(false);
          return;
        }
        data = st.result || {};
      }
      const s = data.sync || {};
      if (s.status === 'error') {
        toast.error(`Error sincronizando DataComex: ${s.error || 'fallo desconocido'}`);
      } else if (s.status === 'unchanged') {
        toast.success('DataComex ya estaba actualizado (sin cambios)');
      } else {
        toast.success(`Sync: ${s.records ?? s.records_imported ?? 0} registros importados`);
      }
      loadDashboard();
    } catch (e) {
      toast.error('Error sincronizando DataComex');
    }
    setSyncing(false);
  };

  const handleRebuildMetrics = async () => {
    try {
      const { data } = await api.post('/datacomex/rebuild-metrics');
      toast.success(`Metricas: ${data.metrics_computed} calculadas`);
      loadDashboard();
    } catch { toast.error('Error recalculando metricas'); }
  };

  const handleRebuildSignals = async () => {
    try {
      const { data } = await api.post('/datacomex/rebuild-signals');
      toast.success(`Senales: ${data.signals_generated} generadas`);
      loadDashboard();
    } catch { toast.error('Error generando senales'); }
  };

  const handleUploadCSV = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      const { data } = await api.post('/datacomex/upload-csv', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.status === 'error') {
        toast.error(`Error en el CSV: ${data.message || 'formato no reconocido'}`);
      } else {
        toast.success(`CSV: ${data.records_imported ?? 0} registros importados`);
      }
      loadDashboard();
    } catch { toast.error('Error procesando CSV'); }
    e.target.value = '';
  };

  const kpis = dashboard?.kpis || {};
  const lastSync = dashboard?.last_sync || {};

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="datacomex-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-zinc-100">DataComex Intelligence</h1>
          <p className="text-xs text-zinc-500 mt-0.5">Comercio exterior espanol — Ministerio de Industria</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="cursor-pointer">
            <input type="file" accept=".csv" onChange={handleUploadCSV} className="hidden" data-testid="csv-upload-input" />
            <span className="inline-flex items-center px-2.5 py-1.5 rounded border border-zinc-700 text-zinc-300 text-xs hover:bg-zinc-800 transition-colors">
              <Upload className="w-3 h-3 mr-1.5" /> Subir CSV
            </span>
          </label>
          <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}
            className="border-zinc-700 text-zinc-300 h-7 text-xs" data-testid="sync-datacomex-btn">
            {syncing ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1.5" />}
            Sincronizar
          </Button>
        </div>
      </div>

      {/* Last sync info */}
      <div className="flex items-center gap-3 bg-zinc-900/40 border border-zinc-800/50 rounded-lg px-3 py-2">
        {lastSync.status === 'completed' || lastSync.status === 'partial' ? (
          <Clock className="w-3.5 h-3.5 text-emerald-500" />
        ) : (
          <AlertTriangle className="w-3.5 h-3.5 text-zinc-600" />
        )}
        <span className="text-xs text-zinc-400">Ultima sync:</span>
        <span className="text-xs text-zinc-200">{lastSync.synced_at ? new Date(lastSync.synced_at).toLocaleDateString('es-ES', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Nunca'}</span>
        {lastSync.records_imported > 0 && (
          <span className="text-[10px] text-zinc-500">{lastSync.records_imported.toLocaleString('es-ES')} registros</span>
        )}
        <Badge variant="outline" className="text-[9px] px-1.5 py-0 text-zinc-400 border-zinc-600">
          {lastSync.trigger === 'auto' ? 'Auto' : lastSync.trigger === 'manual' ? 'Manual' : 'Mensual'}
        </Badge>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-zinc-900 border border-zinc-800">
          <TabsTrigger value="dashboard" className="text-xs data-[state=active]:bg-zinc-800">Dashboard</TabsTrigger>
          <TabsTrigger value="signals" className="text-xs data-[state=active]:bg-zinc-800">Senales</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="mt-3 space-y-4">
          {/* KPIs */}
          <div className="grid grid-cols-4 gap-3">
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1"><TrendingUp className="w-3.5 h-3.5 text-emerald-400" /><span className="text-[10px] uppercase tracking-wider text-zinc-500">Exportaciones {kpis.latest_year}</span></div>
                <p className="text-xl font-bold text-emerald-400 tabular-nums" data-testid="total-exports">{fmtEur(kpis.total_exports_eur)}</p>
              </CardContent>
            </Card>
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1"><TrendingDown className="w-3.5 h-3.5 text-rose-400" /><span className="text-[10px] uppercase tracking-wider text-zinc-500">Importaciones {kpis.latest_year}</span></div>
                <p className="text-xl font-bold text-rose-400 tabular-nums" data-testid="total-imports">{fmtEur(kpis.total_imports_eur)}</p>
              </CardContent>
            </Card>
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1"><ArrowRightLeft className="w-3.5 h-3.5 text-blue-400" /><span className="text-[10px] uppercase tracking-wider text-zinc-500">Saldo comercial</span></div>
                <p className={`text-xl font-bold tabular-nums ${(kpis.trade_balance_eur || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`} data-testid="trade-balance">
                  {fmtEur(kpis.trade_balance_eur)}
                </p>
              </CardContent>
            </Card>
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 mb-1"><BarChart3 className="w-3.5 h-3.5 text-zinc-400" /><span className="text-[10px] uppercase tracking-wider text-zinc-500">Senales activas</span></div>
                <p className="text-xl font-bold text-zinc-100 tabular-nums" data-testid="signals-count">{kpis.signals_active || 0}</p>
              </CardContent>
            </Card>
          </div>

          {/* Top Growing */}
          <div className="grid grid-cols-2 gap-3">
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardHeader className="pb-2"><CardTitle className="text-xs text-emerald-400">Mayor crecimiento export</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableBody>
                    {(dashboard?.top_growing_cnae || []).map((m, i) => (
                      <TableRow key={i} className="border-zinc-800/50">
                        <TableCell className="py-1.5 text-xs font-mono text-zinc-500 w-8">{m.taric_code}</TableCell>
                        <TableCell className="py-1.5 text-xs text-zinc-300 truncate max-w-[200px]">{m.taric_label}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmtPct(m.export_yoy_pct)}</TableCell>
                      </TableRow>
                    ))}
                    {!(dashboard?.top_growing_cnae?.length) && (
                      <TableRow><TableCell colSpan={3} className="text-center text-xs text-zinc-600 py-4">Sin datos. Ejecuta Sincronizar.</TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
            <Card className="bg-zinc-900/50 border-zinc-800">
              <CardHeader className="pb-2"><CardTitle className="text-xs text-rose-400">Mayor deterioro export</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableBody>
                    {(dashboard?.top_declining_cnae || []).map((m, i) => (
                      <TableRow key={i} className="border-zinc-800/50">
                        <TableCell className="py-1.5 text-xs font-mono text-zinc-500 w-8">{m.taric_code}</TableCell>
                        <TableCell className="py-1.5 text-xs text-zinc-300 truncate max-w-[200px]">{m.taric_label}</TableCell>
                        <TableCell className="py-1.5 text-right">{fmtPct(m.export_yoy_pct)}</TableCell>
                      </TableRow>
                    ))}
                    {!(dashboard?.top_declining_cnae?.length) && (
                      <TableRow><TableCell colSpan={3} className="text-center text-xs text-zinc-600 py-4">Sin datos.</TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>

          {/* Admin actions */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleRebuildMetrics} className="border-zinc-700 text-zinc-400 h-7 text-xs">
              Recalcular metricas
            </Button>
            <Button variant="outline" size="sm" onClick={handleRebuildSignals} className="border-zinc-700 text-zinc-400 h-7 text-xs">
              Regenerar senales
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="signals" className="mt-3">
          <Card className="bg-zinc-900/50 border-zinc-800">
            <Table>
              <TableHeader>
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">TARIC</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Senal</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Descripcion</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">Export YoY</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">Ano</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(dashboard?.signals || []).map((s, i) => {
                  const cfg = SIGNAL_CONFIG[s.signal_type] || { label: s.signal_type, color: 'bg-zinc-500/15 text-zinc-400', icon: Minus };
                  const SIcon = cfg.icon;
                  return (
                    <TableRow key={i} className="border-zinc-800/50">
                      <TableCell className="py-2">
                        <span className="text-xs font-mono text-zinc-500">{s.taric_code}</span>
                        <span className="text-xs text-zinc-400 ml-2">{s.taric_label?.substring(0, 30)}</span>
                      </TableCell>
                      <TableCell className="py-2">
                        <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${cfg.color}`}>
                          <SIcon className="w-2.5 h-2.5 mr-1" />{cfg.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="py-2 text-xs text-zinc-400 max-w-[250px] truncate">{s.description}</TableCell>
                      <TableCell className="py-2 text-right">{fmtPct(s.export_yoy_pct)}</TableCell>
                      <TableCell className="py-2 text-right text-xs text-zinc-500">{s.year}</TableCell>
                    </TableRow>
                  );
                })}
                {!(dashboard?.signals?.length) && (
                  <TableRow><TableCell colSpan={5} className="text-center text-xs text-zinc-600 py-8">Sin senales. Sincroniza datos y recalcula.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
