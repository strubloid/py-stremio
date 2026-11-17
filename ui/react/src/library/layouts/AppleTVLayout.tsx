import type { LayoutProps } from './shared'
import { EmptyLibrary, FeaturedHero, LayoutHeading, MediaRail, MovieCard, SeriesCard } from './shared'

export function AppleTVLayout({
  title,
  description,
  series,
  movies,
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
  return <main className="platform-layout platform-layout--apple-tv">
    {featured && <FeaturedHero item={featured} items={featuredItems} index={featuredIndex} variant="apple-tv" onPrevious={onPreviousFeatured} onNext={onNextFeatured} onSelect={onSelectFeatured} />}
    <section className="apple-library">
      <LayoutHeading title={title} detail={description} count={count} />
      {continueWatching.length > 0 && <MediaRail title="Up Next" detail="Unwatched episodes already in your library.">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {series.length > 0 && <MediaRail title="Series" className="apple-wide-rail">{series.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {movies.length > 0 && <MediaRail title="Films" className="apple-wide-rail">{movies.map((item) => <MovieCard key={item.id} item={item} style="landscape" onOpen={() => onOpenMovie(item)} />)}</MediaRail>}
      {count === 0 && <EmptyLibrary text="Your library will appear here when you add films or series." />}
    </section>
  </main>
}
