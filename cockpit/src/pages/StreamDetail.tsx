import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { api } from '../lib/api'
import type { StreamDetail as StreamDetailType, FieldDetail } from '../lib/types'

function FieldCard({ field }: { field: FieldDetail }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors">
      <div
        className="flex items-start justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{field.path}</span>
            {field.pii.length > 0 && (
              <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                PII
              </span>
            )}
            {field.required && (
              <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                required
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
            <span className="px-2 py-0.5 bg-gray-100 rounded font-mono">{field.type}</span>
            <span>{(field.presence_rate * 100).toFixed(0)}% present</span>
            <span>{(field.confidence * 100).toFixed(0)}% confidence</span>
          </div>
        </div>
        <span className="text-gray-400 text-sm">{expanded ? '−' : '+'}</span>
      </div>

      {expanded && (
        <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
          {field.notes && (
            <div>
              <span className="text-xs font-medium text-gray-500">Notes</span>
              <p className="text-sm text-gray-700 mt-1">{field.notes}</p>
            </div>
          )}

          {field.sample_values.length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-500">Sample Values</span>
              <div className="flex flex-wrap gap-2 mt-1">
                {field.sample_values.map((v, i) => (
                  <span
                    key={i}
                    className="px-2 py-1 bg-gray-50 border border-gray-200 rounded text-xs font-mono truncate max-w-xs"
                  >
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {field.enum_values && (
            <div>
              <span className="text-xs font-medium text-gray-500">
                Enum Values ({field.enum_values.length})
              </span>
              <div className="flex flex-wrap gap-2 mt-1">
                {field.enum_values.slice(0, 10).map((e) => (
                  <span
                    key={e.value}
                    className="px-2 py-1 bg-purple-50 border border-purple-200 rounded text-xs"
                  >
                    {e.value} <span className="text-gray-400">({e.count})</span>
                  </span>
                ))}
                {field.enum_values.length > 10 && (
                  <span className="text-xs text-gray-400">
                    +{field.enum_values.length - 10} more
                  </span>
                )}
              </div>
            </div>
          )}

          {field.range && (
            <div>
              <span className="text-xs font-medium text-gray-500">Range</span>
              <p className="text-sm font-mono mt-1">
                {field.range.min} → {field.range.max}
              </p>
            </div>
          )}

          {field.pii.length > 0 && (
            <div>
              <span className="text-xs font-medium text-gray-500">PII Categories</span>
              <div className="flex gap-2 mt-1">
                {field.pii.map((p) => (
                  <span
                    key={p}
                    className="px-2 py-1 bg-red-50 border border-red-200 rounded text-xs text-red-700"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function StreamDetail() {
  const { name } = useParams<{ name: string }>()
  const [stream, setStream] = useState<StreamDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    if (!name) return
    setLoading(true)
    api
      .getStream(name)
      .then(setStream)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [name])

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64 text-gray-500">
          Loading...
        </div>
      </Layout>
    )
  }

  if (error || !stream) {
    return (
      <Layout>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-800">Error: {error || 'Stream not found'}</p>
          <Link to="/" className="text-sm text-red-600 underline mt-2 inline-block">
            Back to Dashboard
          </Link>
        </div>
      </Layout>
    )
  }

  const filteredFields = stream.fields.filter((f) =>
    f.path.toLowerCase().includes(filter.toLowerCase())
  )

  const piiCount = stream.fields.filter((f) => f.pii.length > 0).length
  const requiredCount = stream.fields.filter((f) => f.required).length

  return (
    <Layout>
      <div className="mb-6">
        <Link to="/" className="text-sm text-gray-500 hover:text-gray-700">
          ← Back to Dashboard
        </Link>
      </div>

      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 font-mono">{stream.stream}</h1>
          <p className="text-sm text-gray-500 mt-1">
            Version {stream.version} • Inferred {new Date(stream.inferred_at).toLocaleDateString()}
          </p>
        </div>
        <div className="text-right text-sm text-gray-500">
          <p>{stream.event_count_sampled.toLocaleString()} events sampled</p>
          <p className="font-mono text-xs">{stream.inference_model}</p>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Fields</p>
          <p className="text-2xl font-semibold mt-1">{stream.fields.length}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Required</p>
          <p className="text-2xl font-semibold mt-1">{requiredCount}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">PII Fields</p>
          <p className="text-2xl font-semibold mt-1 text-red-600">{piiCount}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Sub-Schemas</p>
          <p className="text-2xl font-semibold mt-1">{stream.sub_schemas.length}</p>
        </div>
      </div>

      {stream.sub_schemas.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Event Types</h2>
          <div className="flex gap-3">
            {stream.sub_schemas.map((ss) => (
              <div
                key={ss.cluster_id}
                className="bg-white rounded-lg border border-gray-200 px-4 py-3"
              >
                <p className="font-mono text-sm">{ss.cluster_id}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {ss.event_count.toLocaleString()} events
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Fields</h2>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter fields..."
          className="px-3 py-1.5 border border-gray-300 rounded-md text-sm w-64 focus:outline-none focus:ring-1 focus:ring-gray-400"
        />
      </div>

      <div className="space-y-3">
        {filteredFields.map((field) => (
          <FieldCard key={field.path} field={field} />
        ))}
      </div>

      {filteredFields.length === 0 && (
        <div className="text-center py-8 text-gray-500">No fields match filter</div>
      )}
    </Layout>
  )
}
