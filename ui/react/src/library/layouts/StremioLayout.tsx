import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { LayoutProps } from './shared'
import { EmptyLibrary, FeaturedHero, LayoutHeading, LibraryGrid, MediaRail, MovieCard, SeriesCard } from './shared'

export function StremioLayout({
  title,
  description,
  series,
  movies,
  recent,
  featured,
  featuredItems,
  featuredIndex,
  onPreviousFeatured,
  onNextFeatured,
  onSelectFeatured,
  onOpenSeries,
  onOpenMovie,
  onRefreshSpotlight,
}: LayoutProps) {
  const continueWatching = series.filter((item) => item.unwatchedDownloaded > 0)
  const count = series.length + movies.length

  return <main className="platform-layout platform-layout--stremio">
    <LayoutHeading title={title} detail={description} count={count} />
    {featured && <FeaturedHero item={featured} items={featuredItems} index={featuredIndex} variant="stremio" onPrevious={onPreviousFeatured} onNext={onNextFeatured} onSelect={onSelectFeatured} />}
    {recent.length === 0 && <div className="stremio-refresh-row"><span>Check the release calendar for recent titles.</span><Button variant="outline" size="sm" onClick={onRefreshSpotlight}><RotateCcw data-icon="inline-start" size={14} /> Refresh releases</Button></div>}
    {continueWatching.length > 0 && <MediaRail title="Continue watching" detail="Pick up with an unwatched downloaded episode.">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
    {count > 0 ? <LibraryGrid className="stremio-library-grid">
      {series.map((item) => <SeriesCard key={`series-${item.id}`} item={item} style="poster" onOpen={() => onOpenSeries(item.id)} />)}
      {movies.map((item) => <MovieCard key={`movie-${item.id}`} item={item} style="poster" onOpen={() => onOpenMovie(item)} />)}
    </LibraryGrid> : <EmptyLibrary text="Add series or films to your local library to see them here." />}
  </main>
}
