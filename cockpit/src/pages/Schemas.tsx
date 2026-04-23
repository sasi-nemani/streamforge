import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Layout } from '../components/Layout'
import { api } from '../lib/api'
import type { Source, StreamDetail } from '../lib/types'

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    string: 'bg-slate-100 text-slate-700',
    uuid: 'bg-violet-100 text-violet-700',
    email: 'bg-blue-100 text-blue-700',
    timestamp_epoch_ms: 'bg-amber-100 text-amber-700',
    object: 'bg-cyan-100 text-cyan-700',
    mixed: 'bg-orange-100 text-orange-700',
    integer: 'bg-emerald-100 text-emerald-700',
    boolean: 'bg-pink-100 text-pink-700',
  }
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${colors[type] || 'bg-gray-100 text-gray-600'}`}>
      {type}
    </span>
  )
}

function StreamTypeBadge({ name }: { name: string }) {
  const lower = name.toLowerCase()
  let type = 'File'
  let icon = '📁'
  let color = 'bg-gray-100 text-gray-700'

  if (lower.includes('kafka') || lower.includes('events.')) {
    type = 'Kafka'
    icon = '📨'
    color = 'bg-purple-100 text-purple-700'
  } else if (lower.includes('sqs') || lower.includes('queue')) {
    type = 'SQS'
    icon = '📬'
    color = 'bg-orange-100 text-orange-700'
  } else if (lower.includes('kinesis')) {
    type = 'Kinesis'
    icon = '🌊'
    color = 'bg-blue-100 text-blue-700'
  }

  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${color}`}>
      {icon} {type}
    </span>
  )
}

function StatusDot({ hasDrift, hasPii }: { hasDrift: boolean; hasPii: boolean }) {
  if (hasDrift) {
    return (
      <span className="flex items-center gap-1.5 text-red-600">
        <span className="w-2 h-2 rounded-full bg-red-500" />
        <span className="text-xs font-medium">Drift</span>
      </span>
    )
  }
  if (hasPii) {
    return (
      <span className="flex items-center gap-1.5 text-amber-600">
        <span className="w-2 h-2 rounded-full bg-amber-500" />
        <span className="text-xs font-medium">PII</span>
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1.5 text-green-600">
      <span className="w-2 h-2 rounded-full bg-green-500" />
      <span className="text-xs font-medium">Healthy</span>
    </span>
  )
}

interface SchemaCard {
  source: Source
  detail: StreamDetail | null
  hasPii: boolean
}

export function Schemas() {
  const [schemas, setSchemas] = useState<SchemaCard[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedStream, setExpandedStream] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const sources = await api.getSources()

        const cards: SchemaCard[] = await Promise.all(
          sources.map(async (source) => {
            try {
              const detail = await api.getStream(source.name)
              const hasPii = detail.fields.some((f) => f.pii.length > 0)
              return { source, detail, hasPii }
            } catch {
              return { source, detail: null, hasPii: false }
            }
          })
        )
        setSchemas(cards)
      } catch (err) {
        console.error('Failed to load schemas:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const stats = {
    total: schemas.length,
    fields: schemas.reduce((sum, s) => sum + (s.detail?.fields.length || 0), 0),
    pii: schemas.filter((s) => s.hasPii).length,
    multiSchema: schemas.filter((s) => (s.detail?.sub_schemas?.length || 0) > 1).length,
  }

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-64 text-gray-500">
          Loading schemas...
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Auto-Inferred Schemas</h1>
        <p className="text-sm text-gray-500 mt-1">
          All schemas discovered by StreamForge across your data streams
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-2xl font-semibold text-gray-900">{stats.total}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mt-1">Streams</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-2xl font-semibold text-gray-900">{stats.fields}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mt-1">Total Fields</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-2xl font-semibold text-amber-600">{stats.pii}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mt-1">With PII</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-2xl font-semibold text-purple-600">{stats.multiSchema}</div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mt-1">Multi-Schema</div>
        </div>
      </div>

      {schemas.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          No schemas found. Run <code className="bg-gray-100 px-1 rounded">streamforge init</code> to infer your first schema.
        </div>
      ) : (
        <div className="space-y-4">
          {schemas.map(({ source, detail, hasPii }) => {
            const isExpanded = expandedStream === source.name
            const fieldCount = detail?.fields.length || 0
            const subSchemaCount = detail?.sub_schemas?.length || 0

            return (
              <div key={source.name} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div
                  className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedStream(isExpanded ? null : source.name)}
                >
                  <div className="flex items-center gap-4">
                    <span className="text-gray-400 text-sm">{isExpanded ? '▼' : '▶'}</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/stream/${source.name}`}
                          className="font-medium text-gray-900 hover:text-blue-600"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {source.name}
                        </Link>
                        <StreamTypeBadge name={source.name} />
                        {subSchemaCount > 1 && (
                          <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs">
                            {subSchemaCount} event types
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {fieldCount} fields • Inferred {detail?.inferred_at ? new Date(detail.inferred_at).toLocaleDateString() : 'unknown'}
                      </div>
                    </div>
                  </div>
                  <StatusDot hasDrift={source.status === 'error'} hasPii={hasPii} />
                </div>

                {isExpanded && detail && (
                  <div className="border-t border-gray-100">
                    <div className="px-4 py-3 bg-gray-50">
                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div>
                          <span className="text-xs text-gray-500 uppercase tracking-wide">Model</span>
                          <div className="font-medium text-gray-900 mt-0.5">{detail.inference_model || 'statistical'}</div>
                        </div>
                        <div>
                          <span className="text-xs text-gray-500 uppercase tracking-wide">Events Sampled</span>
                          <div className="font-medium text-gray-900 mt-0.5">{detail.event_count_sampled?.toLocaleString() || detail.sample_count?.toLocaleString() || '—'}</div>
                        </div>
                        <div>
                          <span className="text-xs text-gray-500 uppercase tracking-wide">Version</span>
                          <div className="font-medium text-gray-900 mt-0.5">{detail.version || '1.0'}</div>
                        </div>
                      </div>
                    </div>

                    {subSchemaCount > 1 && (
                      <div className="px-4 py-3 border-t border-gray-100">
                        <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Event Types</div>
                        <div className="flex flex-wrap gap-2">
                          {detail.sub_schemas.map((sub) => (
                            <span
                              key={sub.cluster_id}
                              className="px-2 py-1 bg-purple-50 border border-purple-200 rounded text-xs"
                            >
                              {sub.cluster_id}
                              <span className="text-purple-400 ml-1">({sub.event_count})</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="px-4 py-3 border-t border-gray-100">
                      <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Field Schema</div>
                      <div className="bg-gray-50 rounded border border-gray-200 overflow-hidden">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="bg-gray-100 text-xs text-gray-500 uppercase tracking-wide">
                              <th className="text-left px-3 py-2 font-medium">Field</th>
                              <th className="text-left px-3 py-2 font-medium">Type</th>
                              <th className="text-center px-3 py-2 font-medium">Required</th>
                              <th className="text-center px-3 py-2 font-medium">Presence</th>
                              <th className="text-left px-3 py-2 font-medium">PII</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.fields.slice(0, 15).map((field) => (
                              <tr key={field.path} className="border-t border-gray-100">
                                <td className="px-3 py-2">
                                  <code className="text-xs text-blue-600">{field.path}</code>
                                </td>
                                <td className="px-3 py-2">
                                  <TypeBadge type={field.type} />
                                </td>
                                <td className="px-3 py-2 text-center">
                                  {field.required ? '✓' : '—'}
                                </td>
                                <td className="px-3 py-2 text-center text-gray-500">
                                  {(field.presence_rate * 100).toFixed(0)}%
                                </td>
                                <td className="px-3 py-2">
                                  {field.pii.length > 0 && (
                                    <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                                      {field.pii.join(', ')}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {detail.fields.length > 15 && (
                          <div className="px-3 py-2 text-center text-xs text-gray-500 border-t border-gray-200">
                            +{detail.fields.length - 15} more fields —{' '}
                            <Link to={`/stream/${source.name}`} className="text-blue-600 hover:underline">
                              View all
                            </Link>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Layout>
  )
}
