import { ArrowLeft, Check, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import type { EpisodeHistory, LibraryEntry, SeriesSummary } from './types'

type Props = {
  series: SeriesSummary
  selectedSeason: LibraryEntry | null
  history: EpisodeHistory | null
  loading: boolean
  busyEpisode: number | null
  onBack: () => void
  onSelectSeason: (season: LibraryEntry) => void
  onSetWatched: (episodes: number[], watched: boolean) => void
  onRedownload: (season: LibraryEntry, episode: number) => void
}

export function SeriesDetail({
  series,
  selectedSeason,
  history,
  loading,
  busyEpisode,
  onBack,
  onSelectSeason,
  onSetWatched,
  onRedownload,
}: Props) {
  const percent = series.total ? Math.round(series.downloaded / series.total * 100) : 0
  const orderedSeasons = [...series.seasons].sort((left, right) => (left.season ?? 0) - (right.season ?? 0))

  return (
    <div className="detail-page">
      <Button className="back-link" variant="ghost" onClick={onBack}><ArrowLeft data-icon="inline-start" size={16} /> Back to series</Button>
      <section className="detail-hero">
        <div className="detail-hero-art" aria-hidden="true">{series.poster_url ? <img src={series.poster_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} /> : <span>{series.title.slice(0, 1).toUpperCase()}</span>}</div>
        <div className="detail-hero-copy">
          <p className="detail-kicker">SERIES <span>·</span> {orderedSeasons.length} {orderedSeasons.length === 1 ? 'season' : 'seasons'}</p>
          <h1>{series.title}</h1>
          <p className="detail-stats">{series.downloaded} of {series.total} episodes downloaded <span>·</span> {series.missing} missing</p>
          <Progress value={percent} aria-label={`${series.title} ${percent}% downloaded`} />
        </div>
      </section>

      <section className="season-picker" aria-labelledby="season-picker-title">
        <div className="section-title-line"><div><h2 id="season-picker-title">Seasons</h2><p>Choose a season to browse episodes and file details.</p></div><span>{orderedSeasons.length} total</span></div>
        <div className="season-shelf">
          {orderedSeasons.map((season) => {
            const watched = season.watched_episodes?.length ?? 0
            const done = season.downloaded === season.total && season.total > 0
            return <Button
              className={`season-tile${selectedSeason?.id === season.id ? ' season-tile--selected' : ''}`}
              variant="outline"
              key={season.id}
              onClick={() => onSelectSeason(season)}
            >
              <span className="season-number">{String(season.season ?? 0).padStart(2, '0')}</span>
              {season.poster_url && <img className="season-poster" src={season.poster_url} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
              <span className="season-tile-copy"><strong>Season {season.season}</strong><small>{season.downloaded}/{season.total} downloaded · {watched} watched</small></span>
              {done && <Check className="season-check" size={16} />}
            </Button>
          })}
        </div>
      </section>

      {selectedSeason && <section className="episodes-section" aria-labelledby="episodes-title">
        <div className="section-title-line episodes-heading">
          <div><h2 id="episodes-title">Season {selectedSeason.season}</h2><p>{selectedSeason.total} episodes · {selectedSeason.missing} still missing</p></div>
          <div className="episode-bulk-actions">
            <Button variant="outline" size="sm" onClick={() => onSetWatched(selectedSeason.episode_numbers ?? [], true)}><Eye data-icon="inline-start" size={14} /> Mark season watched</Button>
            <Button variant="ghost" size="sm" onClick={() => onSetWatched(selectedSeason.episode_numbers ?? [], false)}><EyeOff data-icon="inline-start" size={14} /> Mark unwatched</Button>
          </div>
        </div>
        {loading ? <div className="episode-list-loading" aria-label="Loading episodes"><span /><span /><span /></div> : <div className="episode-list">
          {(selectedSeason.episode_numbers ?? []).map((episode) => {
            const file = history?.files.find((item) => item.episode === episode && !item.is_part)
            const attempt = history?.attempts.find((item) => item.episode === episode)
            const downloaded = Boolean(file)
            const watched = history?.watched_episodes.includes(episode) ?? selectedSeason.watched_episodes?.includes(episode) ?? false
            const failed = !downloaded && attempt?.success === 0
            const status = downloaded ? 'Downloaded' : failed ? 'Failed' : 'Missing'
            const completedAt = history?.attempts.find((item) => item.episode === episode && item.success === 1)?.completed_at
            const fileDate = file?.mtime_ns ? new Date(file.mtime_ns / 1_000_000).toLocaleDateString() : null
            return <article className="episode-row" key={episode}>
              <div className={`episode-art${downloaded ? ' episode-art--downloaded' : ''}`}><span>E{String(episode).padStart(2, '0')}</span></div>
              <div className="episode-copy">
                <div className="episode-title-line"><h3>Episode {episode}</h3><Badge variant={downloaded ? 'outline' : failed ? 'destructive' : 'secondary'}>{status}</Badge>{watched && <Badge className="watched-badge" variant="outline"><Check size={11} /> Watched</Badge>}</div>
                <p>{file?.rel_path ?? (failed ? attempt?.error || 'Last attempt did not complete' : 'No file downloaded')}</p>
                {downloaded && <small>{file?.size ? `${(file.size / 1_000_000_000).toFixed(2)} GB` : 'File present'}{(completedAt || fileDate) && ` · Downloaded ${completedAt ? new Date(completedAt).toLocaleDateString() : fileDate}`}{attempt?.server_url && ` · ${attempt.server_url}`}</small>}
              </div>
              <div className="episode-actions">
                <Button variant="ghost" size="icon-sm" aria-label={watched ? `Mark episode ${episode} unwatched` : `Mark episode ${episode} watched`} title={watched ? 'Mark unwatched' : 'Mark watched'} onClick={() => onSetWatched([episode], !watched)}>{watched ? <EyeOff /> : <Eye />}</Button>
                <Button variant="outline" size="sm" disabled={busyEpisode === episode} onClick={() => onRedownload(selectedSeason, episode)}><RotateCcw data-icon="inline-start" size={14} />{busyEpisode === episode ? 'Queued…' : downloaded ? 'Re-download' : 'Try again'}</Button>
              </div>
            </article>
          })}
        </div>}
      </section>}
    </div>
  )
}
