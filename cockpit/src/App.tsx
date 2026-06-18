import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { BlastRadius } from './pages/BlastRadius'
import { Dashboard } from './pages/Dashboard'
import { Catalog } from './pages/Catalog'
import { Schemas } from './pages/Schemas'
import { StreamDetail } from './pages/StreamDetail'
import { About } from './pages/About'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<BlastRadius />} />
        <Route path="/overview" element={<Dashboard />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/schemas" element={<Schemas />} />
        <Route path="/stream/:name" element={<StreamDetail />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
