import { useData } from '../hooks/useData'
import { Link } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { SourcesTable } from '../components/SourcesTable'
import { HealthStatus } from '../components/HealthStatus'
import { DashboardSkeleton } from '../components/Skeleton'
import { Scorecard } from '../components/Scorecard'

function MetricCard({
  label,
  value,
  sublabel,
  color = 'gray',
}: {
  label: string
  value: number | string
  sublabel?: string
  color?: 'gray' | 'green' | 'red' | 'amber'
}) {
  const colors = {
    gray: 'text-gray-900',
    green: 'text-green-600',
    red: 'text-red-600',
    amber: 'text-amber-600',
  }
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-3xl font-semibold mt-2 ${colors[color]}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sublabel && <p className="text-xs text-gray-400 mt-1">{sublabel}</p>}
    </div>
  )
}

function DataQualityScore({ score }: { score: number }) {
  const color = score >= 90 ? 'text-green-600' : score >= 70 ? 'text-amber-600' : 'text-red-600'
  const bgColor = score >= 90 ? 'bg-green-100' : score >= 70 ? 'bg-amber-100' : 'bg-red-100'
  const label = score >= 90 ? 'Excellent' : score >= 70 ? 'Good' : 'Needs Attention'

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-700">Data Quality Score</h3>
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${bgColor} ${color}`}>
          {label}
        </span>
      </div>
      <div className="flex items-end gap-3">
        <span className={`text-5xl font-bold ${color}`}>{score}</span>
        <span className="text-gray-400 text-lg mb-1">/100</span>
      </div>
      <div className="mt-4 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full ${score >= 90 ? 'bg-green-500' : score >= 70 ? 'bg-amber-500' : 'bg-red-500'}`}
          style={{ width: `${score}%` }}
        />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <div className="text-center">
          <p className="text-gray-500">Schema</p>
          <p className="font-medium">100%</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500">PII Tagged</p>
          <p className="font-medium">100%</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500">No Drift</p>
          <p className="font-medium">{score >= 90 ? '100%' : '85%'}</p>
        </div>
      </div>
    </div>
  )
}

function DriftCard({ drifts }: { drifts: { stream: string; report: string; detected_at: string }[] }) {
  if (drifts.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Drift Alerts</h3>
        <div className="flex items-center justify-center py-8">
          <div className="text-center">
            <span className="text-3xl">✓</span>
            <p className="text-sm text-gray-500 mt-2">No active drifts</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-700">Drift Alerts</h3>
        <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">
          {drifts.length} active
        </span>
      </div>
      <div className="space-y-3">
        {drifts.slice(0, 5).map((d, i) => (
          <div key={i} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
            <div>
              <Link
                to={`/stream/${d.stream}`}
                className="font-mono text-sm text-blue-600 hover:underline"
              >
                {d.stream}
              </Link>
              <p className="text-xs text-gray-400">{d.report}</p>
            </div>
            <span className="text-xs text-gray-500">
              {new Date(d.detected_at).toLocaleDateString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function PiiCard({ pii }: { pii: { total: number; by_category: Record<string, number> } | null }) {
  if (!pii || pii.total === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">PII Detection</h3>
        <p className="text-gray-500 text-sm">No PII fields detected</p>
      </div>
    )
  }

  const categories = Object.entries(pii.by_category).sort((a, b) => b[1] - a[1])

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-700">PII Detection</h3>
        <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">
          {pii.total} fields
        </span>
      </div>
      <div className="space-y-2">
        {categories.map(([cat, count]) => (
          <div key={cat} className="flex items-center justify-between">
            <span className="text-sm text-gray-600 capitalize">{cat.replace('_', ' ')}</span>
            <div className="flex items-center gap-2">
              <div className="w-24 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-red-400"
                  style={{ width: `${(count / pii.total) * 100}%` }}
                />
              </div>
              <span className="text-xs text-gray-500 w-4">{count}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Dashboard() {
  const { sources, metrics, drifts, pii, health, loading, error } = useData()

  if (loading) {
    return (
      <Layout>
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">Overview</h1>
          <p className="text-sm text-gray-500 mt-1">Loading dashboard...</p>
        </div>
        <DashboardSkeleton />
      </Layout>
    )
  }

  if (error) {
    return (
      <Layout>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-800">Error: {error}</p>
          <p className="text-sm text-red-600 mt-2">
            Make sure the API server is running: uvicorn streamforge.api.main:app
          </p>
        </div>
      </Layout>
    )
  }

  const qualityScore = metrics
    ? Math.round(100 - (metrics.active_drifts * 5) - (metrics.pii_fields > 10 ? 5 : 0))
    : 95

  return (
    <Layout>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Real-time schema intelligence across your data estate
        </p>
      </div>

      <div className="mb-8 bg-gray-50 rounded-xl border border-gray-200 p-6">
        <Scorecard />
      </div>

      <div className="grid grid-cols-5 gap-4 mb-8">
        <MetricCard
          label="Events Sampled"
          value={metrics?.messages_sampled ?? 0}
          sublabel="Total processed"
        />
        <MetricCard
          label="Fields Detected"
          value={metrics?.fields_detected ?? 0}
          sublabel="Across all streams"
        />
        <MetricCard
          label="Schemas"
          value={metrics?.schemas_inferred ?? 0}
          sublabel="Auto-inferred"
          color="green"
        />
        <MetricCard
          label="PII Fields"
          value={metrics?.pii_fields ?? 0}
          sublabel="Auto-detected"
          color={metrics?.pii_fields ? 'red' : 'gray'}
        />
        <MetricCard
          label="Active Drifts"
          value={metrics?.active_drifts ?? 0}
          sublabel={metrics?.active_drifts ? 'Requires attention' : 'All clear'}
          color={metrics?.active_drifts ? 'amber' : 'green'}
        />
      </div>

      <div className="grid grid-cols-3 gap-6 mb-8">
        <DataQualityScore score={qualityScore} />
        <DriftCard drifts={drifts} />
        <PiiCard pii={pii} />
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">Connected Streams</h2>
            <Link
              to="/catalog"
              className="text-sm text-blue-600 hover:underline"
            >
              View all fields →
            </Link>
          </div>
          <SourcesTable sources={sources} />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">System Health</h2>
          <HealthStatus health={health} />
        </div>
      </div>
    </Layout>
  )
}
