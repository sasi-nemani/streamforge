import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

interface LayoutProps {
  children: ReactNode
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation()

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <header className="border-b border-gray-200 bg-white">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-3">
              <div className="w-8 h-8 bg-black rounded flex items-center justify-center">
                <span className="text-white font-mono text-sm font-bold">SF</span>
              </div>
              <h1 className="text-xl font-semibold text-gray-900">StreamForge</h1>
              <span className="text-xs text-gray-400 font-mono">COCKPIT</span>
            </Link>
            <nav className="flex items-center gap-4 ml-8">
              <Link
                to="/"
                className={`text-sm ${location.pathname === '/' ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'}`}
              >
                Blast Radius
              </Link>
              <Link
                to="/overview"
                className={`text-sm ${location.pathname === '/overview' ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'}`}
              >
                Dashboard
              </Link>
              <Link
                to="/catalog"
                className={`text-sm ${location.pathname === '/catalog' ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'}`}
              >
                Catalog
              </Link>
              <Link
                to="/schemas"
                className={`text-sm ${location.pathname === '/schemas' ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'}`}
              >
                Schemas
              </Link>
              <Link
                to="/about"
                className={`text-sm ${location.pathname === '/about' ? 'text-gray-900 font-medium' : 'text-gray-500 hover:text-gray-700'}`}
              >
                About
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">Schema Drift Detection</span>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-6 py-8">
        {children}
      </main>
    </div>
  )
}
