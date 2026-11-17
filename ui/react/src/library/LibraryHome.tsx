import { useState } from 'react'
import { AppleTVLayout } from './layouts/AppleTVLayout'
import { DisneyPlusLayout } from './layouts/DisneyPlusLayout'
import { NetflixLayout } from './layouts/NetflixLayout'
import { PlexLayout } from './layouts/PlexLayout'
import { PrimeVideoLayout } from './layouts/PrimeVideoLayout'
import { StremioLayout } from './layouts/StremioLayout'
import type { FeaturedTitle, LayoutProps } from './layouts/shared'
import type { LibraryEntry, Section, SeriesSummary, LibraryLayout, SpotlightItem } from './types'

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

export function LibraryHome({ section, series, movies, spotlight, search, layout, onOpenSeries, onOpenMovie, onOpenSpotlight, onRefreshSpotlight }: Props) {
  const [featuredIndex, setFeaturedIndex] = useState(0)
  const query = search.trim().toLocaleLowerCase()
  const inSection = (kind: 'series' | 'movie') => section === 'home' || (section === 'series' && kind === 'series') || (section === 'movies' && kind === 'movie')
  const visibleSeries = inSection('series') ? series.filter((item) => item.title.toLocaleLowerCase().includes(query)) : []
  const visibleMovies = inSection('movie') ? movies.filter((item) => item.title.toLocaleLowerCase().includes(query)) : []
  const recent = spotlight.filter((item) => inSection(item.kind) && item.title.toLocaleLowerCase().includes(query))
  const featuredItems: FeaturedTitle[] = recent.map((item) => ({
    key: `${item.kind}-${item.id}-${item.season ?? 0}`,
    kind: item.kind,
    title: item.title,
    posterUrl: item.episode_image_url || item.poster_url || null,
    backdropUrl: item.background_url || item.poster_url || item.episode_image_url || null,
    label: item.kind === 'series' ? 'NEW EPISODE' : 'RECENTLY RELEASED',
    detail: item.kind === 'series'
      ? `S${String(item.season).padStart(2, '0')}E${String(item.episode).padStart(2, '0')}${item.episode_title ? ` · ${item.episode_title}` : ''}`
      : `Released ${new Date(`${item.release_at.slice(0, 10)}T00:00:00`).toLocaleDateString()}`,
    onOpen: () => onOpenSpotlight(item),
  }))
  if (featuredItems.length === 0) {
    const fallbackSeries = visibleSeries[0]
    const fallbackMovie = visibleMovies[0]
    if (fallbackSeries) featuredItems.push({
      key: `series-${fallbackSeries.id}`,
      kind: 'series',
      title: fallbackSeries.title,
      posterUrl: fallbackSeries.poster_url || null,
      backdropUrl: fallbackSeries.background_url || fallbackSeries.poster_url || null,
      label: 'IN YOUR LIBRARY',
      detail: `${fallbackSeries.seasons.length} ${fallbackSeries.seasons.length === 1 ? 'season' : 'seasons'} · ${fallbackSeries.missing} episodes missing`,
      onOpen: () => onOpenSeries(fallbackSeries.id),
    })
    else if (fallbackMovie) featuredItems.push({
      key: `movie-${fallbackMovie.id}`,
      kind: 'movie',
      title: fallbackMovie.title,
      posterUrl: fallbackMovie.poster_url || null,
      backdropUrl: fallbackMovie.background_url || fallbackMovie.poster_url || null,
      label: 'IN YOUR LIBRARY',
      detail: fallbackMovie.watched ? 'Watched' : fallbackMovie.downloaded ? 'Available to watch' : 'Not downloaded',
      onOpen: () => onOpenMovie(fallbackMovie),
    })
  }
  const activeFeaturedIndex = featuredItems.length ? featuredIndex % featuredItems.length : 0
  const featured = featuredItems[activeFeaturedIndex] ?? null
  const moveFeatured = (direction: -1 | 1) => setFeaturedIndex((index) => featuredItems.length
    ? (index + direction + featuredItems.length) % featuredItems.length
    : 0)

  const props: LayoutProps = {
    section: section === 'series' || section === 'movies' ? section : 'home',
    title: section === 'series' ? 'Series' : section === 'movies' ? 'Films' : 'Your library',
    description: section === 'series' ? 'Browse the series in your local library.' : section === 'movies' ? 'Browse the films stored in your local library.' : 'Your series and films, ready when you are.',
    series: visibleSeries,
    movies: visibleMovies,
    recent: featuredItems.length > 0 && recent.length > 0 ? featuredItems : [],
    featured,
    featuredItems,
    featuredIndex: activeFeaturedIndex,
    onPreviousFeatured: () => moveFeatured(-1),
    onNextFeatured: () => moveFeatured(1),
    onSelectFeatured: (index) => setFeaturedIndex(index),
    onOpenSeries,
    onOpenMovie,
    onRefreshSpotlight,
  }

  if (layout === 'netflix') return <NetflixLayout {...props} />
  if (layout === 'apple-tv') return <AppleTVLayout {...props} />
  if (layout === 'plex') return <PlexLayout {...props} />
  if (layout === 'disney-plus') return <DisneyPlusLayout {...props} />
  if (layout === 'prime-video') return <PrimeVideoLayout {...props} />
  return <StremioLayout {...props} />
}
