import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RefreshCw, Loader2, Clock, CheckCircle2, AlertTriangle, Database } from 'lucide-react';
import { toast } from 'sonner';

function timeAgo(isoDate) {
  if (!isoDate) return 'Nunca';
  const now = new Date();
  const then = new Date(isoDate);
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return 'Hace menos de 1 min';
  if (diff < 3600) return `Hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `Hace ${Math.floor(diff / 3600)}h`;
  const days = Math.floor(diff / 86400);
  if (days === 1) return 'Hace 1 dia';
  return `Hace ${days} dias`;
}

function formatDate(isoDate) {
  if (!isoDate) return '—';
  const d = new Date(isoDate);
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatShortDate(isoDate) {
  if (!isoDate) return '—';
  // Handle YYYYMMDD format (from BORME)
  if (typeof isoDate === 'string' && /^\d{8}$/.test(isoDate)) {
    return `${isoDate.substring(6,8)}/${isoDate.substring(4,6)}/${isoDate.substring(0,4)}`;
  }
  const d = new Date(isoDate);
  if (isNaN(d.getTime())) return isoDate.substring(0, 10);
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

const SOURCE_STATUS = {
  active: { dot: 'bg-emerald-500', label: 'Activo' },
  synthetic: { dot: 'bg-amber-500', label: 'Sintetico' },
  pending: { dot: 'bg-zinc-500', label: 'Pendiente' },
  empty: { dot: 'bg-rose-500', label: 'Sin datos' },
};

export function SyncBar({ module, syncEndpoint, onSyncComplete }) {
  const [syncInfo, setSyncInfo] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [schedule, setSchedule] = useState(null);
  const [sources, setSources] = useState(null);

  useEffect(() => {
    loadStatus();
  }, [module]);

  const loadStatus = async () => {
    try {
      const { data } = await api.get('/public/intelligence/sync-status');
      setSyncInfo(data.modules?.[module] || null);
      setSchedule(data.schedule?.[module] || null);
      setSources(data.sources || null);
    } catch {
      // Silent
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data: started } = await api.post(syncEndpoint);
      if (started?.status === 'running') {
        // Endpoint en segundo plano: consultamos sync-status hasta que termine (max 5 min)
        let info = null;
        for (let i = 0; i < 100; i++) {
          await new Promise(r => setTimeout(r, 3000));
          const { data } = await api.get('/public/intelligence/sync-status');
          info = data.modules?.[module] || null;
          setSyncInfo(info);
          if (info && info.status !== 'running') break;
        }
        if (!info || info.status === 'running') { toast.info('La sincronizacion sigue en curso'); setSyncing(false); return; }
        if (info.status === 'failed') { toast.error('Error sincronizando'); setSyncing(false); return; }
      }
      toast.success('Sincronizacion completada');
      await loadStatus();
      onSyncComplete?.();
    } catch (e) {
      toast.error('Error sincronizando');
    }
    setSyncing(false);
  };

  const lastSynced = syncInfo?.last_synced_at;
  const status = syncInfo?.status || 'never';
  const trigger = syncInfo?.trigger;
  const entries = syncInfo?.entries || 0;

  return (
    <div className="space-y-2">
      {/* Main sync bar */}
      <div className="flex items-center justify-between bg-zinc-900/40 border border-zinc-800/50 rounded-lg px-3 py-2" data-testid={`sync-bar-${module}`}>
        <div className="flex items-center gap-3">
          {status === 'completed' ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          ) : status === 'failed' ? (
            <AlertTriangle className="w-3.5 h-3.5 text-rose-500" />
          ) : (
            <Clock className="w-3.5 h-3.5 text-zinc-600" />
          )}
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">Ultima sync:</span>
            <span className="text-xs text-zinc-200 font-medium" data-testid={`sync-date-${module}`}>
              {lastSynced ? formatDate(lastSynced) : 'Nunca'}
            </span>
            {lastSynced && (
              <span className="text-[10px] text-zinc-500">({timeAgo(lastSynced)})</span>
            )}
          </div>
          {trigger && (
            <Badge variant="outline" className={`text-[9px] px-1.5 py-0 ${trigger === 'scheduler' ? 'text-blue-400 border-blue-500/20' : 'text-zinc-400 border-zinc-600'}`}>
              {trigger === 'scheduler' ? 'Auto' : 'Manual'}
            </Badge>
          )}
          {entries > 0 && (
            <span className="text-[10px] text-zinc-600">{entries.toLocaleString('es-ES')} entries</span>
          )}
          {schedule && (
            <>
              <span className="text-zinc-800">|</span>
              <span className="text-[10px] text-zinc-600">Programado: {schedule}</span>
            </>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleSync}
          disabled={syncing}
          className="border-zinc-700 text-zinc-300 h-7 text-xs"
          data-testid={`sync-btn-${module}`}
        >
          {syncing ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1.5" />}
          Sincronizar
        </Button>
      </div>

      {/* Source breakdown */}
      {sources && (
        <div className="flex items-center gap-4 px-3 py-1.5 bg-zinc-900/20 border border-zinc-800/30 rounded-lg" data-testid="source-breakdown">
          <Database className="w-3 h-3 text-zinc-600 flex-shrink-0" />
          {Object.entries(sources).map(([key, src]) => {
            const cfg = SOURCE_STATUS[src.status] || SOURCE_STATUS.empty;
            return (
              <div key={key} className="flex items-center gap-1.5" data-testid={`source-${key}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                <span className="text-[10px] text-zinc-400">{src.name}:</span>
                <span className="text-[10px] text-zinc-300">{src.last_update ? formatShortDate(src.last_update) : 'pendiente'}</span>
                <span className="text-[9px] text-zinc-600">({src.records?.toLocaleString('es-ES') || 0})</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
