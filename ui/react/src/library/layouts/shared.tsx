import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { ArrowLeft, ArrowRight, Film, Play } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import type { LibraryEntry, SeriesSummary, Section } from '../types'

export type BrowseSection = Extract<Section, 'home' | 'series' | 'movies'>
export type CardStyle = 'poster' | 'landscape' | 'compact' | 'collection' | 'list'

export type FeaturedTitle = {
  key: string
  kind: 'series' | 'movie'
  title: string
  posterUrl: string | null
  backdropUrl: string | null
  detail: string
  label: string
  onOpen: () => void
}

export type LayoutProps = {
  section: BrowseSection
  title: string
  description: string
  series: SeriesSummary[]
  movies: LibraryEntry[]
  recent: FeaturedTitle[]
  featured: FeaturedTitle | null
  featuredItems: FeaturedTitle[]
  featuredIndex: number
  onPreviousFeatured: () => void
  onNextFeatured: () => void
  onSelectFeatured: (index: number) => void
  onOpenSeries: (seriesId: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onRefreshSpotlight: () => void
}

type CardProps = {
  title: string
  style: CardStyle
  eyebrow: string
  detail: string
  posterUrl?: string | null
  backdropUrl?: string | null
  progress?: number
  onOpen: () => void
}

export function SeriesCard({ item, style = 'poster', onOpen }: {
  item: SeriesSummary
  style?: CardStyle
  onOpen: () => void
}) {
  const progress = item.total ? Math.round(item.downloaded / item.total * 100) : 0
  return <MediaCard
    title={item.title}
    style={style}
    eyebrow={`${item.seasons.length} ${item.seasons.length === 1 ? 'season' : 'seasons'}`}
    detail={`${item.downloaded} of ${item.total} episodes · ${item.missing} missing`}
    posterUrl={item.poster_url}
    backdropUrl={item.background_url}
    progress={progress}
    onOpen={onOpen}
  />
}

export function MovieCard({ item, style = 'poster', onOpen }: {
  item: LibraryEntry
  style?: CardStyle
  onOpen: () => void
}) {
  return <MediaCard
    title={item.title}
    style={style}
    eyebrow={item.release_date?.slice(0, 4) || 'FILM'}
    detail={item.watched ? 'Watched' : item.downloaded ? 'Available to watch' : 'Not downloaded'}
    posterUrl={item.poster_url}
    backdropUrl={item.background_url}
    progress={item.downloaded ? 100 : 0}
    onOpen={onOpen}
  />
}

function MediaCard({ title, style, eyebrow, detail, posterUrl, backdropUrl, progress, onOpen }: CardProps) {
  const source = style === 'landscape' || style === 'collection' ? backdropUrl || posterUrl : posterUrl || backdropUrl
  return <article className={`media-card-wrap media-card-wrap--${style}`}>
    <Button className={`media-card media-card--${style}`} variant="ghost" aria-label={`Open ${title}`} onClick={onOpen}>
      <span className="media-card-art">
        <MediaArtwork key={source || title} src={source} title={title} />
        <span className="media-card-shade" />
        <span className="media-card-eyebrow">{eyebrow}</span>
        <span className="media-card-copy"><span className="media-card-title">{title}</span><span className="media-card-detail">{detail}</span></span>
        <span className="media-card-action"><Play size={13} fill="currentColor" /> Open title</span>
      </span>
    </Button>
    {progress !== undefined && <Progress className="media-card-progress" value={progress} aria-label={`${title} ${progress}% downloaded`} />}
    <span className="media-card-caption">{title}</span>
  </article>
}

export function FeaturedCard({ item, style = 'poster' }: { item: FeaturedTitle; style?: CardStyle }) {
  return <MediaCard title={item.title} style={style} eyebrow={item.label} detail={item.detail} posterUrl={item.posterUrl} backdropUrl={item.backdropUrl} onOpen={item.onOpen} />
}

function MediaArtwork({ src, title }: { src?: string | null; title: string }) {
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(!src)
  return <>
    {src && !loaded && !failed && <Skeleton className="media-art-skeleton" aria-hidden="true" />}
    {src && !failed && <img className={`media-art-image${loaded ? ' media-art-image--loaded' : ''}`} src={src} alt="" loading="lazy" onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />}
    {failed && <span className="media-art-fallback" aria-hidden="true">{title.slice(0, 1).toUpperCase()}<small>Artwork unavailable</small></span>}
  </>
}

export function FeaturedHero({ item, items, index, variant, onPrevious, onNext, onSelect }: {
  item: FeaturedTitle
  items: FeaturedTitle[]
  index: number
  variant: 'stremio' | 'netflix' | 'apple-tv' | 'disney-plus' | 'prime-video'
  onPrevious: () => void
  onNext: () => void
  onSelect: (index: number) => void
}) {
  const current = items.length ? items[index % items.length] : item
  const paginationStart = Math.max(0, Math.min(items.length - 7, index % Math.max(1, items.length) - 3))
  const paginationItems = items.slice(paginationStart, paginationStart + 7)
  const backdrop = current.backdropUrl || current.posterUrl
  return <section className={`platform-hero platform-hero--${variant}`} aria-roledescription="carousel" aria-label="Featured library titles">
    {backdrop && <MediaArtwork key={backdrop} src={backdrop} title={current.title} />}
    <span className="platform-hero-shade" />
    <div className="platform-hero-copy">
      <Badge variant="outline">{current.kind === 'series' ? 'SERIES' : 'FILM'}</Badge>
      <h2>{current.title}</h2>
      <p>{current.detail}</p>
      <div className="platform-hero-actions"><Button onClick={current.onOpen}><Play data-icon="inline-start" size={16} fill="currentColor" /> Open {current.kind}</Button><Button variant="secondary" onClick={current.onOpen}>Details</Button></div>
    </div>
    {items.length > 1 && <div className="platform-hero-pagination" role="group" aria-label="Featured titles">
      <Button variant="ghost" size="icon" aria-label="Previous featured title" onClick={onPrevious}><ArrowLeft /></Button>
      <div className="platform-hero-dots">{paginationItems.map((entry, offset) => {
        const slideIndex = paginationStart + offset
        return <Button key={entry.key} variant="ghost" size="icon" aria-label={`Show featured title ${slideIndex + 1}: ${entry.title}`} aria-current={slideIndex === index % items.length ? 'true' : undefined} onClick={() => onSelect(slideIndex)}><span /></Button>
      })}</div>
      <span aria-live="polite">{index % items.length + 1} / {items.length}</span>
      <Button variant="ghost" size="icon" aria-label="Next featured title" onClick={onNext}><ArrowRight /></Button>
    </div>}
  </section>
}

export function MediaRail({ title, detail, children, className = '' }: { title: string; detail?: string; children: ReactNode; className?: string }) {
  const trackRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startScrollLeft: number; moved: boolean } | null>(null)
  const suppressClickRef = useRef(false)
  const [dragging, setDragging] = useState(false)

  const scroll = (direction: -1 | 1) => {
    const track = trackRef.current
    if (track) track.scrollBy({ left: direction * track.clientWidth * 0.82, behavior: 'smooth' })
  }
  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startScrollLeft: event.currentTarget.scrollLeft, moved: false }
  }
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const distance = event.clientX - drag.startX
    if (Math.abs(distance) > 5) {
      if (!drag.moved) event.currentTarget.setPointerCapture(event.pointerId)
      drag.moved = true
      setDragging(true)
      event.currentTarget.scrollLeft = drag.startScrollLeft - distance
    }
  }
  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    suppressClickRef.current = drag.moved
    dragRef.current = null
    setDragging(false)
    window.setTimeout(() => { suppressClickRef.current = false }, 0)
  }
  const handleClickCapture = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!suppressClickRef.current) return
    event.preventDefault()
    event.stopPropagation()
    suppressClickRef.current = false
  }
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return
    if (event.key === 'ArrowRight') { event.preventDefault(); scroll(1) }
    if (event.key === 'ArrowLeft') { event.preventDefault(); scroll(-1) }
  }

  return <section className={`media-rail ${className}`}>
    <header className="media-rail-heading"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div><div className="media-rail-controls"><Button variant="outline" size="icon" aria-label={`Scroll ${title} left`} onClick={() => scroll(-1)}><ArrowLeft /></Button><Button variant="outline" size="icon" aria-label={`Scroll ${title} right`} onClick={() => scroll(1)}><ArrowRight /></Button></div></header>
    <div ref={trackRef} className={`media-rail-track${dragging ? ' media-rail-track--dragging' : ''}`} role="region" aria-label={title} tabIndex={0} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onClickCapture={handleClickCapture} onKeyDown={handleKeyDown}>{children}</div>
  </section>
}

export function LayoutHeading({ title, detail, count }: { title: string; detail: string; count: number }) {
  return <header className="platform-heading"><div><h1>{title}</h1><p>{detail}</p></div><Badge variant="outline">{count} {count === 1 ? 'title' : 'titles'}</Badge></header>
}

export function LibraryGrid({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`platform-library-grid ${className}`}>{children}</div>
}

export function EmptyLibrary({ text }: { text: string }) {
  return <div className="platform-empty"><Film size={23} /><p>{text}</p></div>
}
