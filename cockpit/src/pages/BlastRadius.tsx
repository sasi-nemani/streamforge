import { useEffect, useState } from 'react'
import { Layout } from '../components/Layout'
import { api } from '../lib/api'
import type { GraphOverview, FieldDetail, Inconsistency, SharedField } from '../lib/types'

function Stat({ label, value, danger }: { label: string; value: number; danger?: boolean }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">{label}</p>
      <p className={`text-3xl font-semibold font-mono ${danger && value > 0 ? 'text-red-600' : 'text-gray-900'}`}>
        {value}
      </p>
    </div>
  )
}

function TypeChip({ type, streams, primary }: { type: string; streams: string[]; primary: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border ${
        primary
          ? 'bg-gray-50 text-gray-700 border-gray-200'
          : 'bg-red-50 text-red-700 border-red-200'
      }`}
    >
      <span className="font-mono font-semibold">{type}</span>
      <span className="text-gray-400">·</span>
      <span className="text-gray-500">{streams.join(', ')}</span>
    </span>
  )
}

function InconsistencyCard({ inc, onSelect }: { inc: Inconsistency; onSelect: (f: string) => void }) {
  return (
    <button
      onClick={() => onSelect(inc.field_path)}
      className="text-left w-full bg-white rounded-lg border border-gray-200 hover:border-red-300 hover:shadow-sm transition p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-sm font-semibold text-gray-900">{inc.field_path}</span>
        <span className="text-xs text-red-600">{inc.types.length} conflicting types →</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {inc.types.map((t, i) => (
          <TypeChip key={t.type} type={t.type} streams={t.streams} primary={i === 0} />
        ))}
      </div>
    </button>
  )
}

function BlastPanel({ field, onClose }: { field: string; onClose: () => void }) {
  const [detail, setDetail] = useState<FieldDetail | null>(null)

  useEffect(() => {
    let active = true
    api.getFieldDetail(field).then((d) => {
      if (active) setDetail(d)
    })
    return () => {
      active = false
    }
  }, [field])

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 sticky top-6">
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Blast radius</p>
          <p className="font-mono text-sm font-semibold text-gray-900">{field}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm">✕</button>
      </div>

      {!detail ? (
        <div className="h-24 bg-gray-50 rounded animate-pulse" />
      ) : (
        <>
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">
            Appears in {detail.usages.length} topic{detail.usages.length === 1 ? '' : 's'}
          </p>
          <div className="divide-y divide-gray-100 mb-4">
            {detail.usages.map((u) => (
              <div key={u.stream} className="flex items-center justify-between py-1.5 text-sm">
                <span className="font-mono text-gray-700">{u.stream}</span>
                <span className="flex items-center gap-2">
                  {u.pii.length > 0 && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700">PII</span>
                  )}
                  <span className="font-mono text-xs text-gray-500">{u.type}</span>
                </span>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Downstream consumers at risk</p>
            {detail.hard_breaks ? (
              <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">
                {detail.hard_breaks} hard break{detail.hard_breaks === 1 ? '' : 's'}
              </span>
            ) : null}
          </div>
          {detail.consumers.length > 0 ? (
            <div className="space-y-1.5">
              {detail.consumers.map((c, i) => (
                <div
                  key={`${c.consumer}-${c.stream}-${i}`}
                  className={`flex items-center justify-between rounded border px-2.5 py-1.5 ${
                    c.required ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'
                  }`}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{c.consumer}</p>
                    <p className="text-xs text-gray-500">
                      {c.team} · via <span className="font-mono">{c.stream}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-xs text-gray-400 uppercase">{c.criticality}</span>
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded ${
                        c.required ? 'bg-red-600 text-white' : 'bg-gray-200 text-gray-600'
                      }`}
                    >
                      {c.required ? 'breaks' : 'degraded'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-400">
              No consumers registered for this field — add a consumers.yaml or run
              Kafka consumer discovery to map downstream impact.
            </p>
          )}
        </>
      )}
    </div>
  )
}

export function BlastRadius() {
  const [data, setData] = useState<GraphOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    api.getGraph().then(setData).catch((e) =>
      setError(e instanceof Error ? e.message : 'Failed to load dependency graph'),
    )
  }, [])

  if (error) {
    return (
      <Layout>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-800">Error: {error}</p>
          <p className="text-sm text-red-600 mt-2">Start the API: uvicorn streamforge.api.main:app</p>
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">Cross-Topic Dependencies</h1>
        <p className="text-sm text-gray-500 mt-1">
          The same field, defined differently across your streams — the integration bugs no schema registry catches.
        </p>
      </div>

      {!data ? (
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-gray-50 rounded-lg border border-gray-200 animate-pulse" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <Stat label="Fields" value={data.overview.fields} />
            <Stat label="Streams" value={data.overview.streams} />
            <Stat label="Shared fields" value={data.overview.shared_fields} />
            <Stat label="Inconsistencies" value={data.overview.inconsistencies} danger />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <section>
                <h2 className="text-lg font-semibold text-gray-900 mb-1">
                  Inconsistent fields
                  <span className="ml-2 text-sm font-normal text-red-600">
                    {data.inconsistencies.length} found
                  </span>
                </h2>
                <p className="text-sm text-gray-500 mb-4">
                  These fields carry different types across topics — each is a latent integration bug.
                </p>
                {data.inconsistencies.length === 0 ? (
                  <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-gray-500">
                    ✓ No cross-topic type conflicts
                  </div>
                ) : (
                  <div className="space-y-3">
                    {data.inconsistencies.map((inc) => (
                      <InconsistencyCard key={inc.field_path} inc={inc} onSelect={setSelected} />
                    ))}
                  </div>
                )}
              </section>

              <section>
                <h2 className="text-lg font-semibold text-gray-900 mb-3">Shared fields</h2>
                <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
                  {data.shared_fields.slice(0, 20).map((f: SharedField) => (
                    <button
                      key={f.field_path}
                      onClick={() => setSelected(f.field_path)}
                      className="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center justify-between"
                    >
                      <span className="font-mono text-sm text-gray-800">
                        {f.field_path}
                        {f.inconsistent && <span className="ml-2 text-xs text-red-600">⚠ inconsistent</span>}
                        {f.pii.length > 0 && (
                          <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700">PII</span>
                        )}
                      </span>
                      <span className="text-xs text-gray-500">{f.count} streams →</span>
                    </button>
                  ))}
                </div>
              </section>
            </div>

            <div>
              {selected ? (
                <BlastPanel field={selected} onClose={() => setSelected(null)} />
              ) : (
                <div className="bg-gray-50 rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-400 sticky top-6">
                  Select a field to see its blast radius — every topic it touches and the consumers at risk.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </Layout>
  )
}
