interface ConnectorInfo {
  type: string
  name: string
  configured: boolean
}

interface ArchitectureDiagramProps {
  connectors?: ConnectorInfo[]
}

export function ArchitectureDiagram({ connectors = [] }: ArchitectureDiagramProps) {
  const configuredConnectors = connectors.filter((c) => c.configured)

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-sm font-medium text-gray-700 mb-4">System Architecture</h3>
      <svg viewBox="0 0 400 200" className="w-full h-auto">
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#9CA3AF" />
          </marker>
        </defs>

        {/* Sources Column */}
        <g transform="translate(10, 20)">
          <text x="30" y="0" className="text-xs fill-gray-500 font-medium">SOURCES</text>

          {/* Kafka */}
          <rect x="0" y="15" width="80" height="35" rx="4"
            className={configuredConnectors.some(c => c.type === 'kafka') ? 'fill-green-50 stroke-green-300' : 'fill-gray-50 stroke-gray-200'}
            strokeWidth="1.5" />
          <text x="40" y="37" textAnchor="middle" className="text-xs fill-gray-700">Kafka</text>

          {/* File */}
          <rect x="0" y="60" width="80" height="35" rx="4"
            className={configuredConnectors.some(c => c.type === 'file') ? 'fill-green-50 stroke-green-300' : 'fill-gray-50 stroke-gray-200'}
            strokeWidth="1.5" />
          <text x="40" y="82" textAnchor="middle" className="text-xs fill-gray-700">Files</text>

          {/* Cloud */}
          <rect x="0" y="105" width="80" height="35" rx="4" className="fill-gray-50 stroke-gray-200" strokeWidth="1.5" strokeDasharray="4" />
          <text x="40" y="127" textAnchor="middle" className="text-xs fill-gray-400">Kinesis/PubSub</text>
        </g>

        {/* Arrows: Sources → StreamForge */}
        <line x1="95" y1="52" x2="130" y2="100" stroke="#9CA3AF" strokeWidth="1.5" markerEnd="url(#arrowhead)" />
        <line x1="95" y1="97" x2="130" y2="100" stroke="#9CA3AF" strokeWidth="1.5" markerEnd="url(#arrowhead)" />
        <line x1="95" y1="142" x2="130" y2="100" stroke="#9CA3AF" strokeWidth="1.5" strokeDasharray="4" markerEnd="url(#arrowhead)" />

        {/* StreamForge Core */}
        <g transform="translate(135, 50)">
          <rect x="0" y="0" width="130" height="100" rx="6" className="fill-gray-900" />
          <text x="65" y="20" textAnchor="middle" className="text-xs fill-white font-semibold">StreamForge</text>

          {/* Internal modules */}
          <rect x="10" y="30" width="50" height="25" rx="3" className="fill-gray-700" />
          <text x="35" y="47" textAnchor="middle" className="text-[9px] fill-gray-300">Sampler</text>

          <rect x="70" y="30" width="50" height="25" rx="3" className="fill-gray-700" />
          <text x="95" y="47" textAnchor="middle" className="text-[9px] fill-gray-300">Inference</text>

          <rect x="10" y="65" width="50" height="25" rx="3" className="fill-gray-700" />
          <text x="35" y="82" textAnchor="middle" className="text-[9px] fill-gray-300">PII</text>

          <rect x="70" y="65" width="50" height="25" rx="3" className="fill-gray-700" />
          <text x="95" y="82" textAnchor="middle" className="text-[9px] fill-gray-300">Drift</text>
        </g>

        {/* Arrow: StreamForge → Outputs */}
        <line x1="270" y1="100" x2="295" y2="52" stroke="#9CA3AF" strokeWidth="1.5" markerEnd="url(#arrowhead)" />
        <line x1="270" y1="100" x2="295" y2="100" stroke="#9CA3AF" strokeWidth="1.5" markerEnd="url(#arrowhead)" />
        <line x1="270" y1="100" x2="295" y2="148" stroke="#9CA3AF" strokeWidth="1.5" markerEnd="url(#arrowhead)" />

        {/* Outputs Column */}
        <g transform="translate(300, 20)">
          <text x="40" y="0" className="text-xs fill-gray-500 font-medium">OUTPUTS</text>

          {/* Schema */}
          <rect x="0" y="15" width="90" height="35" rx="4" className="fill-blue-50 stroke-blue-300" strokeWidth="1.5" />
          <text x="45" y="37" textAnchor="middle" className="text-xs fill-blue-700">schema.yaml</text>

          {/* Alerts */}
          <rect x="0" y="60" width="90" height="35" rx="4" className="fill-amber-50 stroke-amber-300" strokeWidth="1.5" />
          <text x="45" y="82" textAnchor="middle" className="text-xs fill-amber-700">Drift Alerts</text>

          {/* Audit */}
          <rect x="0" y="105" width="90" height="35" rx="4" className="fill-purple-50 stroke-purple-300" strokeWidth="1.5" />
          <text x="45" y="127" textAnchor="middle" className="text-xs fill-purple-700">audit.jsonl</text>
        </g>

        {/* Legend */}
        <g transform="translate(10, 175)">
          <circle cx="5" cy="5" r="4" className="fill-green-300" />
          <text x="15" y="9" className="text-[9px] fill-gray-500">Active</text>
          <circle cx="60" cy="5" r="4" className="fill-gray-200" />
          <text x="70" y="9" className="text-[9px] fill-gray-500">Available</text>
          <line x1="115" y1="5" x2="130" y2="5" stroke="#9CA3AF" strokeWidth="1.5" strokeDasharray="4" />
          <text x="135" y="9" className="text-[9px] fill-gray-500">Coming Soon</text>
        </g>
      </svg>
    </div>
  )
}
