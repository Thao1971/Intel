import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Loader2, RefreshCw, TrendingUp, Building2, BarChart3, Clock } from 'lucide-react';
import { toast } from 'sonner';

function fmtCap(v) {
  if (!v) return '—';
  if (v >= 1e9) return `${(v/1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v/1e6).toFixed(1)}M`;
  return `${(v/1e3).toFixed(0)}K`;
}

export default function BMEPage() {
  const [data, setData] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [dashRes, compRes] = await Promise.all([
        api.get('/bme-markets/dashboard'),
        api.get('/bme-markets/companies?limit=100'),
      ]);
      setData(dashRes.data);
      setCompanies(compRes.data?.companies || []);
    } catch { /* empty */ }
    setLoading(false);
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      let { data: r } = await api.post('/bme-markets/sync');
      if (r.status === 'running') {
        // Corre en segundo plano en el backend: consultamos el estado (max 10 min)
        let st = null;
        for (let i = 0; i < 200; i++) {
          await new Promise(res => setTimeout(res, 3000));
          st = (await api.get('/bme-markets/sync-state')).data;
          if (st.status !== 'running') break;
        }
        if (!st || st.status === 'running') {
          toast.info('El sync de BME sigue en curso, recarga en unos minutos');
          setSyncing(false);
          return;
        }
        r = st.result || {};
      }
      if (r.status === 'error') {
        toast.error(`Error sincronizando BME: ${r.message || 'fallo desconocido'}`);
      } else if (r.status === 'partial') {
        toast.success(`BME: ${r.total_imported} nuevas, ${r.total_updated} actualizadas (con avisos)`);
      } else {
        toast.success(`BME: ${r.total_imported} nuevas, ${r.total_updated} actualizadas`);
      }
      loadData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error sincronizando BME');
    }
    setSyncing(false);
  };

  const kpis = data?.kpis || {};
  const signals = data?.signals || [];

  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-zinc-500" /></div>;

  return (
    <div className="space-y-4" data-testid="bme-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-zinc-100">BME Markets</h1>
          <p className="text-xs text-zinc-500 mt-0.5">Companias cotizadas — BME Growth + BME Scaleup</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}
          className="border-zinc-700 text-zinc-300 h-7 text-xs" data-testid="sync-bme-btn">
          {syncing ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1.5" />}
          Sincronizar
        </Button>
      </div>

      {/* Sync status */}
      <div className="flex items-center gap-3 bg-zinc-900/40 border border-zinc-800/50 rounded-lg px-3 py-2">
        <Clock className="w-3.5 h-3.5 text-zinc-600" />
        <span className="text-xs text-zinc-400">Ultima sync:</span>
        <span className="text-xs text-zinc-200">
          {kpis.last_sync?.synced_at ? new Date(kpis.last_sync.synced_at).toLocaleDateString('es-ES', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Nunca — ejecutar Sincronizar'}
        </span>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-5 gap-3">
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Building2 className="w-4 h-4 text-zinc-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums" data-testid="bme-total">{kpis.total || 0}</p>
            <p className="text-[10px] text-zinc-500">Companias</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <TrendingUp className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-emerald-400 tabular-nums">{kpis.growth || 0}</p>
            <p className="text-[10px] text-zinc-500">BME Growth</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <TrendingUp className="w-4 h-4 text-blue-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-blue-400 tabular-nums">{kpis.scaleup || 0}</p>
            <p className="text-[10px] text-zinc-500">BME Scaleup</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Building2 className="w-4 h-4 text-violet-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-violet-400 tabular-nums">{kpis.principal || 0}</p>
            <p className="text-[10px] text-zinc-500">BME Principal</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <BarChart3 className="w-4 h-4 text-amber-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums">{fmtCap(kpis.market_cap?.total)}</p>
            <p className="text-[10px] text-zinc-500">Cap. total</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">Top sectores</p>
            <div className="space-y-0.5">
              {(kpis.by_sector || []).slice(0, 4).map((s, i) => (
                <div key={i} className="flex items-center justify-between text-[10px]">
                  <span className="text-zinc-400 truncate max-w-[100px]">{s.sector}</span>
                  <span className="text-zinc-300 tabular-nums">{s.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Signals */}
      {signals.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {signals.map((s, i) => (
            <div key={i} className="px-2.5 py-1.5 rounded-lg border border-zinc-800/50 bg-indigo-500/10">
              <span className="text-[10px] font-medium text-indigo-400">{s.signal_type}</span>
              <p className="text-[9px] text-zinc-500">{s.description}</p>
            </div>
          ))}
        </div>
      )}

      {/* Companies table */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-zinc-400">Companias cotizadas ({companies.length})</CardTitle>
        </CardHeader>
        <Table>
          <TableHeader>
            <TableRow className="border-zinc-800 hover:bg-transparent">
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Empresa</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">ISIN</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Mercado</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Sector</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">Capitalizacion</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">% Ano</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {companies.map((c, i) => (
              <TableRow key={c.isin || i} className="border-zinc-800/50">
                <TableCell className="py-1.5">
                  <span className="text-xs text-zinc-200">{c.company_name}</span>
                  {c.website && <a href={c.website.startsWith('http') ? c.website : `https://${c.website}`} target="_blank" rel="noopener noreferrer" className="text-[8px] text-blue-400 ml-1.5">web</a>}
                </TableCell>
                <TableCell className="py-1.5 text-[10px] font-mono text-zinc-500">{c.isin}</TableCell>
                <TableCell className="py-1.5">
                  <Badge variant="outline" className={`text-[8px] px-1 py-0 ${c.listed_in_bme_principal ? 'text-violet-400 border-violet-500/20' : c.listed_in_growth ? 'text-emerald-400 border-emerald-500/20' : 'text-blue-400 border-blue-500/20'}`}>
                    {c.listed_in_bme_principal ? 'Principal' : c.listed_in_growth ? 'Growth' : 'Scaleup'}
                  </Badge>
                </TableCell>
                <TableCell className="py-1.5 text-[10px] text-zinc-400 truncate max-w-[120px]">{c.sector}</TableCell>
                <TableCell className="py-1.5 text-xs text-zinc-100 tabular-nums text-right">{fmtCap(c.market_cap)}</TableCell>
                <TableCell className="py-1.5 text-xs tabular-nums text-right">
                  {c.annual_performance != null ? (
                    <span className={c.annual_performance >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      {c.annual_performance >= 0 ? '+' : ''}{c.annual_performance?.toFixed(1)}%
                    </span>
                  ) : '—'}
                </TableCell>
              </TableRow>
            ))}
            {companies.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center text-xs text-zinc-600 py-8">
                Sin datos. Ejecuta Sincronizar para importar companias de BME.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
