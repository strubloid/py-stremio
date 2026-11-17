import { ArrowLeft, ArrowRight, ArrowUpDown, Film, Play, Tv } from 'lucide-react'
import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { LibraryEntry, SeriesSummary, Section, LibraryLayout, SpotlightItem } from './types'

type Props = {
  section: Section
  series: SeriesSummary[]
  movies: LibraryEntry[]
  spotlight: SpotlightItem[]
  search: string
  layout: LibraryLayout
  onOpenSeries: (seriesId: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onOpenSpotlight: (item: SpotlightItem) => void
  onRefreshSpotlight: () => void
}

type CardLayout = 'poster' | 'backdrop' | 'compact' | 'mosaic' | 'editorial'

export function LibraryHome({ section, series, movies, spotlight, search, layout, onOpenSeries, onOpenMovie, onOpenSpotlight, onRefreshSpotlight }: Props) {
  const [spotlightIndex, setSpotlightIndex] = useState(0)
  const filteredSeries = series.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
  const filteredMovies = movies.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
  const continueWatching = filteredSeries.filter((item) => item.unwatchedDownloaded > 0)
  const incompleteSeries = filteredSeries.filter((item) => item.missing > 0)
  const showPreviousSpotlight = () => setSpotlightIndex((index) => (index - 1 + spotlight.length) % spotlight.length)
  const showNextSpotlight = () => setSpotlightIndex((index) => (index + 1) % spotlight.length)
  const cardLayout: CardLayout = layout === 'backdrop' || layout === 'mosaic' || layout === 'editorial'
    ? layout
    : layout === 'streaming' || layout === 'smart' ? 'compact' : 'poster'

  if (section === 'series') {
    if (layout === 'smart') return <SmartLibrary title="Series" series={filteredSeries} movies={[]} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} />
    return <section className={`browse-page browse-page--${layout}`}><PageHeading icon={<Tv size={18} />} title="Series" count={filteredSeries.length} /><div className={`cover-grid cover-grid--${layout}`}>{filteredSeries.map((item, index) => <SeriesCover item={item} index={index} layout={cardLayout} featured={layout === 'mosaic' && index === 0} onOpen={onOpenSeries} key={item.id} />)}</div>{filteredSeries.length === 0 && <EmptyState text={search ? 'No series match your search.' : 'No series in the catalog yet.'} />}</section>
  }

  if (section === 'movies') {
    if (layout === 'smart') return <SmartLibrary title="Films" series={[]} movies={filteredMovies} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} />
    return <section className={`browse-page browse-page--${layout}`}><PageHeading icon={<Film size={18} />} title="Films" count={filteredMovies.length} /><div className={`cover-grid cover-grid--${layout}`}>{filteredMovies.map((item, index) => <MovieCover item={item} index={index} layout={cardLayout} featured={layout === 'mosaic' && index === 0} onOpen={onOpenMovie} key={item.id} />)}</div>{filteredMovies.length === 0 && <EmptyState text={search ? 'No films match your search.' : 'No films in the catalog yet.'} />}</section>
  }

  if (layout === 'smart') return <SmartLibrary title="Smart library" series={filteredSeries} movies={filteredMovies} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} />
  if (layout === 'streaming') return <StreamingBoard series={filteredSeries} movies={filteredMovies} continueWatching={continueWatching} incompleteSeries={incompleteSeries} spotlight={spotlight} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} onOpenSpotlight={onOpenSpotlight} />
  if (layout === 'backdrop') return <BackdropGallery spotlight={spotlight} spotlightIndex={spotlightIndex} onPrevious={showPreviousSpotlight} onNext={showNextSpotlight} onSelectSpotlight={setSpotlightIndex} series={filteredSeries} movies={filteredMovies} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} onOpenSpotlight={onOpenSpotlight} onRefreshSpotlight={onRefreshSpotlight} />
  if (layout === 'mosaic') return <MosaicGallery series={filteredSeries} movies={filteredMovies} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} />
  if (layout === 'editorial') return <EditorialMagazine spotlight={spotlight} spotlightIndex={spotlightIndex} onPrevious={showPreviousSpotlight} onNext={showNextSpotlight} onSelectSpotlight={setSpotlightIndex} series={filteredSeries} movies={filteredMovies} onOpenSeries={onOpenSeries} onOpenMovie={onOpenMovie} onOpenSpotlight={onOpenSpotlight} onRefreshSpotlight={onRefreshSpotlight} />

  return <div className="browse-home">
    <SpotlightHero items={spotlight} index={spotlightIndex} variant="cinematic" onPrevious={showPreviousSpotlight} onNext={showNextSpotlight} onSelect={setSpotlightIndex} onOpen={onOpenSpotlight} onRefresh={onRefreshSpotlight} />
    <SeriesRail title="Continue watching" items={continueWatching} layout="poster" onOpenSeries={onOpenSeries} />
    <SpotlightRail items={spotlight} onOpen={onOpenSpotlight} />
    <SeriesRail title="Keep exploring series" items={incompleteSeries} layout="poster" onOpenSeries={onOpenSeries} />
    <MovieRail title="Films" items={filteredMovies} layout="poster" onOpenMovie={onOpenMovie} />
    <SeriesRail title="All series" items={filteredSeries} layout="poster" onOpenSeries={onOpenSeries} />
  </div>
}

function SpotlightHero({ items, index, variant, onPrevious, onNext, onSelect, onOpen, onRefresh }: {
  items: SpotlightItem[]
  index: number
  variant: 'cinematic' | 'backdrop' | 'editorial'
  onPrevious: () => void
  onNext: () => void
  onSelect: (index: number) => void
  onOpen: (item: SpotlightItem) => void
  onRefresh: () => void
}) {
  const currentIndex = items.length ? index % items.length : 0
  const paginationStart = Math.max(0, Math.min(items.length - 7, currentIndex - 3))
  const paginationItems = items.slice(paginationStart, paginationStart + 7)
  const title = items.length ? items[currentIndex] : null
  if (!title) return <div className="feature-empty"><h1>Recent releases</h1><p>No releases were found from today back through the last 14 days. Refresh the release calendar to check again.</p><Button variant="outline" onClick={onRefresh}>Refresh releases</Button></div>

  return <section className={`feature-banner feature-banner--${variant}`} aria-roledescription="carousel" aria-label="New releases from today and the previous 14 days">
    {(title.background_url || title.poster_url) && <img className="feature-backdrop" src={title.background_url || title.poster_url || ''} alt="" onError={(event) => { event.currentTarget.hidden = true }} />}
    <div className="feature-copy">
      <Badge variant="outline">NEW IN YOUR LIBRARY · {title.kind === 'series' ? 'SERIES' : 'FILM'}</Badge>
      <h1>{title.title}</h1>
      <p>{title.kind === 'series'
        ? `New episode · S${String(title.season).padStart(2, '0')}E${String(title.episode).padStart(2, '0')}${title.episode_title ? ` · ${title.episode_title}` : ''}`
        : `Released ${new Date(`${title.release_at.slice(0, 10)}T00:00:00`).toLocaleDateString()}`}</p>
      <div className="feature-actions">
        <Button onClick={() => onOpen(title)}><Play data-icon="inline-start" size={16} fill="currentColor" /> Open {title.kind === 'series' ? 'series' : 'film'}</Button>
        {title.kind === 'series' && <Button variant="secondary" onClick={() => onOpen(title)}>S{String(title.season).padStart(2, '0')}E{String(title.episode).padStart(2, '0')} <ArrowRight data-icon="inline-end" size={16} /></Button>}
      </div>
    </div>
    {items.length > 1 && <div className="spotlight-controls" role="group" aria-label="New release pagination"><Button variant="ghost" size="icon" aria-label="Previous new release" onClick={onPrevious}><ArrowLeft /></Button><div className="spotlight-pagination">{paginationItems.map((item, offset) => {
      const slideIndex = paginationStart + offset
      return <Button key={`${item.kind}-${item.id}-${item.season ?? 0}`} variant="ghost" size="icon" aria-label={`Show release ${slideIndex + 1}: ${item.title}`} aria-current={slideIndex === currentIndex ? 'true' : undefined} onClick={() => onSelect(slideIndex)}><span className="spotlight-dot" /></Button>
    })}</div><span className="spotlight-count" aria-live="polite">{currentIndex + 1} / {items.length}</span><Button variant="ghost" size="icon" aria-label="Next new release" onClick={onNext}><ArrowRight /></Button></div>}
  </section>
}

const coverStyles = ['cover--ember', 'cover--violet', 'cover--ice', 'cover--moss', 'cover--rose']

function SeriesCover({ item, index, layout, featured = false, onOpen }: { item: SeriesSummary; index: number; layout: CardLayout; featured?: boolean; onOpen: (seriesId: number) => void }) {
  const progress = item.total ? Math.round(item.downloaded / item.total * 100) : 0
  const imageUrl = layout === 'backdrop' ? item.background_url || item.poster_url : item.poster_url
  return (
    <article className={`media-cover-wrap media-cover-wrap--${layout}${featured ? ' mosaic-tile--featured' : ''}`}>
      <Button className={`media-cover media-cover--${layout} ${coverStyles[index % coverStyles.length]}`} variant="ghost" onClick={() => onOpen(item.id)} aria-label={`Open ${item.title}`}>
        {imageUrl && <img className="cover-image" src={imageUrl} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
        <span className="cover-copy"><span className="cover-overline">SERIES <span>·</span> {item.seasons.length} {item.seasons.length === 1 ? 'season' : 'seasons'}</span>
          <span className="cover-title">{item.title}</span>
          <span className="cover-meta">{item.downloaded} / {item.total} episodes</span>
          <span className="cover-play"><Play size={14} fill="currentColor" /> Open series</span></span>
      </Button>
      {item.total > 0 && <Progress className="cover-progress" value={progress} aria-label={`${item.title} ${progress}% downloaded`} />}
      <span className="cover-caption">{item.title}</span>
    </article>
  )
}

function MovieCover({ item, index, layout, featured = false, onOpen }: { item: LibraryEntry; index: number; layout: CardLayout; featured?: boolean; onOpen: (movie: LibraryEntry) => void }) {
  const imageUrl = layout === 'backdrop' ? item.background_url || item.poster_url : item.poster_url
  return (
    <article className={`media-cover-wrap media-cover-wrap--${layout}${featured ? ' mosaic-tile--featured' : ''}`}>
      <Button className={`media-cover movie-cover media-cover--${layout} ${coverStyles[index % coverStyles.length]}`} variant="ghost" onClick={() => onOpen(item)} aria-label={`Open ${item.title}`}>
        {imageUrl && <img className="cover-image" src={imageUrl} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
        <span className="cover-copy"><span className="cover-overline">FILM</span>
          <span className="cover-title">{item.title}</span>
          <span className="cover-meta">{item.watched ? 'Watched' : item.downloaded ? 'In your library' : 'Not downloaded'}</span>
          <span className="cover-play"><Play size={14} fill="currentColor" /> Open film</span></span>
      </Button>
      <span className="cover-caption">{item.title}</span>
    </article>
  )
}

function SeriesRail({ title, items, layout, onOpenSeries }: { title: string; items: SeriesSummary[]; layout: CardLayout; onOpenSeries: (seriesId: number) => void }) {
  if (!items.length) return null
  return <MediaRail title={title} count={`${items.length} titles`} layout={layout}>{items.map((item, index) => <SeriesCover item={item} index={index} layout={layout} onOpen={onOpenSeries} key={item.id} />)}</MediaRail>
}

function MovieRail({ title, items, layout, onOpenMovie }: { title: string; items: LibraryEntry[]; layout: CardLayout; onOpenMovie: (movie: LibraryEntry) => void }) {
  if (!items.length) return null
  return <MediaRail title={title} count={`${items.length} titles`} layout={layout}>{items.map((item, index) => <MovieCover item={item} index={index} layout={layout} onOpen={onOpenMovie} key={item.id} />)}</MediaRail>
}

function SpotlightRail({ items, onOpen }: { items: SpotlightItem[]; onOpen: (item: SpotlightItem) => void }) {
  if (!items.length) return null
  return <MediaRail title="Recently released" count={`${items.length} from the last 14 days`} layout="poster">{items.map((item) => <article className="spotlight-cover-wrap" key={`${item.kind}-${item.id}-${item.season ?? 0}`}><Button className="spotlight-cover" variant="ghost" onClick={() => onOpen(item)} aria-label={`Open ${item.title}`}>
    {(item.poster_url || item.episode_image_url) && <img src={item.episode_image_url || item.poster_url || ''} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
    <span className="cover-overline">{item.kind === 'series' ? `S${String(item.season).padStart(2, '0')}E${String(item.episode).padStart(2, '0')}` : 'FILM'}</span><span className="cover-title">{item.title}</span><span className="cover-meta">{item.kind === 'series' ? item.episode_title || 'New episode' : new Date(`${item.release_at.slice(0, 10)}T00:00:00`).toLocaleDateString()}</span>
  </Button></article>)}</MediaRail>
}

function MediaRail({ title, count, layout, children }: { title: string; count: string; layout: CardLayout; children: ReactNode }) {
  const trackRef = useRef<HTMLDivElement>(null)
  const scroll = (direction: -1 | 1) => trackRef.current?.scrollBy({ left: direction * trackRef.current.clientWidth * 0.8, behavior: 'smooth' })
  return <section className="browse-rail"><div className="rail-heading"><div><h2>{title}</h2><span>{count}</span></div><div className="rail-controls"><Button variant="outline" size="icon" aria-label={`Scroll ${title} left`} onClick={() => scroll(-1)}><ArrowLeft /></Button><Button variant="outline" size="icon" aria-label={`Scroll ${title} right`} onClick={() => scroll(1)}><ArrowRight /></Button></div></div><div ref={trackRef} className={`rail-track rail-track--${layout}`} role="region" aria-label={title} tabIndex={0}>{children}</div></section>
}

function StreamingBoard({
  series,
  movies,
  continueWatching,
  incompleteSeries,
  spotlight,
  onOpenSeries,
  onOpenMovie,
  onOpenSpotlight,
}: {
  series: SeriesSummary[]
  movies: LibraryEntry[]
  continueWatching: SeriesSummary[]
  incompleteSeries: SeriesSummary[]
  spotlight: SpotlightItem[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onOpenSpotlight: (item: SpotlightItem) => void
}) {
  return <div className="streaming-board"><header className="board-heading"><p className="detail-kicker">YOUR COLLECTION</p><h1>Browse your library</h1><p>Jump back in, continue an unfinished season, or find something from your collection.</p></header><SeriesRail title="Continue watching" items={continueWatching} layout="backdrop" onOpenSeries={onOpenSeries} /><SpotlightRail items={spotlight} onOpen={onOpenSpotlight} /><SeriesRail title="Unfinished series" items={incompleteSeries} layout="editorial" onOpenSeries={onOpenSeries} /><MovieRail title="Films" items={movies} layout="mosaic" onOpenMovie={onOpenMovie} /><SeriesRail title="All series" items={series} layout="compact" onOpenSeries={onOpenSeries} /></div>
}

function BackdropGallery({
  spotlight,
  spotlightIndex,
  onPrevious,
  onNext,
  onSelectSpotlight,
  series,
  movies,
  onOpenSeries,
  onOpenMovie,
  onOpenSpotlight,
  onRefreshSpotlight,
}: {
  spotlight: SpotlightItem[]
  spotlightIndex: number
  onPrevious: () => void
  onNext: () => void
  onSelectSpotlight: (index: number) => void
  series: SeriesSummary[]
  movies: LibraryEntry[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onOpenSpotlight: (item: SpotlightItem) => void
  onRefreshSpotlight: () => void
}) {
  return <div className="backdrop-gallery"><SpotlightHero items={spotlight} index={spotlightIndex} variant="backdrop" onPrevious={onPrevious} onNext={onNext} onSelect={onSelectSpotlight} onOpen={onOpenSpotlight} onRefresh={onRefreshSpotlight} /><section className="backdrop-gallery-content"><PageHeading icon={<Film size={18} />} title="Your collection" count={series.length + movies.length} /><div className="backdrop-gallery-grid">{series.map((item, index) => <SeriesCover item={item} index={index} layout="backdrop" onOpen={onOpenSeries} key={`series-${item.id}`} />)}{movies.map((item, index) => <MovieCover item={item} index={series.length + index} layout="backdrop" onOpen={onOpenMovie} key={`movie-${item.id}`} />)}</div></section></div>
}

function MosaicGallery({ series, movies, onOpenSeries, onOpenMovie }: {
  series: SeriesSummary[]
  movies: LibraryEntry[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
}) {
  return <section className="mosaic-page"><header className="board-heading"><p className="detail-kicker">YOUR COLLECTION</p><h1>Library mosaic</h1><p>A visual wall of series and films, with larger tiles for the first titles.</p></header><div className="mosaic-wall">{series.map((item, index) => <SeriesCover item={item} index={index} layout="mosaic" featured={index % 9 === 0} onOpen={onOpenSeries} key={`series-${item.id}`} />)}{movies.map((item, index) => <MovieCover item={item} index={series.length + index} layout="mosaic" featured={(series.length + index) % 9 === 0} onOpen={onOpenMovie} key={`movie-${item.id}`} />)}</div></section>
}

function EditorialMagazine({ spotlight, spotlightIndex, onPrevious, onNext, onSelectSpotlight, series, movies, onOpenSeries, onOpenMovie, onOpenSpotlight, onRefreshSpotlight }: {
  spotlight: SpotlightItem[]
  spotlightIndex: number
  onPrevious: () => void
  onNext: () => void
  onSelectSpotlight: (index: number) => void
  series: SeriesSummary[]
  movies: LibraryEntry[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onOpenSpotlight: (item: SpotlightItem) => void
  onRefreshSpotlight: () => void
}) {
  return <div className="editorial-magazine"><div className="editorial-title"><div><p className="detail-kicker">THE LOCAL EDITION</p><h1>Stories in your library</h1><p>New releases, unfinished seasons, and films already on disk.</p></div><Badge variant="outline">{series.length + movies.length} titles</Badge></div><SpotlightHero items={spotlight} index={spotlightIndex} variant="editorial" onPrevious={onPrevious} onNext={onNext} onSelect={onSelectSpotlight} onOpen={onOpenSpotlight} onRefresh={onRefreshSpotlight} /><section className="editorial-list"><h2>Series</h2>{series.map((item, index) => <SeriesCover item={item} index={index} layout="editorial" onOpen={onOpenSeries} key={item.id} />)}{movies.length > 0 && <h2>Films</h2>}{movies.map((item, index) => <MovieCover item={item} index={index} layout="editorial" onOpen={onOpenMovie} key={item.id} />)}</section></div>
}

function SmartLibrary({ title, series, movies, onOpenSeries, onOpenMovie }: {
  title: string
  series: SeriesSummary[]
  movies: LibraryEntry[]
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
}) {
  const [sortByMissing, setSortByMissing] = useState(true)
  const rows = [
    ...series.map((item) => ({ key: `series-${item.id}`, title: item.title, type: `${item.seasons.length} seasons`, downloaded: item.downloaded, total: item.total, missing: item.missing, onOpen: () => onOpenSeries(item.id) })),
    ...movies.map((item) => ({ key: `movie-${item.id}`, title: item.title, type: 'Film', downloaded: item.downloaded, total: item.total, missing: item.missing, onOpen: () => onOpenMovie(item) })),
  ].sort((left, right) => sortByMissing ? right.missing - left.missing || left.title.localeCompare(right.title) : left.title.localeCompare(right.title))
  return <section className="smart-library"><header className="board-heading"><p className="detail-kicker">FIND AND MANAGE</p><h1>{title}</h1><p>Dense, sortable rows for quickly scanning a large library.</p></header><div className="smart-table-wrap"><Table><TableHeader><TableRow><TableHead>Title</TableHead><TableHead>Type</TableHead><TableHead>Downloaded</TableHead><TableHead aria-sort={sortByMissing ? 'descending' : 'ascending'}><Button variant="ghost" size="sm" onClick={() => setSortByMissing((value) => !value)}>Missing <ArrowUpDown size={13} /></Button></TableHead><TableHead>Open</TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.key}><TableCell className="smart-title">{row.title}</TableCell><TableCell>{row.type}</TableCell><TableCell className="numeric">{row.downloaded} / {row.total}</TableCell><TableCell className="numeric">{row.missing}</TableCell><TableCell><Button variant="ghost" size="sm" onClick={row.onOpen}>Details <ArrowRight data-icon="inline-end" size={14} /></Button></TableCell></TableRow>)}</TableBody></Table>{rows.length === 0 && <EmptyState text="No titles match the current library." />}</div></section>
}

function PageHeading({ icon, title, count }: { icon: ReactNode; title: string; count: number }) {
  return <header className="browse-heading"><span className="browse-heading-icon">{icon}</span><h1>{title}</h1><Badge variant="secondary">{count}</Badge></header>
}

function EmptyState({ text }: { text: string }) {
  return <div className="browse-empty"><div className="empty-glyph"><Tv size={21} /></div><h2>Nothing here yet</h2><p>{text}</p></div>
}
