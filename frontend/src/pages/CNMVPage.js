import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, RefreshCw, Building2, TrendingUp, Users, Clock, Star, Info, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';

const MNA_STARS = { 5: 'text-amber-400', 4: 'text-amber-400', 3: 'text-zinc-400', 2: 'text-zinc-600', 1: 'text-zinc-700' };

function MnaRelevance({ level }) {
  if (!level) return null;
  return (
    <div className="flex items-center gap-0.5">
      {[1,2,3,4,5].map(i => (
        <Star key={i} className={`w-2.5 h-2.5 ${i <= level ? MNA_STARS[level] || 'text-zinc-600' : 'text-zinc-800'}`}
          fill={i <= level ? 'currentColor' : 'none'} />
      ))}
    </div>
  );
}

function CatalogCard({ item }) {
  return (
    <Card className="bg-zinc-900/50 border-zinc-800">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs px-2 py-0.5 text-violet-400 border-violet-500/20 font-mono">{item.code}</Badge>
            <span className="text-sm font-semibold text-zinc-100">{item.name}</span>
          </div>
          <MnaRelevance level={item.mna_relevance} />
        </div>
        <p className="text-xs text-zinc-400 mb-2">{item.short_description}</p>
        <p className="text-[11px] text-zinc-500 mb-3">{item.long_description}</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-zinc-600">M&A:</span>
            <span className="text-zinc-300">{item.mna_label}</span>
          </div>
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-zinc-600">Caso de uso:</span>
            <span className="text-zinc-400">{item.example_use_case}</span>
          </div>
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-zinc-600">Tipo:</span>
            <Badge variant="outline" className={`text-[9px] px-1.5 py-0 ${item.category === 'vehicle' ? 'text-blue-400 border-blue-500/20' : 'text-emerald-400 border-emerald-500/20'}`}>
              {item.category === 'vehicle' ? 'Vehiculo de inversion' : 'Gestora / Intermediario'}
            </Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function CNMVPage() {
  const [data, setData] = useState(null);
  const [entities, setEntities] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState('dashboard');
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState(null);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [dashRes, catRes] = await Promise.all([
        api.get('/cnmv/dashboard'),
        api.get('/cnmv/catalog'),
      ]);
      setData(dashRes.data);
      setCatalog(catRes.data?.catalog || []);
    } catch { /* empty state */ }
    setLoading(false);
  };

  const loadEntities = async (type = null, search = '') => {
    try {
      let params = 'limit=50';
      if (type) params += `&entity_type=${type}`;
      if (search) params += `&search=${encodeURIComponent(search)}`;
      const { data: res } = await api.get(`/cnmv/entities?${params}`);
      setEntities(res?.entities || []);
    } catch { setEntities([]); }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data: r } = await api.post('/cnmv/sync?types=fcr,scr');
      // El backend ahora devuelve un error HTTP real si el sync falla (antes
      // respondia 200 OK con status:"error" y esto mostraba "CNMV: undefined
      // entidades" como si fuera un exito), pero comprobamos igualmente por si
      // acaso llega un status:"partial" con avisos.
      if (r.status === 'error') {
        toast.error(`Error sincronizando CNMV: ${r.message || 'fallo desconocido'}`);
      } else if (r.status === 'partial') {
        toast.success(`CNMV: ${r.total_imported} entidades (con avisos, ver logs)`);
      } else {
        toast.success(`CNMV: ${r.total_imported} entidades`);
      }
      loadData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error sincronizando CNMV');
    }
    setSyncing(false);
  };

  const handleMatch = async () => {
    try {
      const { data: r } = await api.post('/cnmv/match-companies');
      toast.success(`Match: ${r.matched} de ${r.total_checked} (${r.match_rate_pct}%)`);
      loadData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Error matching'); }
  };

  const kpis = data?.kpis || {};
  const signals = data?.signals || [];
  const byType = kpis.by_type || {};

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-5 h-5 animate-spin text-zinc-500" /></div>;
  }

  return (
    <div className="space-y-4" data-testid="cnmv-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-zinc-100">CNMV Intelligence</h1>
          <p className="text-xs text-zinc-500 mt-0.5">Mapa de inversores, gestoras y vehiculos financieros de Espana</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleMatch} className="border-zinc-700 text-zinc-300 h-7 text-xs">
            Match empresas
          </Button>
          <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}
            className="border-zinc-700 text-zinc-300 h-7 text-xs" data-testid="sync-cnmv-btn">
            {syncing ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1.5" />}
            Sincronizar
          </Button>
        </div>
      </div>

      {/* Sync status */}
      <div className="flex items-center gap-3 bg-zinc-900/40 border border-zinc-800/50 rounded-lg px-3 py-2">
        <Clock className="w-3.5 h-3.5 text-zinc-600" />
        <span className="text-xs text-zinc-400">Ultima sync:</span>
        <span className="text-xs text-zinc-200">
          {kpis.last_sync?.synced_at ? new Date(kpis.last_sync.synced_at).toLocaleDateString('es-ES', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Nunca'}
        </span>
        {kpis.matched_to_companies > 0 && (
          <span className="text-[10px] text-emerald-400">{kpis.matched_to_companies} vinculadas a companies_master</span>
        )}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-5 gap-3">
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Building2 className="w-4 h-4 text-zinc-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-zinc-100 tabular-nums" data-testid="cnmv-total">{kpis.total_entities || 0}</p>
            <p className="text-[10px] text-zinc-500">Entidades CNMV</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <TrendingUp className="w-4 h-4 text-blue-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-blue-400 tabular-nums">{kpis.funds_vehicles || 0}</p>
            <p className="text-[10px] text-zinc-500">Vehiculos inversion</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <Users className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
            <p className="text-xl font-bold text-emerald-400 tabular-nums">{kpis.managers || 0}</p>
            <p className="text-[10px] text-zinc-500">Gestoras / ESI</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3 text-center">
            <p className="text-xl font-bold text-amber-400 tabular-nums">{kpis.vehicles_per_manager || 0}</p>
            <p className="text-[10px] text-zinc-500">Vehiculos / gestora</p>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardContent className="p-3">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">Top tipos</p>
            <div className="space-y-0.5">
              {Object.entries(byType).sort((a,b) => b[1]-a[1]).slice(0, 5).map(([t, c]) => {
                const info = catalog.find(cat => cat.entity_type === t);
                return (
                  <div key={t} className="flex items-center justify-between text-[10px]">
                    <span className="text-zinc-400">{info?.code || t}</span>
                    <span className="text-zinc-300 tabular-nums">{c}</span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs value={tab} onValueChange={(v) => {
        setTab(v);
        if (v === 'entities') loadEntities(filterType, searchTerm);
      }}>
        <TabsList className="bg-zinc-900 border border-zinc-800">
          <TabsTrigger value="dashboard" className="text-xs data-[state=active]:bg-zinc-800">Senales</TabsTrigger>
          <TabsTrigger value="catalog" className="text-xs data-[state=active]:bg-zinc-800">Que es cada entidad</TabsTrigger>
          <TabsTrigger value="entities" className="text-xs data-[state=active]:bg-zinc-800">Entidades ({kpis.total_entities || 0})</TabsTrigger>
          <TabsTrigger value="confidence" className="text-xs data-[state=active]:bg-zinc-800">Calidad y procedencia</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="mt-3">
          {signals.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {signals.map((s, i) => (
                <div key={i} className="px-2.5 py-1.5 rounded-lg border border-zinc-800/50 bg-violet-500/10">
                  <span className="text-[10px] font-medium text-violet-400">{s.signal_type}</span>
                  <p className="text-[9px] text-zinc-500">{s.description}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-zinc-600 py-4">Sin senales. Ejecutar Sincronizar y Regenerar.</p>
          )}
        </TabsContent>

        <TabsContent value="catalog" className="mt-3">
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            {catalog.sort((a,b) => (b.mna_relevance || 0) - (a.mna_relevance || 0)).map(item => (
              <CatalogCard key={item.entity_type} item={item} />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="entities" className="mt-3 space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" />
              <Input placeholder="Buscar por nombre..." value={searchTerm}
                onChange={(e) => { setSearchTerm(e.target.value); loadEntities(filterType, e.target.value); }}
                className="h-8 pl-8 text-xs bg-zinc-900 border-zinc-800" />
            </div>
            <Button variant={!filterType ? 'secondary' : 'ghost'} size="sm"
              onClick={() => { setFilterType(null); loadEntities(null, searchTerm); }}
              className="h-7 px-2 text-xs">Todas</Button>
            {['scr','fcr','sgeic','sgiic','esi','eaf'].map(t => {
              const info = catalog.find(c => c.entity_type === t);
              return (
                <Button key={t} variant={filterType === t ? 'secondary' : 'ghost'} size="sm"
                  onClick={() => { setFilterType(t); loadEntities(t, searchTerm); }}
                  className="h-7 px-2 text-xs">{info?.code || t}</Button>
              );
            })}
          </div>

          <Card className="bg-zinc-900/50 border-zinc-800">
            <Table>
              <TableHeader>
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">NIF</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Nombre</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Tipo</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">M&A</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Descripcion</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entities.map((e, i) => (
                  <TableRow key={e.nif || i} className="border-zinc-800/50">
                    <TableCell className="py-1.5 text-xs font-mono text-zinc-500">{e.nif}</TableCell>
                    <TableCell className="py-1.5 text-xs text-zinc-200">{e.name}</TableCell>
                    <TableCell className="py-1.5">
                      <Badge variant="outline" className={`text-[9px] px-1.5 py-0 ${e.is_manager ? 'text-emerald-400 border-emerald-500/20' : 'text-blue-400 border-blue-500/20'}`}>
                        {catalog.find(c => c.entity_type === e.entity_type)?.code || e.entity_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-1.5"><MnaRelevance level={e.mna_relevance} /></TableCell>
                    <TableCell className="py-1.5 text-[10px] text-zinc-500 max-w-[200px] truncate">{e.short_description}</TableCell>
                  </TableRow>
                ))}
                {entities.length === 0 && (
                  <TableRow><TableCell colSpan={5} className="text-center text-xs text-zinc-600 py-8">
                    {kpis.total_entities > 0 ? 'Usa los filtros para buscar entidades.' : 'Sin datos. Ejecuta Sincronizar.'}
                  </TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        <TabsContent value="confidence" className="mt-3 space-y-4">
          {(() => {
            const c = data?.confidence || {};
            return (
              <>
                {/* Level cards */}
                <div className="grid grid-cols-3 gap-3">
                  <Card className="bg-zinc-900/50 border-emerald-800/30 border">
                    <CardContent className="p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-3 h-3 rounded-full bg-emerald-500" />
                        <span className="text-sm font-semibold text-emerald-400">Nivel A — Dato oficial</span>
                      </div>
                      <p className="text-2xl font-bold text-zinc-100 tabular-nums">{c.official_data_level_a || 0}</p>
                      <p className="text-[10px] text-zinc-500 mt-1">Nombre, NIF, tipo de entidad, estado. Proceden directamente de los registros oficiales de la CNMV.</p>
                      <p className="text-[10px] text-emerald-400 mt-1">Confianza: 100%</p>
                    </CardContent>
                  </Card>
                  <Card className="bg-zinc-900/50 border-amber-800/30 border">
                    <CardContent className="p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-3 h-3 rounded-full bg-amber-500" />
                        <span className="text-sm font-semibold text-amber-400">Nivel B — Dato inferido</span>
                      </div>
                      <p className="text-2xl font-bold text-zinc-100 tabular-nums">{(c.inferred_sector_level_b || 0) + (c.generalist_level_b || 0)}</p>
                      <div className="text-[10px] text-zinc-500 mt-1 space-y-0.5">
                        <p>{c.inferred_sector_level_b || 0} con sector CNAE inferido</p>
                        <p>{c.generalist_level_b || 0} clasificados como generalistas</p>
                      </div>
                      <p className="text-[10px] text-amber-400 mt-1">Confianza media: {c.avg_confidence_score || 0}%</p>
                    </CardContent>
                  </Card>
                  <Card className="bg-zinc-900/50 border-blue-800/30 border">
                    <CardContent className="p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="w-3 h-3 rounded-full bg-blue-500" />
                        <span className="text-sm font-semibold text-blue-400">Nivel C — Validado</span>
                      </div>
                      <p className="text-2xl font-bold text-zinc-100 tabular-nums">{c.validated_level_c || 0}</p>
                      <p className="text-[10px] text-zinc-500 mt-1">Sector, ticket, tamano empresa, geografia. Validados manualmente por el equipo.</p>
                      <p className="text-[10px] text-blue-400 mt-1">Pendiente de validacion manual</p>
                    </CardContent>
                  </Card>
                </div>

                {/* Data lineage explanation */}
                <Card className="bg-zinc-900/50 border-zinc-800">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-zinc-400">Trazabilidad: de donde sale cada dato</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow className="border-zinc-800 hover:bg-transparent">
                          <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Campo</TableHead>
                          <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Fuente</TableHead>
                          <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Nivel</TableHead>
                          <TableHead className="text-[10px] uppercase tracking-wider text-zinc-500">Confianza</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {[
                          { field: 'Nombre', source: 'CNMV Registros Oficiales', level: 'A', score: 100 },
                          { field: 'NIF', source: 'CNMV Registros Oficiales', level: 'A', score: 100 },
                          { field: 'Tipo de entidad', source: 'CNMV Registros Oficiales', level: 'A', score: 100 },
                          { field: 'Estado', source: 'CNMV Registros Oficiales', level: 'A', score: 100 },
                          { field: 'Sector CNAE', source: 'Internal Classification Engine', level: 'B', score: c.avg_confidence_score || 56 },
                          { field: 'Clasificacion especialista/generalista', source: 'Keyword Analysis', level: 'B', score: c.avg_confidence_score || 56 },
                          { field: 'Compradores por CNAE', source: 'CNMV Buyers Engine', level: 'B', score: c.avg_confidence_score || 56 },
                          { field: 'Relevancia M&A', source: 'CNMV Entity Catalog', level: 'A', score: 100 },
                        ].map((row, i) => (
                          <TableRow key={i} className="border-zinc-800/50">
                            <TableCell className="py-1.5 text-xs text-zinc-300">{row.field}</TableCell>
                            <TableCell className="py-1.5 text-xs text-zinc-400">{row.source}</TableCell>
                            <TableCell className="py-1.5">
                              <span className={`w-2 h-2 rounded-full inline-block mr-1.5 ${row.level === 'A' ? 'bg-emerald-500' : row.level === 'B' ? 'bg-amber-500' : 'bg-blue-500'}`} />
                              <span className="text-xs text-zinc-400">{row.level}</span>
                            </TableCell>
                            <TableCell className="py-1.5 text-xs tabular-nums text-zinc-400">{row.score}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>

                {/* Coverage */}
                <Card className="bg-zinc-900/50 border-zinc-800">
                  <CardContent className="p-4">
                    <p className="text-xs text-zinc-400 mb-2">Cobertura sectorial</p>
                    <div className="w-full h-2 bg-zinc-800 rounded-full overflow-hidden flex">
                      <div className="h-full bg-amber-500" style={{ width: `${c.sector_coverage_pct || 0}%` }} />
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-[10px] text-amber-400">{c.sector_coverage_pct || 0}% con sector CNAE inferido</span>
                      <span className="text-[10px] text-zinc-600">{100 - (c.sector_coverage_pct || 0)}% generalistas</span>
                    </div>
                  </CardContent>
                </Card>
              </>
            );
          })()}
        </TabsContent>
      </Tabs>
    </div>
  );
}
