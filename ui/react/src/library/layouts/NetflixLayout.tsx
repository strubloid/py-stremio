import type { LayoutProps } from './shared'
import { EmptyLibrary, FeaturedCard, FeaturedHero, LayoutHeading, MediaRail, MovieCard, SeriesCard } from './shared'

export function NetflixLayout({
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
  return <main className="platform-layout platform-layout--netflix">
    {featured && <FeaturedHero item={featured} items={featuredItems} index={featuredIndex} variant="netflix" onPrevious={onPreviousFeatured} onNext={onNextFeatured} onSelect={onSelectFeatured} />}
    <div className="netflix-content"><LayoutHeading title={title} detail={description} count={count} />
      {continueWatching.length > 0 && <MediaRail title="Continue Watching">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="landscape" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {recent.length > 0 && <MediaRail title="Recently Added" detail="Recent episodes and films from your calendar.">{recent.map((item) => <FeaturedCard key={item.key} item={item} style="poster" />)}</MediaRail>}
      {series.length > 0 && <MediaRail title={title === 'Series' ? 'All Series' : 'Series'}>{series.map((item) => <SeriesCard key={item.id} item={item} style="poster" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {movies.length > 0 && <MediaRail title={title === 'Films' ? 'All Films' : 'Films'}>{movies.map((item) => <MovieCard key={item.id} item={item} style="poster" onOpen={() => onOpenMovie(item)} />)}</MediaRail>}
      {count === 0 && <EmptyLibrary text="Your library is ready for series and films." />}
    </div>
  </main>
}
