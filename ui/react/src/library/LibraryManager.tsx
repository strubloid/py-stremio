import { useState } from 'react'
import { FolderOpen, Layers3, Search, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { LibraryEntry, SeriesSummary } from './types'

type Props = {
  series: SeriesSummary[]
  movies: LibraryEntry[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onRemove: (kind: 'series' | 'movie', id: number) => void
}

type Collections = Record<number, string>
const storageKey = 'py-stremio-series-collections'

export function LibraryManager({ series, movies, onOpenSeries, onOpenMovie, onRemove }: Props) {
  const [collections, setCollections] = useState<Collections>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || '{}') as Collections } catch { return {} }
  })
  const [query, setQuery] = useState('')
  const saveCollection = (id: number, value: string) => {
    const next = { ...collections }
    if (value.trim()) next[id] = value.trim()
    else delete next[id]
    setCollections(next)
    localStorage.setItem(storageKey, JSON.stringify(next))
  }
  const matches = (title: string) => title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const collectionNames = [...new Set(Object.values(collections))].sort((a, b) => a.localeCompare(b))

  return <section className="library-manager">
    <header className="library-manager-heading">
      <div><span className="browse-heading-icon"><FolderOpen size={19} /></span><h1>Library</h1><p>See where every title lives and bring related series together.</p></div>
      <label className="library-manager-search"><Search size={16} /><Input aria-label="Filter library" placeholder="Filter titles" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    </header>
    {collectionNames.length > 0 && <section className="manager-collections"><div className="manager-section-heading"><Layers3 size={17} /><h2>Series collections</h2><Badge variant="outline">{collectionNames.length}</Badge></div>
      {collectionNames.map((name) => <div className="manager-collection" key={name}><h3>{name}</h3>{series.filter((item) => collections[item.id] === name && matches(item.title)).map((item) => <button key={item.id} onClick={() => onOpenSeries(item.id)}>{item.title}<span>{item.seasons.length} {item.seasons.length === 1 ? 'season' : 'seasons'}</span></button>)}</div>)}
    </section>}
    <section className="manager-section"><div className="manager-section-heading"><h2>Series</h2><Badge variant="outline">{series.filter((item) => matches(item.title)).length}</Badge></div>
      {series.filter((item) => matches(item.title)).map((item) => <article className="manager-row" key={item.id}>
        <button className="manager-title" onClick={() => onOpenSeries(item.id)}><strong>{item.title}</strong><span>{item.downloaded}/{item.total} episodes · {item.missing} missing</span></button>
        <div className="manager-locations">{[...item.seasons].sort((a, b) => (a.season ?? 0) - (b.season ?? 0)).map((season) => <button key={season.id} onClick={() => onOpenSeries(item.id)}><Badge variant="secondary">Season {season.season ?? '—'}</Badge><code>{season.rel_path || 'Folder path unavailable'}</code></button>)}</div>
        <div className="manager-row-actions"><label className="collection-control"><span>Collection</span><Input aria-label={`Collection for ${item.title}`} list="series-collection-options" placeholder="e.g. Westeros" value={collections[item.id] || ''} onChange={(event) => saveCollection(item.id, event.target.value)} /><Button variant="ghost" size="icon-sm" aria-label={`Clear collection for ${item.title}`} onClick={() => saveCollection(item.id, '')}>×</Button></label><Button className="manager-remove" variant="outline" size="sm" onClick={() => onRemove('series', item.id)}><Trash2 size={14} /> Remove</Button></div>
      </article>)}
      {series.filter((item) => matches(item.title)).length === 0 && <p className="manager-empty">No series match that filter.</p>}
    </section>
    <datalist id="series-collection-options">{collectionNames.map((name) => <option key={name} value={name} />)}</datalist>
    <section className="manager-section"><div className="manager-section-heading"><h2>Films</h2><Badge variant="outline">{movies.filter((item) => matches(item.title)).length}</Badge></div>
      {movies.filter((item) => matches(item.title)).map((movie) => <article className="manager-row manager-movie-row" key={movie.id}><button className="manager-title" onClick={() => onOpenMovie(movie)}><strong>{movie.title}</strong><span>{movie.downloaded ? 'Downloaded' : 'Not downloaded'}</span></button><div className="manager-locations"><div><Badge variant="secondary">Movie</Badge><code>{movie.rel_path || 'Folder path unavailable'}</code></div></div><Button className="manager-remove" variant="outline" size="sm" onClick={() => onRemove('movie', movie.id)}><Trash2 size={14} /> Remove</Button></article>)}
      {movies.filter((item) => matches(item.title)).length === 0 && <p className="manager-empty">No films match that filter.</p>}
    </section>
  </section>
}
