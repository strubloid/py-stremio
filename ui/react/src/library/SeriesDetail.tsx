import { useState } from 'react'
import { ArrowLeft, Check, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { EpisodeHistory, LibraryEntry, SeriesSummary } from './types'

type Props = {
  series: SeriesSummary
  selectedSeason: LibraryEntry | null
  history: EpisodeHistory | null
  loading: boolean
  busyEpisode: number | null
  initialEpisode?: number | null
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
  initialEpisode,
  onBack,
  onSelectSeason,
  onSetWatched,
  onRedownload,
}: Props) {
  const [episodeSearch, setEpisodeSearch] = useState('')
  const [selectedEpisodeNumber, setSelectedEpisodeNumber] = useState<number | null>(initialEpisode ?? null)
  const orderedSeasons = [...series.seasons].sort((left, right) => (left.season ?? 0) - (right.season ?? 0))
  const episodeNumbers = selectedSeason?.episode_numbers ?? []
  const selectedEpisode = episodeNumbers.includes(selectedEpisodeNumber ?? -1)
    ? selectedEpisodeNumber
    : episodeNumbers[0] ?? null
  const visibleEpisodes = episodeNumbers.filter((episode) =>
    `episode ${episode} e${String(episode).padStart(2, '0')}`.includes(episodeSearch.toLowerCase()),
  )
  const progress = series.total ? Math.round(series.downloaded / series.total * 100) : 0
  const activeFile = selectedEpisode === null
    ? undefined
    : history?.files.find((file) => file.episode === selectedEpisode && !file.is_part)
  const activeAttempt = selectedEpisode === null
    ? undefined
    : history?.attempts.find((attempt) => attempt.episode === selectedEpisode)
  const activeCompletedAt = selectedEpisode === null
    ? undefined
    : history?.attempts.find((attempt) => attempt.episode === selectedEpisode && attempt.success === 1)?.completed_at
  const activeWatched = selectedEpisode !== null && (history?.watched_episodes.includes(selectedEpisode)
    ?? selectedSeason?.watched_episodes?.includes(selectedEpisode)
    ?? false)

  const chooseSeason = (seasonId: string) => {
    const season = orderedSeasons.find((item) => String(item.id) === seasonId)
    if (season) {
      setSelectedEpisodeNumber(null)
      setEpisodeSearch('')
      onSelectSeason(season)
    }
  }

  return (
    <div className="series-screen">
      {series.background_url && <img className="series-backdrop" src={series.background_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} />}
      <div className="series-screen-shade" />
      <div className="series-screen-layout">
        <section className="series-story">
          <Button className="back-link" variant="ghost" onClick={onBack}><ArrowLeft data-icon="inline-start" size={16} /> All series</Button>
          <div className="series-story-copy">
            <p className="detail-kicker">SERIES <span>·</span> {orderedSeasons.length} {orderedSeasons.length === 1 ? 'season' : 'seasons'}</p>
            <h1>{series.title}</h1>
            <p className="detail-stats">{series.downloaded} of {series.total} episodes downloaded <span>·</span> {series.missing} missing</p>
            <Progress className="series-progress" value={progress} aria-label={`${series.title} ${progress}% downloaded`} />
          </div>

          <section className="selected-episode-card" aria-live="polite">
            {selectedSeason && selectedEpisode !== null ? <>
              <div className="selected-episode-art">{series.poster_url && <img src={series.poster_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} />}<span>S{String(selectedSeason.season).padStart(2, '0')}E{String(selectedEpisode).padStart(2, '0')}</span></div>
              <div className="selected-episode-copy">
                <p className="detail-kicker">SELECTED EPISODE</p>
                <h2>Episode {selectedEpisode}</h2>
                <Badge variant={activeFile ? 'outline' : activeAttempt?.success === 0 ? 'destructive' : 'secondary'}>{activeFile ? 'Downloaded' : activeAttempt?.success === 0 ? 'Failed' : 'Missing'}</Badge>
                {activeFile ? <>
                  <p className="episode-file-name">{activeFile.rel_path}</p>
                  <small>{activeFile.size ? `${(activeFile.size / 1_000_000_000).toFixed(2)} GB` : 'File present'}{activeCompletedAt && ` · Downloaded ${new Date(activeCompletedAt).toLocaleDateString()}`}</small>
                  {activeAttempt?.server_url && <small>Source · {activeAttempt.server_url}</small>}
                </> : <p className="episode-file-name">No completed file yet. Search the configured add-ons to download this episode.</p>}
                <div className="selected-episode-actions">
                  <Button variant="outline" size="sm" disabled={selectedEpisode === null} onClick={() => onSetWatched([selectedEpisode], !activeWatched)}>{activeWatched ? <EyeOff data-icon="inline-start" size={14} /> : <Eye data-icon="inline-start" size={14} />}{activeWatched ? 'Mark unwatched' : 'Mark watched'}</Button>
                  <Button size="sm" disabled={busyEpisode === selectedEpisode} onClick={() => onRedownload(selectedSeason, selectedEpisode)}><RotateCcw data-icon="inline-start" size={14} />{busyEpisode === selectedEpisode ? 'Queued…' : activeFile ? 'Re-download' : 'Find a source'}</Button>
                </div>
              </div>
            </> : <div className="selected-empty"><p className="detail-kicker">EPISODE DETAILS</p><h2>Choose a season and episode</h2><p>Files, source history, and watched controls will appear here.</p></div>}
          </section>
        </section>

        <aside className="series-episode-browser" aria-label="Season and episode browser">
          <div className="browser-topline"><span>EPISODES</span><Badge variant="outline">{series.seasons.length} seasons</Badge></div>
          {orderedSeasons.length > 0 ? <Tabs value={selectedSeason ? String(selectedSeason.id) : ''} onValueChange={chooseSeason}>
            <TabsList className="season-tabs" variant="line" aria-label="Select season">
              {orderedSeasons.map((season) => <TabsTrigger value={String(season.id)} key={season.id}>Season {season.season}</TabsTrigger>)}
            </TabsList>
          </Tabs> : <p className="browser-empty">No seasons are cataloged for this series.</p>}
          {selectedSeason && <>
            <label className="episode-search"><Input aria-label="Search episodes" placeholder="Search episodes" value={episodeSearch} onChange={(event) => setEpisodeSearch(event.target.value)} /></label>
            <div className="browser-season-actions"><span>{selectedSeason.downloaded}/{selectedSeason.total} downloaded</span><div><Button variant="ghost" size="sm" onClick={() => onSetWatched(selectedSeason.episode_numbers ?? [], true)}>All watched</Button><Button variant="ghost" size="sm" onClick={() => onSetWatched(selectedSeason.episode_numbers ?? [], false)}>All unwatched</Button></div></div>
            <div className="episode-browser-list">
              {loading ? <div className="episode-list-loading"><span /><span /><span /></div> : visibleEpisodes.map((episode) => {
                const file = history?.files.find((item) => item.episode === episode && !item.is_part)
                const failed = !file && history?.attempts.some((attempt) => attempt.episode === episode && attempt.success === 0)
                const watched = history?.watched_episodes.includes(episode) ?? selectedSeason.watched_episodes?.includes(episode) ?? false
                return <Button className={`episode-browser-row${selectedEpisode === episode ? ' episode-browser-row--active' : ''}`} variant="ghost" key={episode} onClick={() => setSelectedEpisodeNumber(episode)}>
                  <span className={`episode-state${file ? ' episode-state--downloaded' : failed ? ' episode-state--failed' : ''}`} />
                  <span className="episode-row-name"><strong>{String(episode).padStart(2, '0')}</strong><span>Episode {episode}</span></span>
                  {watched && <Check size={14} className="episode-watched-mark" />}
                  {busyEpisode === episode && <span className="episode-queued">Queued</span>}
                </Button>
              })}
              {!loading && visibleEpisodes.length === 0 && <p className="browser-empty">No episodes match your search.</p>}
            </div>
          </>}
          {!selectedSeason && orderedSeasons.length > 0 && <p className="browser-empty">Choose a season to see its episodes.</p>}
        </aside>
      </div>
    </div>
  )
}
