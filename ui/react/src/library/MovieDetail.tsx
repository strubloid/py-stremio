import { ArrowLeft, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { EpisodeHistory, LibraryEntry } from './types'

type Props = {
  movie: LibraryEntry
  history: EpisodeHistory | null
  loading: boolean
  busy: boolean
  onBack: () => void
  onSetWatched: (watched: boolean) => void
  onRedownload: () => void
}

export function MovieDetail({ movie, history, loading, busy, onBack, onSetWatched, onRedownload }: Props) {
  const file = history?.files.find((item) => !item.is_part)
  const attempt = history?.attempts.find((item) => item.success === 1)
  const watched = movie.watched ?? history?.watched_episodes.includes(0) ?? false

  return (
    <div className="detail-page movie-detail">
      <Button className="back-link" variant="ghost" onClick={onBack}><ArrowLeft data-icon="inline-start" size={16} /> Back to films</Button>
      <section className="detail-hero">
        <div className="detail-hero-art detail-hero-art--film" aria-hidden="true">{movie.poster_url ? <img src={movie.poster_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} /> : <span>{movie.title.slice(0, 1).toUpperCase()}</span>}</div>
        <div className="detail-hero-copy">
          <p className="detail-kicker">FILM <span>·</span> LOCAL LIBRARY</p>
          <h1>{movie.title}</h1>
          <p className="detail-stats">{file ? 'Available to watch' : 'Not downloaded yet'}{watched ? ' · Watched' : ''}</p>
          <div className="detail-actions">
            <Button variant="outline" onClick={() => onSetWatched(!watched)}>{watched ? <EyeOff data-icon="inline-start" size={16} /> : <Eye data-icon="inline-start" size={16} />}{watched ? 'Mark unwatched' : 'Mark watched'}</Button>
            <Button onClick={onRedownload} disabled={busy}><RotateCcw data-icon="inline-start" size={16} />{busy ? 'Queued…' : file ? 'Re-download' : 'Download'}</Button>
          </div>
        </div>
      </section>
      <section className="film-file-section">
        <div className="section-title-line"><div><h2>Files</h2><p>Media stored in this movie folder</p></div><Badge variant={file ? 'outline' : 'secondary'}>{file ? 'Downloaded' : 'Missing'}</Badge></div>
        {loading ? <div className="episode-list-loading"><span /><span /></div> : file ? <article className="movie-file-row">
          <div><strong>{file.rel_path}</strong><small>{file.size ? `${(file.size / 1_000_000_000).toFixed(2)} GB` : 'File present'}{attempt?.completed_at && ` · Downloaded ${new Date(attempt.completed_at).toLocaleDateString()}`}{attempt?.server_url && ` · ${attempt.server_url}`}</small></div>
          {watched && <Badge variant="outline">Watched</Badge>}
        </article> : <p className="missing-file-note">No completed video file is recorded for this title.</p>}
      </section>
    </div>
  )
}
