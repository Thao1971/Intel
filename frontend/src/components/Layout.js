import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  LayoutDashboard, Search, FileStack, List, Building2,
  ClipboardCheck, Settings, LogOut, Cpu,
  FileText, Palette, Newspaper, FileDown, BookOpen, Activity, Layers,
  TrendingUp, Globe, BarChart3, Zap, ArrowRightLeft, Database,
  Landmark, Shield, Heart, Workflow, ListChecks, ScrollText,
  Users, Lock, History, Flag, Plug, Gauge, Sparkles,
  Eye, PieChart, Combine, Network, GitCompareArrows, Upload, Brain
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import api from '@/lib/api';

// Reorganizado 2026-07-22: agrupado por tarea del usuario (no por nombre de arquitectura
// interna), incorporando 14 páginas ya funcionales que antes no aparecían en ningún menú
// (solo accesibles tecleando la URL), y separando lo construido de lo pendiente en una
// única sección "PRÓXIMAMENTE" al final en vez de mezclarlo con funcionalidad real.
const navSections = [
  {
    label: 'INICIO',
    items: [
      { path: '/', label: 'Dashboard', icon: LayoutDashboard },
      { path: '/copilot', label: 'Copilot M&A', icon: Brain },
      { path: '/ai-chat', label: 'AI Chat', icon: Sparkles },
    ],
  },
  {
    label: 'EMPRESAS',
    items: [
      { path: '/analysis', label: 'Análisis individual', icon: Search },
      { path: '/bulk', label: 'Análisis masivo', icon: FileStack },
      { path: '/results', label: 'Resultados', icon: List },
      { path: '/master-entities', label: 'Empresas maestro', icon: Building2 },
      { path: '/watchlist', label: 'Watchlist', icon: Eye },
    ],
  },
  {
    label: 'INTELIGENCIA DE MERCADO',
    items: [
      { path: '/macro', label: 'Macro', dot: 'bg-blue-500' },
      { path: '/sector-intelligence', label: 'Sectorial', dot: 'bg-emerald-500' },
      { path: '/geo-intelligence', label: 'Geográfica', dot: 'bg-violet-500' },
      { path: '/cross-intelligence', label: 'Sector × Geografía', dot: 'bg-cyan-500' },
      { path: '/economic-intelligence', label: 'Económica', dot: 'bg-amber-500' },
      { path: '/business-demography', label: 'DIRCE (demografía empresarial)', icon: Building2 },
      { path: '/datacomex', label: 'Comercio exterior', icon: Globe },
      { path: '/procurement', label: 'Contratación pública', icon: Landmark },
      { path: '/cnmv', label: 'CNMV', icon: TrendingUp },
      { path: '/bme', label: 'BME', icon: BarChart3 },
    ],
  },
  {
    label: 'M&A E INVERSIÓN',
    items: [
      { path: '/opportunities', label: 'Oportunidades', icon: Sparkles },
      { path: '/signals', label: 'Señales', icon: Zap },
      { path: '/transactions', label: 'Transacciones', icon: ArrowRightLeft },
      { path: '/ma-radar', label: 'M&A Radar', icon: Activity },
      { path: '/borme', label: 'BORME', icon: FileStack },
      { path: '/valuations', label: 'Valoraciones', dot: 'bg-emerald-500' },
      { path: '/investment/fragmentation', label: 'Fragmentación', icon: PieChart },
      { path: '/investment/rollup-thesis', label: 'Roll-up Thesis', icon: Combine },
      { path: '/ownership/control-graph', label: 'Grafo de control', icon: Network },
      { path: '/ownership/control-synergy', label: 'Control & Synergy', icon: GitCompareArrows },
    ],
  },
  {
    label: 'DOCUMENTOS Y CONTENIDO',
    items: [
      { path: '/doc-studio', label: 'Document Studio', icon: FileDown },
      { path: '/editorial', label: 'Editorial', icon: Newspaper },
      { path: '/manual', label: 'Manual', icon: BookOpen },
    ],
  },
  {
    label: 'TAXONOMÍA Y CALIDAD',
    items: [
      { path: '/taxonomy', label: 'Taxonomía CIS', dot: 'bg-indigo-500' },
      { path: '/taxonomy-intelligence', label: 'Taxonomía Intel', icon: Layers },
      { path: '/taxonomy-audit', label: 'Auditoría Taxonomía', icon: PieChart },
      { path: '/review', label: 'Cola de revisión', icon: ClipboardCheck },
      { path: '/data-providers', label: 'Proveedores de datos', icon: Database },
      { path: '/data-providers/iberinform-delivery', label: 'Entregas Iberinform', icon: Upload },
      { path: '/data-quality', label: 'Calidad de datos', icon: Gauge },
    ],
  },
  {
    label: 'MOTOR DE SCRAPING',
    items: [
      { path: '/engine/profiles', label: 'Perfiles', icon: Layers },
      { path: '/engine/web-source', label: 'Web Source', icon: Globe },
      { path: '/engine/scrape-queue', label: 'Cola de scraping', icon: Workflow },
      { path: '/engine/health', label: 'Salud del motor', icon: Heart },
    ],
  },
];

const platformSection = {
  label: 'PLATAFORMA',
  items: [
    { path: '/ai-usage', label: 'Consumo de IA', icon: Cpu },
    { path: '/settings', label: 'Configuración', icon: Settings },
    { path: '/api-docs', label: 'API Docs', icon: BookOpen },
  ],
};

// Todo lo que aún no está construido (antes disperso entre M&A ENGINE, KNOWLEDGE,
// PLATFORM y ADMIN, indistinguible de las funcionalidades reales) vive ahora en un
// único bloque atenuado al final del menú. Sigue siendo clicable — la propia
// PlaceholderPage explica qué falta — pero visualmente no compite con lo que sí funciona.
const comingSoonSection = {
  label: 'PRÓXIMAMENTE',
  comingSoon: true,
  items: [
    { path: '/ma/buyers', label: 'Buyers', icon: Users },
    { path: '/ma/sellers', label: 'Sellers', icon: Building2 },
    { path: '/ma/matching', label: 'Matching', icon: Search },
    { path: '/knowledge/prompts', label: 'Prompts', icon: ScrollText },
    { path: '/platform/integrations', label: 'Integraciones', icon: Plug },
    { path: '/platform/jobs', label: 'Jobs', icon: ListChecks },
    { path: '/platform/logs', label: 'Logs', icon: ScrollText },
    { path: '/platform/feature-flags', label: 'Feature Flags', icon: Flag },
    { path: '/data/oepm', label: 'OEPM', icon: Database },
    { path: '/admin/users', label: 'Usuarios', icon: Users },
    { path: '/admin/roles', label: 'Roles', icon: Shield },
    { path: '/admin/security', label: 'Seguridad', icon: Lock },
    { path: '/admin/audit', label: 'Auditoría', icon: History },
  ],
};

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [dataSources, setDataSources] = useState([]);

  useEffect(() => {
    api.get('/intelligence/sources/sidebar')
      .then(r => setDataSources(r.data?.groups?.data || []))
      .catch(() => setDataSources([]));
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  // DATA section is derived 100% from the Intelligence Engine (no static array).
  const dynamicDataSection = {
    label: 'DATA',
    items: dataSources.map(s => ({ path: s.route, label: s.label, dot: s.dot })),
  };

  const allSections = [...navSections, dynamicDataSection, platformSection, comingSoonSection];

  return (
    <div className="flex h-screen bg-zinc-950" data-testid="app-layout">
      <aside className="w-56 flex-shrink-0 border-r border-zinc-800 bg-zinc-950 flex flex-col">
        <div className="p-4 flex items-center gap-2.5">
          <div className="w-7 h-7 rounded bg-blue-600 flex items-center justify-center">
            <Cpu className="w-3.5 h-3.5 text-white" />
          </div>
          <div>
            <h1 className="font-heading text-xs font-bold tracking-tight text-zinc-50">Intelligence Engine</h1>
            <p className="text-[8px] uppercase tracking-[0.15em] text-zinc-500 font-medium">Platform Console</p>
          </div>
        </div>

        <Separator className="bg-zinc-800" />

        <ScrollArea className="flex-1 px-2 py-2">
          <nav>
            {allSections.map((section, sIdx) => (
              <div key={sIdx}>
                {section.label && (
                  <p className={`px-3 pt-3 pb-1 text-[7px] font-semibold uppercase tracking-[0.2em] ${section.comingSoon ? 'text-zinc-700' : 'text-zinc-600'}`}>
                    {section.label}
                  </p>
                )}
                {section.items.map((item) => (
                  <NavLink
                    key={item.path + item.label}
                    to={item.path}
                    end={item.path === '/'}
                    data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-').replace(/[×&]/g, '')}`}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-3 py-1 rounded text-[12px] font-medium transition-colors ${
                        section.comingSoon
                          ? `text-zinc-600 hover:text-zinc-400 ${isActive ? 'bg-zinc-800/50' : ''}`
                          : isActive
                          ? 'bg-zinc-800 text-zinc-50'
                          : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                      }`
                    }
                  >
                    {item.dot ? (
                      <span className={`w-2 h-2 rounded-full ${section.comingSoon ? 'bg-zinc-700' : item.dot} flex-shrink-0`} />
                    ) : (
                      <item.icon className={`w-3.5 h-3.5 flex-shrink-0 ${section.comingSoon ? 'opacity-40' : ''}`} />
                    )}
                    <span className="flex-1 truncate">{item.label}</span>
                    {section.comingSoon && (
                      <span className="text-[7px] text-zinc-700 uppercase tracking-wide flex-shrink-0">pronto</span>
                    )}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
        </ScrollArea>

        <div className="p-3 border-t border-zinc-800">
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-zinc-500 truncate">{user?.email}</p>
            <Button variant="ghost" size="sm" onClick={handleLogout} data-testid="logout-btn"
              className="text-zinc-500 hover:text-zinc-200 h-7 w-7 p-0">
              <LogOut className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-6">
            <Outlet />
          </div>
        </ScrollArea>
      </main>
    </div>
  );
}
