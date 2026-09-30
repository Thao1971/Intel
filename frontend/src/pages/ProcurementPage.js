import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Progress } from '@/components/ui/progress';
import { Loader2, FileText, Building2, Users, DollarSign, CheckCircle2, AlertTriangle, BarChart3, Layers, Clock, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

function fmtEur(v) {
  if (!v && v !== 0) return '—';
  if (Math.abs(v) >= 1e9) return `${(v/1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `${(v/1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v/1e3).toFixed(0)}K`;
  return v.toLocaleString('es-ES');
}
function fmtNum(v) { return v != null ? Math.round(v).toLocaleString('es-ES') : '—'; }
function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('es-ES', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}); } catch { return iso.substring(0,10); }
}

const TYPE_LABELS = { servicios: 'Servicios', suministros: 'Suministros', obras: 'Obras', concesion_obras: 'Concesion obras', gestion_servicios: 'Gestion servicios', sin_tipo: 'Sin clasificar' };
const TYPE_COLORS = { servicios: 'bg-blue-500', suministros: 'bg-emerald-500', obras: 'bg-amber-500', concesion_obras: 'bg-violet-500', gestion_servicios: 'bg-cyan-500', sin_tipo: 'bg-zinc-600' };
const INTEGRATION_TARGETS = [
  { name: 'Economic Intelligence', desc: '32 metricas de contratacion por CNAE', status: 'active' },
  { name: 'Sector Intelligence', desc: 'activity_score incluye contratacion publica', status: 'active' },
  { name: 'Geo Intelligence', desc: 'Contratos por territorio (preparado)', status: 'prepared' },
  { name: 'Sector x Geo', desc: 'Cruce sectorial-territorial', status: 'active' },
  { name: 'Companies Master', desc: 'Match adjudicatario por NIF', status: 'limited' },
  { name: 'Universal Search', desc: 'Busqueda de contratos (futuro)', status: 'planned' },
];

export default function ProcurementPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = () => api.get('/public-procurement/overview').then(r => setData(r.data)).catch(() => {}).finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      let { data: result } = await api.post('/public-procurement/sync-placsp');
      if (result.status === 'running') {
        // Corre en segundo plano en el backend: consultamos el estado (max 15 min)
        let st = null;
        for (let i = 0; i < 300; i++) {
          await new Promise(r => setTimeout(r, 3000));
          st = (await api.get('/public-procurement/sync-placsp-state')).data;
          if (st.status !== 'running') break;
        }
        if (!st || st.status === 'running') {
          toast.info('El sync de PLACSP sigue en curso, recarga en unos minutos');
          return;
        }
        result = st.result || {};
      }
      if (result.status === 'error') {
        toast.error('Error sincronizando PLACSP: ' + (result.message || (result.errors || []).join(', ')));
      } else {
        toast.success(`PLACSP sincronizado: ${result.imported ?? result.total_imported ?? 0} contratos importados`);
      }
      await load();
    } catch (e) {
      toast.error('Error sincronizando PLACSP');
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-zinc-500" /></div>;
  }

  const d = data || {};
  const total = d.total_contracts || 0;

  return (
    <div className="space-y-5" data-testid="procurement-page">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-zinc-100">Contratacion Publica (PLACSP)</h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            Plataforma de Contratacion del Sector Publico — Contratos menores, formato CODICE 2.07
          </p>
          {d.last_sync && (
            <div className="flex items-center gap-2 mt-1.5">
              <Clock className="w-3 h-3 text-zinc-600" />
              <span className="text-[10px] text-zinc-500">Ultima sincronizacion: {fmtDate(d.last_sync?.synced_at)}</span>
              <span className="text-[10px] text-zinc-600">Fuente: {d.last_sync?.source || 'PLACSP'}</span>
            </div>
          )}
        </div>
        <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-300 h-7 text-[10px] shrink-0"
          onClick={handleSync} disabled={syncing}>
          {syncing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1" />}
          Sincronizar PLACSP
        </Button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <FileText className="w-4 h-4 text-zinc-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums" data-testid="proc-total">{fmtNum(total)}</p>
            <p className="text-[10px] text-zinc-500">Contratos</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <DollarSign className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-emerald-400 tabular-nums">{fmtEur(d.total_amount_eur)}</p>
            <p className="text-[10px] text-zinc-500">Importe adjudicado</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Users className="w-4 h-4 text-blue-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums">{fmtNum(d.unique_adjudicatarios)}</p>
            <p className="text-[10px] text-zinc-500">Adjudicatarios unicos</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Building2 className="w-4 h-4 text-violet-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums">{fmtNum(d.unique_compradores)}</p>
            <p className="text-[10px] text-zinc-500">Organismos publicos</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-emerald-400 tabular-nums">{d.contracts_with_nif_pct || 0}%</p>
            <p className="text-[10px] text-zinc-500">NIF identificable</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <BarChart3 className="w-4 h-4 text-amber-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-amber-400 tabular-nums">{d.economic_intelligence?.metrics || 0}</p>
            <p className="text-[10px] text-zinc-500">Metricas economicas</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Distribucion tipo contrato */}
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-zinc-400">Distribucion por tipo de contrato</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(d.contract_types || []).filter(t => t.count > 10).map(t => {
              const pct = total > 0 ? (t.count / total * 100) : 0;
              const color = TYPE_COLORS[t.type] || 'bg-zinc-600';
              return (
                <div key={t.type}>
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-xs text-zinc-300">{TYPE_LABELS[t.type] || t.type}</span>
                    <span className="text-[10px] text-zinc-500 tabular-nums">{fmtNum(t.count)} ({pct.toFixed(1)}%) — {fmtEur(t.amount)}</span>
                  </div>
                  <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Cobertura empresarial */}
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-zinc-400">Cobertura empresarial</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-zinc-300">Contratos con NIF identificado</span>
                <span className="text-xs text-emerald-400 tabular-nums">{fmtNum(d.contracts_with_nif)} ({d.contracts_with_nif_pct}%)</span>
              </div>
              <div className="w-full h-2 bg-zinc-800 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${d.contracts_with_nif_pct || 0}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-zinc-800/30 rounded-lg p-2.5">
                <p className="text-lg font-bold text-blue-400 tabular-nums">{fmtNum(d.empresas_sa_sl)}</p>
                <p className="text-[10px] text-zinc-500">Empresas SA/SL detectadas</p>
              </div>
              <div className="bg-zinc-800/30 rounded-lg p-2.5">
                <p className="text-lg font-bold text-zinc-400 tabular-nums">{fmtNum(d.personas_fisicas)}</p>
                <p className="text-[10px] text-zinc-500">Personas fisicas</p>
              </div>
            </div>
            <div className="bg-zinc-800/30 rounded-lg p-2.5">
              <p className="text-lg font-bold text-zinc-500 tabular-nums">{fmtNum(total - (d.contracts_with_nif || 0))}</p>
              <p className="text-[10px] text-zinc-500">Contratos sin NIF adjudicatario</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Cobertura sectorial (Top CPV) */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-zinc-400">Cobertura sectorial — Top CPV por volumen</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1.5">
            {(d.top_cpv || []).map(c => {
              const maxCount = d.top_cpv?.[0]?.count || 1;
              const pct = (c.count / maxCount) * 100;
              return (
                <div key={c.cpv} className="flex items-center gap-3">
                  <span className="text-xs font-mono text-zinc-500 w-8">{c.cpv}</span>
                  <div className="flex-1">
                    <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div className="h-full bg-violet-500/70 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <span className="text-[10px] text-zinc-400 tabular-nums w-20 text-right">{fmtNum(c.count)}</span>
                  <span className="text-[10px] text-zinc-500 tabular-nums w-16 text-right">{fmtEur(c.amount)}</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Calidad de datos */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-zinc-400">Calidad de datos — Cobertura por campo</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-zinc-800 hover:bg-transparent">
                <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Campo</TableHead>
                <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">Registros</TableHead>
                <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 text-right">Cobertura</TableHead>
                <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500 w-40">Barra</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(d.field_coverage || {}).map(([field, info]) => {
                const pct = info.pct || 0;
                const color = pct >= 95 ? 'bg-emerald-500' : pct >= 70 ? 'bg-amber-500' : 'bg-rose-500';
                const fieldLabels = {
                  expediente: 'Expediente', cpv_code: 'Codigo CPV', contract_type: 'Tipo contrato',
                  award_date: 'Fecha adjudicacion', publication_date: 'Fecha publicacion',
                  buyer_name: 'Comprador (nombre)', buyer_nif: 'Comprador (NIF)', buyer_city: 'Ciudad comprador',
                  awardee_name: 'Adjudicatario (nombre)', awardee_tax_id: 'Adjudicatario (NIF)', amount: 'Importe',
                };
                return (
                  <TableRow key={field} className="border-zinc-800/50">
                    <TableCell className="py-1.5 text-xs text-zinc-300">{fieldLabels[field] || field}</TableCell>
                    <TableCell className="py-1.5 text-xs text-zinc-400 tabular-nums text-right">{fmtNum(info.count)}</TableCell>
                    <TableCell className="py-1.5 text-xs tabular-nums text-right">
                      <span className={pct >= 95 ? 'text-emerald-400' : pct >= 70 ? 'text-amber-400' : 'text-rose-400'}>{pct}%</span>
                    </TableCell>
                    <TableCell className="py-1.5">
                      <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Integracion con la plataforma */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs text-zinc-400 flex items-center gap-2">
            <Layers className="w-3.5 h-3.5 text-zinc-500" /> Integracion con la plataforma
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {INTEGRATION_TARGETS.map(t => (
              <div key={t.name} className="flex items-center gap-2 bg-zinc-800/30 rounded-lg p-2.5">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  t.status === 'active' ? 'bg-emerald-500' : t.status === 'prepared' ? 'bg-amber-500' : t.status === 'limited' ? 'bg-zinc-500' : 'bg-zinc-700'
                }`} />
                <div>
                  <p className="text-xs text-zinc-200">{t.name}</p>
                  <p className="text-[9px] text-zinc-500">{t.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
