import type { DriftAlert } from '../lib/types'

interface DriftListProps {
  drifts: DriftAlert[]
}

export function DriftList({ drifts }: DriftListProps) {
  if (drifts.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="text-center">
          <div className="text-2xl mb-2">✓</div>
          <p className="text-green-600 font-medium">All Clear</p>
          <p className="text-sm text-gray-500">No active drift alerts</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 bg-red-50">
        <p className="text-sm font-medium text-red-800">
          {drifts.length} Active Drift{drifts.length > 1 ? 's' : ''}
        </p>
      </div>
      <ul className="divide-y divide-gray-100">
        {drifts.slice(0, 5).map((drift, i) => (
          <li key={i} className="px-4 py-3 hover:bg-gray-50">
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm">{drift.stream}</span>
              <span className="text-xs text-gray-500">
                {new Date(drift.detected_at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm text-gray-600 mt-1">{drift.report}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
