import { ArrowLeft, Eye, EyeOff, Film, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
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
  const files = history?.files.filter((item) => !item.is_part) ?? []
  const file = files[0]
  const attempt = history?.attempts.find((item) => item.success === 1)
  const watched = movie.watched ?? history?.watched_episodes.includes(0) ?? false
  const progress = movie.downloaded ? 100 : 0

  return (
    <div className="series-screen movie-screen">
      {(movie.background_url || movie.poster_url) && <img className="series-backdrop" src={movie.background_url || movie.poster_url || ''} alt="" onError={(event) => { event.currentTarget.hidden = true }} />}
      <div className="series-screen-shade" />
      <div className="series-screen-layout movie-screen-layout">
        <section className="series-story movie-story">
          <Button className="back-link" variant="ghost" onClick={onBack}><ArrowLeft data-icon="inline-start" size={16} /> Back to films</Button>
          <div className="series-story-copy movie-story-copy">
            <p className="detail-kicker">FILM <span>·</span> LOCAL LIBRARY</p>
            <h1>{movie.title}</h1>
            <p className="detail-stats">{file ? 'Available to watch' : 'Not downloaded yet'}{movie.release_date ? ` · ${movie.release_date.slice(0, 4)}` : ''}{watched ? ' · Watched' : ''}</p>
            <Progress className="series-progress" value={progress} aria-label={`${movie.title} ${progress}% downloaded`} />
          </div>

          <section className="selected-episode-card movie-selected-file" aria-live="polite">
            <div className="selected-episode-art movie-file-art">
              {movie.poster_url ? <img src={movie.poster_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} /> : <Film size={26} />}
              <span className="movie-file-kind">FILM</span>
            </div>
            <div className="selected-episode-copy">
              <p className="detail-kicker">MOVIE FILE</p>
              <h2>{file ? 'Stored in your library' : 'No downloaded file'}</h2>
              <Badge variant={file ? 'outline' : 'secondary'}>{file ? 'Downloaded' : 'Missing'}</Badge>
              {file && <>
                <p className="episode-file-name">{file.rel_path}</p>
                <small>{file.size ? `${(file.size / 1_000_000_000).toFixed(2)} GB` : 'File present'}{attempt?.completed_at && ` · Downloaded ${new Date(attempt.completed_at).toLocaleDateString()}`}</small>
                {attempt?.server_url && <small>Source · {attempt.server_url}</small>}
              </>}
              {!loading && !file && <p className="episode-file-name">No completed video file is recorded for this title.</p>}
              <div className="selected-episode-actions">
                <Button variant="outline" size="sm" onClick={() => onSetWatched(!watched)}>{watched ? <EyeOff data-icon="inline-start" size={14} /> : <Eye data-icon="inline-start" size={14} />}{watched ? 'Mark unwatched' : 'Mark watched'}</Button>
                <Button size="sm" onClick={onRedownload} disabled={busy}><RotateCcw data-icon="inline-start" size={14} />{busy ? 'Queued…' : file ? 'Re-download' : 'Download'}</Button>
              </div>
            </div>
          </section>
        </section>

        <aside className="series-episode-browser movie-file-browser" aria-label="Movie files">
          <div className="browser-topline"><span>FILES</span><Badge variant="outline">{files.length} {files.length === 1 ? 'file' : 'files'}</Badge></div>
          <p className="movie-browser-intro">Media stored in this movie folder</p>
          <div className="movie-browser-list">
            {loading ? <div className="episode-list-loading"><span /><span /><span /></div> : files.length > 0 ? files.map((item) => <article className="movie-browser-file" key={item.rel_path}>
              <span className="episode-state episode-state--downloaded" />
              <div><strong title={item.rel_path}>{item.rel_path}</strong><small>{item.size ? `${(item.size / 1_000_000_000).toFixed(2)} GB` : 'File present'}</small></div>
              <Badge variant="outline">Downloaded</Badge>
            </article>) : <p className="browser-empty">No movie files are recorded yet.</p>}
          </div>
        </aside>
      </div>
    </div>
  )
}
