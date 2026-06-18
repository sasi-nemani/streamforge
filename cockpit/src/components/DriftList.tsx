import type { DriftAlert, DriftFinding } from '../lib/types'

const TIER_STYLE: Record<number, string> = {
  3: 'bg-red-100 text-red-700',
  2: 'bg-amber-100 text-amber-700',
  1: 'bg-gray-100 text-gray-600',
}

const TEST_LABEL: Record<string, string> = {
  binomial_z: 'binomial z',
  chi_squared: 'chi²',
  enum_threshold: 'enum threshold',
  pii_heuristic: 'PII heuristic',
}

function evidence(f: DriftFinding): string {
  if (!f.test_name) return ''
  const parts = [TEST_LABEL[f.test_name] ?? f.test_name]
  if (f.p_value != null) {
    parts.push(f.p_value < 1e-4 ? 'p<0.0001' : `p=${f.p_value.toFixed(4)}`)
  }
  if (f.effect_size != null) parts.push(`effect ${f.effect_size.toFixed(2)}`)
  return parts.join(', ')
}

function Finding({ f }: { f: DriftFinding }) {
  const tier = f.tier ?? 1
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <p className="text-sm">
          <span className="font-mono text-gray-800">{f.field_path}</span>{' '}
          <span className="text-gray-500">{f.drift_type}</span>
        </p>
        {evidence(f) && <p className="text-xs text-gray-400 font-mono mt-0.5">{evidence(f)}</p>}
      </div>
      <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded ${TIER_STYLE[tier] ?? TIER_STYLE[1]}`}>
        T{tier}
      </span>
    </div>
  )
}

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
            {drift.findings && drift.findings.length > 0 ? (
              <div className="mt-2 divide-y divide-gray-50">
                {drift.findings.slice(0, 4).map((f, j) => (
                  <Finding key={j} f={f} />
                ))}
                {drift.findings.length > 4 && (
                  <p className="text-xs text-gray-400 pt-1.5">+{drift.findings.length - 4} more</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-600 mt-1">{drift.report}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
