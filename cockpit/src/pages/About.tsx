import { useState, useEffect } from 'react'
import { Layout } from '../components/Layout'
import { ArchitectureDiagram } from '../components/ArchitectureDiagram'
import { api } from '../lib/api'
import type { Connector } from '../lib/types'

const faqs = [
  {
    q: 'What is StreamForge?',
    a: 'StreamForge is an automatic schema inference and drift detection system for streaming data. It connects to your event sources (Kafka, files, etc.), samples events, infers schemas using AI, and continuously monitors for schema drift.',
  },
  {
    q: 'How does schema inference work?',
    a: 'StreamForge samples events from your streams and uses LLM-powered inference (with statistical fallback) to detect field types, required/optional status, and nested structures. It achieves 90%+ accuracy on real-world data.',
  },
  {
    q: 'What is schema drift?',
    a: 'Schema drift occurs when the structure of incoming data changes over time — new fields appear, types change, or required fields become optional. StreamForge detects these changes in real-time and classifies them by severity (Tier 1-3).',
  },
  {
    q: 'How is PII detected?',
    a: 'PII detection uses pattern matching and heuristics to identify sensitive fields like emails, phone numbers, IP addresses, and names. No data leaves your infrastructure — all detection runs locally.',
  },
  {
    q: 'What file formats are supported?',
    a: 'The file connector supports JSON, NDJSON/JSONL, CSV, and TSV files. Format detection is automatic based on content analysis. New formats can be added via the pluggable parser architecture.',
  },
  {
    q: 'Can I use StreamForge without Kafka?',
    a: 'Yes. The file connector allows you to point at any directory containing data files. StreamForge will ingest, infer schemas, and monitor for drift just like with Kafka streams.',
  },
  {
    q: 'How do I fix a detected drift?',
    a: 'Drift reports are generated as Markdown files in the schema directory. Review the report, update your schema.yaml if the change is intentional, or fix your producer if the change is a bug.',
  },
  {
    q: 'Is my data sent to external services?',
    a: 'Schema inference can use external LLM APIs (configurable), but only field names and sample values are sent — never full payloads. PII detection and drift monitoring run entirely locally.',
  },
]

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between py-4 text-left"
      >
        <span className="text-sm font-medium text-gray-900">{q}</span>
        <span className="text-gray-400 ml-4">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <p className="text-sm text-gray-600 pb-4 pr-8">{a}</p>
      )}
    </div>
  )
}

export function About() {
  const [connectors, setConnectors] = useState<Connector[]>([])

  useEffect(() => {
    api.getConnectors().then(setConnectors).catch(() => {})
  }, [])

  return (
    <Layout>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-gray-900">About StreamForge</h1>
        <p className="text-sm text-gray-500 mt-1">
          Automatic schema inference and drift detection for streaming data
        </p>
      </div>

      <div className="grid grid-cols-2 gap-6 mb-8">
        <ArchitectureDiagram connectors={connectors} />

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-sm font-medium text-gray-700 mb-4">Available Connectors</h3>
          <div className="space-y-3">
            {connectors.map((c) => (
              <div key={c.type} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full ${c.configured ? 'bg-green-500' : c.available ? 'bg-gray-300' : 'bg-gray-200'}`} />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{c.name}</p>
                    <p className="text-xs text-gray-500">{c.description}</p>
                  </div>
                </div>
                <div className="flex gap-1">
                  {c.formats.slice(0, 3).map((f) => (
                    <span key={f} className="px-1.5 py-0.5 bg-gray-100 rounded text-xs font-mono">{f}</span>
                  ))}
                  {c.formats.length > 3 && (
                    <span className="text-xs text-gray-400">+{c.formats.length - 3}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Frequently Asked Questions</h3>
        <div className="divide-y divide-gray-100">
          {faqs.map((faq, i) => (
            <FaqItem key={i} q={faq.q} a={faq.a} />
          ))}
        </div>
      </div>
    </Layout>
  )
}
