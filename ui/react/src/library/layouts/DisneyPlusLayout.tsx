import type { LayoutProps } from './shared'
import { EmptyLibrary, FeaturedCard, FeaturedHero, LayoutHeading, LibraryGrid, MediaRail, MovieCard, SeriesCard } from './shared'

export function DisneyPlusLayout({
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
  return <main className="platform-layout platform-layout--disney-plus">
    {featured && <FeaturedHero item={featured} items={featuredItems} index={featuredIndex} variant="disney-plus" onPrevious={onPreviousFeatured} onNext={onNextFeatured} onSelect={onSelectFeatured} />}
    <div className="disney-library">
      <LayoutHeading title={title} detail={description} count={count} />
      {continueWatching.length > 0 && <MediaRail title="Continue Watching" className="disney-large-rail">{continueWatching.map((item) => <SeriesCard key={item.id} item={item} style="collection" onOpen={() => onOpenSeries(item.id)} />)}</MediaRail>}
      {recent.length > 0 && <MediaRail title="Recently Added" className="disney-large-rail">{recent.map((item) => <FeaturedCard key={item.key} item={item} style="collection" />)}</MediaRail>}
      {count > 0 ? <LibraryGrid className="disney-collection-grid">
        {series.map((item) => <SeriesCard key={item.id} item={item} style="collection" onOpen={() => onOpenSeries(item.id)} />)}
        {movies.map((item) => <MovieCard key={item.id} item={item} style="collection" onOpen={() => onOpenMovie(item)} />)}
      </LibraryGrid> : <EmptyLibrary text="Your collection will appear here when you add films or series." />}
    </div>
  </main>
}
