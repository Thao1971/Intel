import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import AnalysisPage from "@/pages/AnalysisPage";
import BulkAnalysisPage from "@/pages/BulkAnalysisPage";
import ResultsPage from "@/pages/ResultsPage";
import ResultDetailPage from "@/pages/ResultDetailPage";
import TaxonomyPage from "@/pages/TaxonomyPage";
import ReviewPage from "@/pages/ReviewPage";
import SettingsPage from "@/pages/SettingsPage";
import ApiDocsPage from "@/pages/ApiDocsPage";
import AIUsagePage from "@/pages/AIUsagePage";
import HubPage from "@/pages/hub/HubPage";
import ManualPage from "@/pages/ManualPage";
import BormePage from "@/pages/BormePage";
import MAPage from "@/pages/MAPage";
import EditorialPage from "@/pages/editorial/EditorialPage";
import DataProvidersPage from "@/pages/DataProvidersPage";
import IberinformDeliveryPage from "@/pages/IberinformDeliveryPage";
import MasterEntitiesPage from "@/pages/MasterEntitiesPage";
import MacroIntelligencePage from "@/pages/MacroIntelligencePage";
import SectorIntelligencePage from "@/pages/SectorIntelligencePage";
import GeoIntelligencePage from "@/pages/GeoIntelligencePage";
import DataQualityPage from "@/pages/DataQualityPage";
import TaxonomyAuditPage from "@/pages/TaxonomyAuditPage";
import CrossIntelligencePage from "@/pages/CrossIntelligencePage";
import DataComexPage from "@/pages/DataComexPage";
import TaxonomyIntelligencePage from "@/pages/TaxonomyIntelligencePage";
import EconomicIntelligencePage from "@/pages/EconomicIntelligencePage";
import BusinessDemographyPage from "@/pages/BusinessDemographyPage";
import CNMVPage from "@/pages/CNMVPage";
import BMEPage from "@/pages/BMEPage";
import ValuationsPage from "@/pages/ValuationsPage";
import ProcurementPage from "@/pages/ProcurementPage";
import DocStudioPage from "@/pages/DocStudioPage";
import TransactionsPage from "@/pages/transactions/TransactionsPage";
import AIChatPage from "@/pages/AIChatPage";
import CopilotPage from "@/pages/CopilotPage";
import HealthPage from "@/pages/engine/HealthPage";
import ProfilesPage from "@/pages/engine/ProfilesPage";
import ScrapeQueuePage from "@/pages/engine/ScrapeQueuePage";
import WebSourcePage from "@/pages/engine/WebSourcePage";
import PlaceholderPage from "@/pages/PlaceholderPage";
import DataSourcePage from "@/pages/DataSourcePage";
import WatchlistPage from "@/pages/WatchlistPage";
import OpportunitiesPage from "@/pages/OpportunitiesPage";
import SignalsPage from "@/pages/SignalsPage";
import FragmentationPage from "@/pages/FragmentationPage";
import RollupThesisPage from "@/pages/RollupThesisPage";
import ControlGraphPage from "@/pages/ControlGraphPage";
import ControlSynergyPage from "@/pages/ControlSynergyPage";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  return user ? children : <Navigate to="/login" replace />;
}

function AppRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="hub" element={<HubPage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="bulk" element={<BulkAnalysisPage />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="results/:id" element={<ResultDetailPage />} />
        {/* Unificado en Document Studio — rutas antiguas redirigen (sin pantallas huérfanas) */}
        <Route path="documents" element={<Navigate to="/doc-studio" replace />} />
        <Route path="brands" element={<Navigate to="/doc-studio" replace />} />
        <Route path="borme" element={<BormePage />} />
        <Route path="ma-radar" element={<MAPage />} />
        <Route path="data-providers" element={<DataProvidersPage />} />
        <Route path="data-providers/iberinform-delivery" element={<IberinformDeliveryPage />} />
        <Route path="master-entities" element={<MasterEntitiesPage />} />
        <Route path="macro" element={<MacroIntelligencePage />} />
        <Route path="sector-intelligence" element={<SectorIntelligencePage />} />
        <Route path="geo-intelligence" element={<GeoIntelligencePage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="taxonomy-audit" element={<TaxonomyAuditPage />} />
        <Route path="cross-intelligence" element={<CrossIntelligencePage />} />
        <Route path="datacomex" element={<DataComexPage />} />
        <Route path="taxonomy-intelligence" element={<TaxonomyIntelligencePage />} />
        <Route path="economic-intelligence" element={<EconomicIntelligencePage />} />
        <Route path="business-demography" element={<BusinessDemographyPage />} />
        <Route path="cnmv" element={<CNMVPage />} />
        <Route path="bme" element={<BMEPage />} />
        <Route path="valuations" element={<ValuationsPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="opportunities" element={<OpportunitiesPage />} />
        <Route path="signals" element={<SignalsPage />} />
        <Route path="investment/fragmentation" element={<FragmentationPage />} />
        <Route path="investment/rollup-thesis" element={<RollupThesisPage />} />
        <Route path="ownership/control-graph" element={<ControlGraphPage />} />
        <Route path="ownership/control-synergy" element={<ControlSynergyPage />} />
        <Route path="procurement" element={<ProcurementPage />} />
        <Route path="doc-studio" element={<DocStudioPage />} />
        <Route path="template-builder" element={<Navigate to="/doc-studio" replace />} />
        <Route path="editorial" element={<EditorialPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="taxonomy" element={<TaxonomyPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="manual" element={<ManualPage />} />
        <Route path="api-docs" element={<ApiDocsPage />} />
        <Route path="ai-usage" element={<AIUsagePage />} />
        <Route path="ai-chat" element={<AIChatPage />} />
        <Route path="copilot" element={<CopilotPage />} />

        {/* Intelligence Engine */}
        <Route path="engine/health" element={<HealthPage />} />
        <Route path="engine/profiles" element={<ProfilesPage />} />
        <Route path="engine/scrape-queue" element={<ScrapeQueuePage />} />
        <Route path="engine/web-source" element={<WebSourcePage />} />

        {/* M&A Engine */}
        <Route path="ma/buyers" element={<PlaceholderPage title="M&A Engine — Buyers" subtitle="Catálogo de compradores activos" hint="Se poblará cuando llegue Iberinform real + el módulo de Universal Search (Arroba)." />} />
        <Route path="ma/sellers" element={<PlaceholderPage title="M&A Engine — Sellers" subtitle="Catálogo de vendedores y oportunidades" hint="Pendiente de Iberinform real." />} />
        <Route path="ma/matching" element={<PlaceholderPage title="M&A Engine — Matching" subtitle="Matching automático buyer ↔ target por CNAE, tamaño y geografía" hint="Depende de la importación real de Iberinform (3.3M empresas)." />} />

        {/* Knowledge */}
        <Route path="knowledge/prompts" element={<PlaceholderPage title="Knowledge — Prompts" subtitle="Plantillas LLM versionadas para clasificación y narrativa" hint="Registro central de prompts en producción. P2 backlog." />} />

        {/* Platform */}
        <Route path="platform/integrations" element={<PlaceholderPage title="Platform — Integraciones" subtitle="Conectores externos (Stripe, BME, IMAP, etc.)" hint="Hoy se gestiona desde Configuración → API Settings." />} />
        <Route path="platform/jobs" element={<PlaceholderPage title="Platform — Jobs" subtitle="Vista unificada de analysis_jobs, intelligence_scheduler, datacomex_scheduler" hint="P1 backlog tras Atlas migration." />} />
        <Route path="platform/logs" element={<PlaceholderPage title="Platform — Logs" subtitle="Stream de logs del backend (supervisor)" hint="Por ahora consultable via tail /var/log/supervisor/backend.*.log." />} />
        <Route path="platform/feature-flags" element={<PlaceholderPage title="Platform — Feature Flags" subtitle="Toggles de funcionalidades por producto/entorno" hint="Estructura para producción multi-producto. P2 backlog." />} />

        {/* Data */}
        <Route path="data/oepm" element={<PlaceholderPage title="OEPM Intelligence" subtitle="Patentes, marcas y diseños industriales" hint="🧊 Congelado por decisión del producto hasta importación real de Iberinform (necesita matching robusto por CIF)." />} />
        <Route path="data/source/:source" element={<DataSourcePage />} />

        {/* Admin */}
        <Route path="admin/users" element={<PlaceholderPage title="Admin — Usuarios" subtitle="Gestión de cuentas del Platform Console" hint="Hoy autenticación JWT vía /api/v1/auth. Panel CRUD pendiente." />} />
        <Route path="admin/roles" element={<PlaceholderPage title="Admin — Roles" subtitle="RBAC para Valuo, Arroba y Platform Console" hint="P2 backlog. Hoy todos los usuarios autenticados son admin." />} />
        <Route path="admin/security" element={<PlaceholderPage title="Admin — Seguridad" subtitle="Políticas de contraseña, MFA, rotación de API keys" hint="P2 backlog tras Atlas." />} />
        <Route path="admin/audit" element={<PlaceholderPage title="Admin — Auditoría" subtitle="er_audit_logs centralizados (entity resolution + merges)" hint="La colección er_audit_logs ya existe; pendiente UI." />} />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: '#18181b',
              border: '1px solid #27272a',
              color: '#fafafa',
            },
          }}
        />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
