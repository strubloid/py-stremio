import { useState } from 'react'
import { ArrowDownWideNarrow, ArrowUpAZ, LayoutGrid, Rows3 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { LayoutProps } from './shared'
import { EmptyLibrary, LayoutHeading, MediaRail, MovieCard, SeriesCard } from './shared'

export function PlexLayout({ title, description, series, movies, onOpenSeries, onOpenMovie }: LayoutProps) {
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [sort, setSort] = useState<'title' | 'missing'>('title')
  const continueWatching = series.filter((item) => item.unwatchedDownloaded > 0)
  const orderedSeries = [...series].sort((left, right) => sort === 'missing'
    ? right.missing - left.missing || left.title.localeCompare(right.title)
    : left.title.localeCompare(right.title))
  const orderedMovies = [...movies].sort((left, right) => sort === 'missing'
    ? right.missing - left.missing || left.title.localeCompare(right.title)
    : left.title.localeCompare(right.title))
  const count = series.length + movies.length
  const style = view === 'grid' ? 'poster' : 'list'

  return <main className="platform-layout platform-layout--plex">
    <div className="plex-library-header"><LayoutHeading title={title} detail={description} count={count} /><div className="plex-library-tools">
      <div className="plex-sort-controls" role="group" aria-label="Sort library"><Button variant={sort === 'title' ? 'secondary' : 'ghost'} size="sm" aria-pressed={sort === 'title'} onClick={() => setSort('title')}><ArrowUpAZ data-icon="inline-start" size={15} />Title</Button><Button variant={sort === 'missing' ? 'secondary' : 'ghost'} size="sm" aria-pressed={sort === 'missing'} onClick={() => setSort('missing')}><ArrowDownWideNarrow data-icon="inline-start" size={15} />Missing</Button></div>
      <ToggleGroup multiple={false} value={[view]} onValueChange={(values) => { const value = values[0]; if (value === 'grid' || value === 'list') setView(value) }} variant="outline" aria-label="Library view"><ToggleGroupItem value="grid" aria-label="Grid view"><LayoutGrid size={15} /></ToggleGroupItem><ToggleGroupItem value="list" aria-label="List view"><Rows3 size={15} /></ToggleGroupItem></ToggleGroup>
    </div></div>
    {continueWatching.length > 0 && <MediaRail title="Continue Watching" detail="Downloaded episodes you have not marked watched.">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
    <section className={`plex-library-content plex-library-content--${view}`} aria-label="Library titles">
      {series.length > 0 && <div className="plex-library-group"><div className="plex-group-heading"><h2>Series</h2><Badge variant="outline">{series.length}</Badge></div><div className="plex-title-grid">{orderedSeries.map((item) => <SeriesCard key={item.id} item={item} style={style} onOpen={() => onOpenSeries(item.id)} />)}</div></div>}
      {movies.length > 0 && <div className="plex-library-group"><div className="plex-group-heading"><h2>Films</h2><Badge variant="outline">{movies.length}</Badge></div><div className="plex-title-grid">{orderedMovies.map((item) => <MovieCard key={item.id} item={item} style={style} onOpen={() => onOpenMovie(item)} />)}</div></div>}
      {count === 0 && <EmptyLibrary text="Your personal library is empty. Add titles to start organising them here." />}
    </section>
  </main>
}
