import { Badge } from '@/components/ui/badge'
import type { LayoutProps } from './shared'
import { EmptyLibrary, FeaturedCard, FeaturedHero, LayoutHeading, MediaRail, MovieCard, SeriesCard } from './shared'

export function PrimeVideoLayout({
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
}: LayoutProps) {
  const continueWatching = series.filter((item) => item.unwatchedDownloaded > 0)
  const count = series.length + movies.length
  return <main className="platform-layout platform-layout--prime-video">
    <div className="prime-discovery-top">
      {featured && <FeaturedHero item={featured} items={featuredItems} index={featuredIndex} variant="prime-video" onPrevious={onPreviousFeatured} onNext={onNextFeatured} onSelect={onSelectFeatured} />}
      <aside className="prime-quick-list"><div className="prime-quick-heading"><div><h2>In your library</h2><p>Recently released titles</p></div><Badge variant="outline">{recent.length}</Badge></div>
        {recent.slice(0, 4).map((item) => <FeaturedCard key={item.key} item={item} style="compact" />)}
        {recent.length === 0 && <p className="prime-quick-empty">Your recent releases will appear here when available.</p>}
      </aside>
    </div>
    <section className="prime-discovery-content">
      <LayoutHeading title={title} detail={description} count={count} />
      {continueWatching.length > 0 && <MediaRail title="Continue Watching" detail="Downloaded episodes ready to pick up.">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {recent.length > 0 && <MediaRail title="Recently Released">{recent.map((item) => <FeaturedCard key={item.key} item={item} style="poster" />)}</MediaRail>}
      {series.length > 0 && <MediaRail title="Your Series">{series.map((item) => <SeriesCard key={item.id} item={item} style="poster" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {movies.length > 0 && <MediaRail title="Your Films">{movies.map((item) => <MovieCard key={item.id} item={item} style="poster" onOpen={() => onOpenMovie(item)} />)}</MediaRail>}
      {count === 0 && <EmptyLibrary text="Add titles to your local library to start browsing." />}
    </section>
  </main>
}
