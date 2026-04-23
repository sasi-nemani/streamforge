import type { HealthStatus as HealthStatusType } from '../lib/types'

interface HealthStatusProps {
  health: HealthStatusType | null
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'ok') return <span className="text-green-500">●</span>
  if (status === 'error') return <span className="text-red-500">●</span>
  if (status === 'unavailable') return <span className="text-gray-400">○</span>
  return <span className="text-yellow-500">●</span>
}

export function HealthStatus({ health }: HealthStatusProps) {
  if (!health) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <p className="text-sm text-gray-500">Loading health status...</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-medium text-gray-700">System Health</p>
        <div className="flex items-center gap-2">
          <StatusIcon status={health.status} />
          <span className="text-sm capitalize">{health.status}</span>
        </div>
      </div>
      <div className="space-y-3">
        {health.components.map((component) => (
          <div key={component.name} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <StatusIcon status={component.status} />
              <span className="text-sm capitalize">{component.name}</span>
            </div>
            <span className="font-mono text-xs text-gray-500">
              {component.latency_ms}ms
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
