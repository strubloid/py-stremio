import { ArrowRight, Film, Play, Tv } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import type { LibraryEntry, SeriesSummary, Section } from './types'

type Props = {
  section: Section
  series: SeriesSummary[]
  movies: LibraryEntry[]
  search: string
  onOpenSeries: (seriesId: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
}

export function LibraryHome({ section, series, movies, search, onOpenSeries, onOpenMovie }: Props) {
  const filteredSeries = series.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
  const filteredMovies = movies.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
  const continueWatching = filteredSeries.filter((item) => item.unwatchedDownloaded > 0)
  const incompleteSeries = filteredSeries.filter((item) => item.missing > 0)
  const featured = incompleteSeries[0] ?? filteredSeries[0]

  if (section === 'series') {
    return <section className="browse-page"><PageHeading icon={<Tv size={18} />} title="Series" count={filteredSeries.length} /><div className="cover-grid">{filteredSeries.map((item, index) => <SeriesCover item={item} index={index} onOpen={onOpenSeries} key={item.id} />)}</div>{filteredSeries.length === 0 && <EmptyState text={search ? 'No series match your search.' : 'No series in the catalog yet.'} />}</section>
  }

  if (section === 'movies') {
    return <section className="browse-page"><PageHeading icon={<Film size={18} />} title="Films" count={filteredMovies.length} /><div className="cover-grid">{filteredMovies.map((item, index) => <MovieCover item={item} index={index} onOpen={onOpenMovie} key={item.id} />)}</div>{filteredMovies.length === 0 && <EmptyState text={search ? 'No films match your search.' : 'No films in the catalog yet.'} />}</section>
  }

  return (
    <div className="browse-home">
      {featured ? <section className="feature-banner">
        {featured.background_url && <img className="feature-backdrop" src={featured.background_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} />}
        <div className="feature-copy">
          <Badge variant="outline">YOUR LIBRARY · SERIES</Badge>
          <h1>{featured.title}</h1>
          <p>{featured.seasons.length} {featured.seasons.length === 1 ? 'season' : 'seasons'} <span>·</span> {featured.downloaded} of {featured.total} episodes downloaded <span>·</span> {featured.missing} missing</p>
          <div className="feature-actions">
            <Button onClick={() => onOpenSeries(featured.id)}><Play data-icon="inline-start" size={16} fill="currentColor" /> Open series</Button>
            <Button variant="secondary" onClick={() => onOpenSeries(featured.id)}>Season details <ArrowRight data-icon="inline-end" size={16} /></Button>
          </div>
        </div>
        <div className="feature-mark" aria-hidden="true">{featured.poster_url ? <img src={featured.poster_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} /> : <span>{featured.title.slice(0, 1).toUpperCase()}</span>}</div>
      </section> : <div className="feature-empty"><h1>Your screen, your library.</h1><p>Import your folders to browse series, seasons, films, and episodes here.</p></div>}

      <SeriesRail title="Continue watching" items={continueWatching} onOpenSeries={onOpenSeries} />
      <SeriesRail title="Keep exploring series" items={incompleteSeries} onOpenSeries={onOpenSeries} />
      <MovieRail title="Films" items={filteredMovies} onOpenMovie={onOpenMovie} />
      <SeriesRail title="All series" items={filteredSeries} onOpenSeries={onOpenSeries} />
      {!featured && filteredMovies.length === 0 && <EmptyState text="Run `py-stremio migrate` to bring your folder library into the catalog." />}
    </div>
  )
}

const coverStyles = ['cover--ember', 'cover--violet', 'cover--ice', 'cover--moss', 'cover--rose']

function SeriesCover({ item, index, onOpen }: { item: SeriesSummary; index: number; onOpen: (seriesId: number) => void }) {
  const progress = item.total ? Math.round(item.downloaded / item.total * 100) : 0
  return (
    <article className="media-cover-wrap">
      <Button className={`media-cover ${coverStyles[index % coverStyles.length]}`} variant="ghost" onClick={() => onOpen(item.id)} aria-label={`Open ${item.title}`}>
        {item.poster_url && <img className="cover-image" src={item.poster_url} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
        <span className="cover-overline">SERIES <span>·</span> {item.seasons.length} {item.seasons.length === 1 ? 'season' : 'seasons'}</span>
        <span className="cover-title">{item.title}</span>
        <span className="cover-meta">{item.downloaded} / {item.total} episodes</span>
        <span className="cover-play"><Play size={14} fill="currentColor" /> Open series</span>
      </Button>
      {item.total > 0 && <Progress className="cover-progress" value={progress} aria-label={`${item.title} ${progress}% downloaded`} />}
      <span className="cover-caption">{item.title}</span>
    </article>
  )
}

function MovieCover({ item, index, onOpen }: { item: LibraryEntry; index: number; onOpen: (movie: LibraryEntry) => void }) {
  return (
    <article className="media-cover-wrap">
      <Button className={`media-cover movie-cover ${coverStyles[index % coverStyles.length]}`} variant="ghost" onClick={() => onOpen(item)} aria-label={`Open ${item.title}`}>
        {item.poster_url && <img className="cover-image" src={item.poster_url} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
        <span className="cover-overline">FILM</span>
        <span className="cover-title">{item.title}</span>
        <span className="cover-meta">{item.watched ? 'Watched' : item.downloaded ? 'In your library' : 'Not downloaded'}</span>
        <span className="cover-play"><Play size={14} fill="currentColor" /> Open film</span>
      </Button>
      <span className="cover-caption">{item.title}</span>
    </article>
  )
}

function SeriesRail({ title, items, onOpenSeries }: { title: string; items: SeriesSummary[]; onOpenSeries: (seriesId: number) => void }) {
  if (!items.length) return null
  return <section className="browse-rail"><div className="rail-heading"><h2>{title}</h2><span>{items.length} titles</span></div><div className="rail-track">{items.map((item, index) => <SeriesCover item={item} index={index} onOpen={onOpenSeries} key={item.id} />)}</div></section>
}

function MovieRail({ title, items, onOpenMovie }: { title: string; items: LibraryEntry[]; onOpenMovie: (movie: LibraryEntry) => void }) {
  if (!items.length) return null
  return <section className="browse-rail"><div className="rail-heading"><h2>{title}</h2><span>{items.length} titles</span></div><div className="rail-track">{items.map((item, index) => <MovieCover item={item} index={index} onOpen={onOpenMovie} key={item.id} />)}</div></section>
}

function PageHeading({ icon, title, count }: { icon: ReactNode; title: string; count: number }) {
  return <header className="browse-heading"><span className="browse-heading-icon">{icon}</span><h1>{title}</h1><Badge variant="secondary">{count}</Badge></header>
}

function EmptyState({ text }: { text: string }) {
  return <div className="browse-empty"><div className="empty-glyph"><Tv size={21} /></div><h2>Nothing here yet</h2><p>{text}</p></div>
}
