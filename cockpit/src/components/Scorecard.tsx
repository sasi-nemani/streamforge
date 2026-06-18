import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { EvalScorecard } from '../lib/types'

function Stat({ label, value, sub, tone = 'default' }: {
  label: string
  value: string
  sub?: string
  tone?: 'default' | 'good' | 'warn'
}) {
  const valueColor =
    tone === 'good' ? 'text-emerald-600' : tone === 'warn' ? 'text-amber-600' : 'text-gray-900'
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">{label}</p>
      <p className={`text-3xl font-semibold font-mono tracking-tight ${valueColor}`}>{value}</p>
      {sub && <p className="text-sm text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function pct(n: number): string {
  return `${Math.round(n * 100)}%`
}

interface ScorecardProps {
  /** Stream to score. Defaults to the first available benchmark. */
  stream?: string
}

export function Scorecard({ stream }: ScorecardProps) {
  const [card, setCard] = useState<EvalScorecard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const name = stream ?? (await api.getBenchmarks()).benchmarks[0]
        if (!name) {
          if (active) setError('No labeled benchmarks available')
          return
        }
        const data = await api.getEval(name)
        if (active) setCard(data)
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Failed to load scorecard')
      }
    }
    load()
    return () => {
      active = false
    }
  }, [stream])

  if (error) {
    return <p className="text-sm text-gray-400">Scorecard unavailable: {error}</p>
  }
  if (!card) {
    return <div className="h-32 bg-gray-50 rounded-lg border border-gray-200 animate-pulse" />
  }

  const calTone = card.calibration.ece <= 0.1 ? 'good' : card.calibration.ece <= 0.2 ? 'default' : 'warn'

  return (
    <section>
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Does it work?</h2>
          <p className="text-sm text-gray-500">
            Scored against hand-labeled ground truth — <span className="font-mono">{card.stream}</span>,
            reproducible (seed {card.seed})
          </p>
        </div>
        <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600 font-mono">
          {card.inference_path}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat
          label="Schema F1"
          value={card.schema.type_f1.toFixed(2)}
          sub={`type-acc ${pct(card.schema.type_accuracy)}`}
          tone="good"
        />
        <Stat label="PII F1" value={card.schema.pii_f1.toFixed(2)} tone="good" />
        <Stat
          label="Drift F1"
          value={card.drift.f1.toFixed(2)}
          sub={`P ${card.drift.precision.toFixed(2)} · R ${card.drift.recall.toFixed(2)}`}
          tone="good"
        />
        <Stat
          label="False positives"
          value={pct(card.drift.fpr_null)}
          sub="on clean data (null)"
          tone={card.drift.fpr_null === 0 ? 'good' : 'warn'}
        />
        <Stat
          label="Calibration (ECE)"
          value={card.calibration.ece.toFixed(2)}
          sub={card.calibration.rating}
          tone={calTone}
        />
      </div>

      <div className="mt-4">
        <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Injected drift scenarios</p>
        <div className="flex flex-wrap gap-2">
          {card.drift.scenarios.map((s) => (
            <span
              key={s.label}
              className={`text-xs px-2.5 py-1 rounded-full font-mono border ${
                s.caught
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : 'bg-gray-50 text-gray-400 border-gray-200'
              }`}
              title={`F1 ${s.f1}`}
            >
              {s.caught ? '✓' : '○'} {s.label}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}
