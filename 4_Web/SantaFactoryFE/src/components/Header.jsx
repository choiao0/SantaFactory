const LINKS = [
  ['#s1', 'WAREHOUSE'],
  ['#s2', 'FLEET'],
  ['#s3', 'RUNS'],
  ['#verify', 'VERIFY'],
  ['#quote', 'QUOTE'],
]

export default function Header() {
  return (
    <header className="header">
      <a className="brand" href="#top">
        <img className="brand-mark" src="/santafactory-logo.png" alt="Santa Factory" width={30} height={30} />
        SANTA FACTORY
        <small>AMR FLEET QUOTE</small>
      </a>
      <nav className="header-links">
        {LINKS.map(([href, label]) => (
          <a key={href} href={href}>{label}</a>
        ))}
      </nav>
    </header>
  )
}
