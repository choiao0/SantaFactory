import Header from './components/Header.jsx'
import Hero from './components/Hero.jsx'
import WarehouseStep from './components/WarehouseStep.jsx'
import FleetStep from './components/FleetStep.jsx'
import RunsStep from './components/RunsStep.jsx'
import QuoteStep from './components/QuoteStep.jsx'
import Footer from './components/Footer.jsx'
import { useReveal } from './hooks/useReveal.js'

export default function App() {
  useReveal()
  return (
    <>
      <Header />
      <main>
        <Hero />
        <WarehouseStep />
        <FleetStep />
        <RunsStep />
        <QuoteStep />
      </main>
      <Footer />
    </>
  )
}
