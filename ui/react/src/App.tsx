import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, ArrowDownToLine, Search, Settings2, Tv } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LibraryHome } from '@/library/LibraryHome'
import { MovieDetail } from '@/library/MovieDetail'
import { SeriesDetail } from '@/library/SeriesDetail'
import { LibraryManager } from '@/library/LibraryManager'
import type { EpisodeHistory, LibraryEntry, LibraryMetadataRow, Section, SeriesSummary, SpotlightItem } from '@/library/types'
import { CalendarPage } from '@/calendar/CalendarPage'
import type { CalendarData } from '@/calendar/CalendarPage'
import { SettingsPage } from '@/settings/SettingsPage'
import type { SettingsUpdate, SettingsValues } from '@/settings/SettingsPage'
import { DownloadPage } from '@/download/DownloadPage'
import './App.css'

type LibraryResponse = { entries: LibraryEntry[]; series_seasons: number; movies: number; missing: number }
type DownloadProgressSnapshot = {
  type?: string
  title?: string
  season?: number | null
  episode?: number | null
  current?: number
  total?: number
  downloaded?: number
  bytes_total?: number
  rate_bps?: number
  success?: boolean
  outcome?: string
  server_current?: number
  server_total?: number
  live_current?: number
  live_total?: number
  experimental_current?: number
  experimental_total?: number
  updated_at?: string
}
type JobRun = { id: number | string; job: string; started_at: string; status: string; detail?: string | null; output?: { message: string; timestamp: string; status?: string; item?: LibraryMetadataRow }[]; progress?: DownloadProgressSnapshot[] }
type JobsResponse = { active: JobRun[]; history: JobRun[] }
type ControlValues = { threads: number; speed_percent: number; allow_4k: boolean }
type AddonHealth = { id: number; url: string; status: string; downloads_completed: number; last_tested_at: string | null }
type ProgressEvent = DownloadProgressSnapshot & { id: number; message: string }
type JobOutputLine = { id: number; message: string; timestamp: string; status?: string; item?: LibraryMetadataRow }

export function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('py-stremio-token') ?? '')
  const [library, setLibrary] = useState<LibraryResponse | null>(null)
  const [spotlight, setSpotlight] = useState<SpotlightItem[]>([])
  const [jobs, setJobs] = useState<JobsResponse | null>(null)
  const [addons, setAddons] = useState<AddonHealth[]>([])
  const [controls, setControls] = useState<ControlValues | null>(null)
  const [settings, setSettings] = useState<SettingsValues | null>(null)
  const [savingSettings, setSavingSettings] = useState(false)
  const [savingLayout, setSavingLayout] = useState(false)
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false)
  const [calendar, setCalendar] = useState<CalendarData | null>(null)
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [calendarMonth, setCalendarMonth] = useState(() => {
    const today = new Date()
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
  })
  const [calendarDate, setCalendarDate] = useState(() => {
    const today = new Date()
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  })
  const [history, setHistory] = useState<EpisodeHistory | null>(null)
  const [detailOwner, setDetailOwner] = useState<{ id: number; kind: 'season' | 'movie' } | null>(null)
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null)
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | null>(null)
  const [focusedEpisode, setFocusedEpisode] = useState<number | null>(null)
  const [selectedMovieId, setSelectedMovieId] = useState<number | null>(null)
  const [section, setSection] = useState<Section>(() => {
    const path = window.location.pathname
    if (path === '/download') return 'download'
    if (path === '/libray' || path === '/library') return 'library'
    return 'home'
  })
  const [search, setSearch] = useState('')
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [jobOutput, setJobOutput] = useState<JobOutputLine[]>([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const nextEventId = useRef(0)

  const progressMessage = useCallback((event: DownloadProgressSnapshot) => {
    const episode = typeof event.season === 'number' && typeof event.episode === 'number'
      ? `S${String(event.season).padStart(2, '0')}E${String(event.episode).padStart(2, '0')}`
      : null
    const progress = typeof event.downloaded === 'number' && typeof event.bytes_total === 'number' && event.bytes_total > 0
      ? `${Math.round(event.downloaded / event.bytes_total * 100)}%`
      : null
    const speed = typeof event.rate_bps === 'number' && event.rate_bps > 0
      ? `${(event.rate_bps / 1_000_000).toFixed(1)} MB/s`
      : null
    const phase = event.outcome ?? (event.type === 'episode_done'
      ? event.success ? 'complete' : 'failed'
      : event.type === 'bytes' ? 'downloading' : 'searching')
    return [event.title, episode, phase, progress, speed].filter(Boolean).join(' · ') || 'Download progress update'
  }, [])

  const mergeJobOutput = useCallback((current: JobOutputLine[], incoming: JobOutputLine[]) => {
    const metadata = new Map<string, JobOutputLine>()
    const activity = new Map<string, JobOutputLine>()
    for (const line of [...current, ...incoming]) {
      if (line.item) {
        metadata.set(`${line.item.title}\0${line.item.season}`, line)
      } else {
        const key = `${line.timestamp}\0${line.message}`
        if (!activity.has(key)) activity.set(key, line)
      }
    }
    return [...metadata.values(), ...[...activity.values()].slice(-150)]
      .toSorted((left, right) => left.timestamp.localeCompare(right.timestamp))
  }, [])

  const applyJobsSnapshot = useCallback((jobsData: JobsResponse) => {
    setJobs(jobsData)
    const activeJob = jobsData.active[0]
    const recentOperation = activeJob
      ? activeJob
      : jobsData.history.find((job) => ['configs', 'download', 'download-quick'].includes(job.job) && job.output?.length)
    const output = recentOperation?.output
    if (activeJob?.progress) {
      setEvents(activeJob.progress.toSorted((left, right) =>
        (right.updated_at ?? '').localeCompare(left.updated_at ?? '')
      ).map((event) => ({
        ...event,
        id: nextEventId.current++,
        message: progressMessage(event),
      })).slice(0, 16))
    }
    if (!output?.length) return

    const snapshot = output.map((line) => ({ ...line, id: nextEventId.current++ }))
    setJobOutput((current) => mergeJobOutput(current, snapshot))
  }, [mergeJobOutput, progressMessage])

  const refresh = useCallback(async () => {
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    try {
      const [libraryResponse, jobsResponse, controlsResponse, addonsResponse, settingsResponse] = await Promise.all([
        fetch('/api/library', { headers }),
        fetch('/api/jobs', { headers }),
        fetch('/api/controls', { headers }),
        fetch('/api/addons', { headers }),
        fetch('/api/settings', { headers }),
      ])
      if (!libraryResponse.ok || !jobsResponse.ok) {
        throw new Error(libraryResponse.status === 401 || jobsResponse.status === 401
          ? 'The API token was rejected. Check it and try again.'
          : 'The dashboard API could not be reached.')
      }
      setError(null)
      const libraryData = await libraryResponse.json() as LibraryResponse
      setLibrary(libraryData)
      applyJobsSnapshot(await jobsResponse.json() as JobsResponse)
      setControls(controlsResponse.ok ? await controlsResponse.json() as ControlValues | null : null)
      if (addonsResponse.ok) setAddons((await addonsResponse.json() as { addons: AddonHealth[] }).addons)
      if (settingsResponse.ok) setSettings(await settingsResponse.json() as SettingsValues)

      const today = new Date().toISOString().slice(0, 10)
      const start = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
      const monthKeys = [...new Set([start.slice(0, 7), today.slice(0, 7)])]
      const calendarResponses = await Promise.all(monthKeys.map((month) => {
        const [year, monthNumber] = month.split('-')
        return fetch(`/api/calendar?year=${year}&month=${Number(monthNumber)}`, { headers })
      }))
      if (calendarResponses.some((response) => !response.ok)) {
        throw new Error('Could not load recent releases from the calendar.')
      }
      const calendarMonths = await Promise.all(calendarResponses.map((response) => response.json() as Promise<CalendarData>))
      const recentEpisodes = calendarMonths.flatMap((month) => month.events)
        .filter((event) => event.release_at.slice(0, 10) >= start && event.release_at.slice(0, 10) <= today)
        .toSorted((left, right) => right.release_at.localeCompare(left.release_at))
      const seenSeries = new Set<number>()
      const episodeSpotlight: SpotlightItem[] = recentEpisodes.flatMap((event) => {
        if (seenSeries.has(event.series_id)) return []
        seenSeries.add(event.series_id)
        return [{
          kind: 'series',
          id: event.series_id,
          series_id: event.series_id,
          title: event.series_title,
          poster_url: event.poster_url || event.image_url,
          episode_image_url: event.image_url,
          season: event.season,
          episode: event.episode,
          episode_title: event.title,
          release_at: event.release_at,
        }]
      })
      const movieSpotlight: SpotlightItem[] = libraryData.entries.flatMap((entry) => {
        if (entry.kind !== 'movie' || !entry.release_date || entry.release_date < start || entry.release_date > today) return []
        return [{
          kind: 'movie',
          id: entry.id,
          title: entry.title,
          poster_url: entry.poster_url,
          background_url: entry.background_url,
          release_at: entry.release_date,
        }]
      })
      setSpotlight([...episodeSpotlight, ...movieSpotlight].toSorted((left, right) => right.release_at.localeCompare(left.release_at)))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unexpected dashboard error.')
    } finally {
      setLoading(false)
    }
  }, [applyJobsSnapshot, token])

  useEffect(() => {
    sessionStorage.setItem('py-stremio-token', token)
    const frame = window.requestAnimationFrame(() => void refresh())
    const timer = window.setInterval(() => void refresh(), 15000)
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearInterval(timer)
    }
  }, [refresh, token])

  useEffect(() => {
    const syncSectionFromPath = () => {
      const path = window.location.pathname
      setSection(path === '/download' ? 'download' : path === '/libray' || path === '/library' ? 'library' : 'home')
    }
    window.addEventListener('popstate', syncSectionFromPath)
    return () => window.removeEventListener('popstate', syncSectionFromPath)
  }, [])

  useEffect(() => {
    if (section !== 'download' || (!busyAction && !jobs?.active.length)) return
    const pollJobOutput = async () => {
      const headers = token ? { Authorization: `Bearer ${token}` } : undefined
      const response = await fetch('/api/jobs', { headers })
      if (!response.ok) return
      const jobsData = await response.json() as JobsResponse
      applyJobsSnapshot(jobsData)
      if (jobs?.active.length && !jobsData.active.length) await refresh()
    }
    const timer = window.setInterval(() => {
      void pollJobOutput().catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : 'Could not refresh job activity.')
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [applyJobsSnapshot, busyAction, jobs?.active.length, refresh, section, token])

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const auth = token ? `?token=${encodeURIComponent(token)}` : ''
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/progress${auth}`)
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as Record<string, unknown>
      if (event.type === 'keepalive') return
      const jobMessage = event.message
      if (event.type === 'job_output' && typeof jobMessage === 'string') {
        const outputItem = event.item
        const item = typeof outputItem === 'object' && outputItem !== null
          && 'title' in outputItem && typeof outputItem.title === 'string'
          && 'season' in outputItem && typeof outputItem.season === 'string'
          && 'episodes' in outputItem && typeof outputItem.episodes === 'string'
          && 'imdb_id' in outputItem && typeof outputItem.imdb_id === 'string'
          && 'status' in outputItem && typeof outputItem.status === 'string'
          ? {
              title: outputItem.title,
              season: outputItem.season,
              episodes: outputItem.episodes,
              imdb_id: outputItem.imdb_id,
              status: outputItem.status,
            }
          : undefined
        setJobOutput((current) => mergeJobOutput(current, [{
          id: nextEventId.current++,
          message: jobMessage,
          timestamp: typeof event.timestamp === 'string' ? event.timestamp : new Date().toISOString(),
          status: typeof event.status === 'string' ? event.status : undefined,
          item,
        }]))
        return
      }
      const progressEvent: DownloadProgressSnapshot = {
        type: typeof event.type === 'string' ? event.type : undefined,
        title: typeof event.title === 'string' ? event.title : undefined,
        season: typeof event.season === 'number' ? event.season : null,
        episode: typeof event.episode === 'number' ? event.episode : null,
        current: typeof event.current === 'number' ? event.current : undefined,
        total: typeof event.total === 'number' ? event.total : undefined,
        downloaded: typeof event.downloaded === 'number' ? event.downloaded : undefined,
        bytes_total: typeof event.bytes_total === 'number' ? event.bytes_total : undefined,
        rate_bps: typeof event.rate_bps === 'number' ? event.rate_bps : undefined,
        success: typeof event.success === 'boolean' ? event.success : undefined,
        outcome: typeof event.outcome === 'string' ? event.outcome : undefined,
        server_current: typeof event.server_current === 'number' ? event.server_current : undefined,
        server_total: typeof event.server_total === 'number' ? event.server_total : undefined,
        live_current: typeof event.live_current === 'number' ? event.live_current : undefined,
        live_total: typeof event.live_total === 'number' ? event.live_total : undefined,
        experimental_current: typeof event.experimental_current === 'number' ? event.experimental_current : undefined,
        experimental_total: typeof event.experimental_total === 'number' ? event.experimental_total : undefined,
      }
      const eventKey = `${progressEvent.title ?? ''}\0${progressEvent.season ?? ''}\0${progressEvent.episode ?? ''}`
      const entry: ProgressEvent = { ...progressEvent, id: nextEventId.current++, message: progressMessage(progressEvent) }
      setEvents((current) => {
        const withoutEvent = current.filter((item) => `${item.title ?? ''}\0${item.season ?? ''}\0${item.episode ?? ''}` !== eventKey)
        return [entry, ...withoutEvent].slice(0, 16)
      })
    }
    return () => socket.close()
  }, [mergeJobOutput, progressMessage, token])

  useEffect(() => {
    if (section !== 'calendar') return
    let current = true
    const loadCalendar = async () => {
      setCalendarLoading(true)
      const headers = token ? { Authorization: `Bearer ${token}` } : undefined
      try {
        const response = await fetch(`/api/calendar?year=${calendarMonth.slice(0, 4)}&month=${Number(calendarMonth.slice(5, 7))}`, { headers })
        if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not load the release calendar.')
        const data = await response.json() as CalendarData
        if (current) setCalendar(data)
      } catch (caught) {
        if (current) setError(caught instanceof Error ? caught.message : 'Could not load the release calendar.')
      } finally {
        if (current) setCalendarLoading(false)
      }
    }
    void loadCalendar()
    const timer = window.setInterval(() => void loadCalendar(), 15000)
    return () => {
      current = false
      window.clearInterval(timer)
    }
  }, [calendarMonth, section, token])

  const series = (() => {
    const grouped = new Map<number, SeriesSummary>()
    for (const entry of library?.entries ?? []) {
      if (entry.kind !== 'season') continue
      const id = entry.series_id ?? entry.id
      const item = grouped.get(id) ?? {
        id,
        title: entry.title,
        imdb_id: entry.imdb_id,
        poster_url: entry.poster_url,
        background_url: entry.background_url,
        seasons: [],
        downloaded: 0,
        total: 0,
        missing: 0,
        unwatchedDownloaded: 0,
      }
      item.seasons.push(entry)
      item.poster_url ||= entry.poster_url
      item.background_url ||= entry.background_url
      item.downloaded += entry.downloaded
      item.total += entry.total
      item.missing += entry.missing
      const watched = new Set(entry.watched_episodes ?? [])
      item.unwatchedDownloaded += (entry.downloaded_episodes ?? []).filter((episode) => !watched.has(episode)).length
      grouped.set(id, item)
    }
    return [...grouped.values()].sort((left, right) => left.title.localeCompare(right.title))
  })()

  const movies = (library?.entries ?? []).filter((entry) => entry.kind === 'movie')
  const selectedSeries = series.find((item) => item.id === selectedSeriesId) ?? null
  const selectedSeason = selectedSeries?.seasons.find((item) => item.id === selectedSeasonId) ?? null
  const selectedMovie = movies.find((item) => item.id === selectedMovieId) ?? null

  const loadEpisodeHistory = async (owner: { id: number; kind: 'season' | 'movie' }) => {
    setDetailOwner(owner)
    setDetailLoading(true)
    setHistory(null)
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    try {
      const response = await fetch(`/api/episodes/${owner.id}?kind=${owner.kind}`, { headers })
      if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not load file details.')
      setHistory(await response.json() as EpisodeHistory)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load file details.')
    } finally {
      setDetailLoading(false)
    }
  }

  const openSeries = (seriesId: number) => {
    const firstSeason = series.find((item) => item.id === seriesId)?.seasons
      .toSorted((left, right) => (left.season ?? 0) - (right.season ?? 0))[0]
    setSelectedSeriesId(seriesId)
    setSelectedSeasonId(firstSeason?.id ?? null)
    setFocusedEpisode(null)
    setSelectedMovieId(null)
    setHistory(null)
    setSection('series')
    if (firstSeason) void loadEpisodeHistory({ id: firstSeason.id, kind: 'season' })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const openMovie = (movie: LibraryEntry) => {
    setSelectedMovieId(movie.id)
    setSelectedSeriesId(null)
    setHistory(null)
    setSection('movies')
    void loadEpisodeHistory({ id: movie.id, kind: 'movie' })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const openSpotlight = (item: SpotlightItem) => {
    if (item.kind === 'movie') {
      const movie = movies.find((entry) => entry.id === item.id)
      if (movie) openMovie(movie)
      return
    }
    const seriesId = item.series_id ?? item.id
    const matchingSeason = series.find((entry) => entry.id === seriesId)?.seasons.find((season) => season.season === item.season)
    setSelectedSeriesId(seriesId)
    setSelectedSeasonId(matchingSeason?.id ?? null)
    setFocusedEpisode(item.episode ?? null)
    setSelectedMovieId(null)
    setHistory(null)
    setSection('series')
    if (matchingSeason) void loadEpisodeHistory({ id: matchingSeason.id, kind: 'season' })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const selectSeason = (season: LibraryEntry) => {
    setSelectedSeasonId(season.id)
    setFocusedEpisode(null)
    void loadEpisodeHistory({ id: season.id, kind: 'season' })
  }

  const setWatched = async (owner: { id: number; kind: 'season' | 'movie' }, episodes: number[], watched: boolean) => {
    if (!episodes.length) return
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch(`/api/episodes/${owner.id}/watch`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ kind: owner.kind, episodes, watched }),
      })
      if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not save watched status.')
      await Promise.all([refresh(), loadEpisodeHistory(owner)])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save watched status.')
    }
  }

  const redownload = async (owner: { id: number; kind: 'season' | 'movie' }, episode?: number) => {
    const actionKey = `${owner.kind}-${owner.id}-${episode ?? 0}`
    setBusyAction(actionKey)
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch(`/api/episodes/${owner.id}/redownload`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ kind: owner.kind, episode }),
      })
      const body = await response.json() as { detail?: string }
      if (!response.ok) throw new Error(body.detail || (response.status === 401 ? 'The API token was rejected.' : 'Could not queue this re-download.'))
      setError(null)
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not queue this re-download.')
    } finally {
      setBusyAction(null)
    }
  }

  const enableLibraryEntry = async (entry: LibraryEntry) => {
    await setLibraryEntryEnabled(entry, true)
  }

  const removeLibrarySeason = async (entry: LibraryEntry) => {
    setBusyAction(`remove-season-${entry.id}`)
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    try {
      const response = await fetch(`/api/library/season/${entry.id}`, { method: 'DELETE', headers })
      if (!response.ok) {
        const body = await response.json() as { detail?: string }
        throw new Error(body.detail || (response.status === 401 ? 'The API token was rejected.' : 'Could not delete this season folder.'))
      }
      if (selectedSeasonId === entry.id) {
        setSelectedSeasonId(null)
        setDetailOwner(null)
        setHistory(null)
      }
      setError(null)
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete this season folder.')
    } finally {
      setBusyAction(null)
    }
  }

  const setLibraryEntryEnabled = async (entry: LibraryEntry, enabled: boolean) => {
    setBusyAction(`enable-${entry.kind}-${entry.id}`)
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch(`/api/library/${entry.kind}/${entry.id}/enabled`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ enabled }),
      })
      if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not enable this library item.')
      setError(null)
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not enable this library item.')
    } finally {
      setBusyAction(null)
    }
  }

  const updateControls = async (values: Partial<ControlValues>) => {
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch('/api/controls', { method: 'POST', headers, body: JSON.stringify(values) })
      if (!response.ok) throw new Error(response.status === 409 ? 'Controls are available during an active download.' : 'Could not update download controls.')
      setControls(await response.json() as ControlValues)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not update download controls.')
    }
  }

  const runJob = useCallback(async (name: 'configs' | 'download' | 'download-quick' | 'calendar-refresh') => {
    setBusyAction(name)
    if (name === 'configs' || name === 'download' || name === 'download-quick') {
      setEvents([])
      const labels = { configs: 'Update library', download: 'Update and download', 'download-quick': 'Download only' }
      setJobOutput([{
        id: nextEventId.current++,
        message: `Submitting ${labels[name]} to the API worker`,
        timestamp: new Date().toISOString(),
        status: 'queued',
      }])
    }
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : undefined
      const response = await fetch(`/api/jobs/${name}`, { method: 'POST', headers })
      if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not start this job.')
      if (name === 'configs' || name === 'download' || name === 'download-quick') {
        setJobOutput((current) => [...current, {
          id: nextEventId.current++,
          message: 'API accepted the job; waiting for its first work update',
          timestamp: new Date().toISOString(),
          status: 'queued',
        }])
      }
      await refresh()
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start this job.')
    } finally {
      setBusyAction(null)
    }
  }, [refresh, token])

  const updateSettings = async (values: SettingsUpdate) => {
    setSavingSettings(true)
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch('/api/settings', { method: 'PUT', headers, body: JSON.stringify(values) })
      if (!response.ok) throw new Error(response.status === 401 ? 'The API token was rejected.' : 'Could not save settings.')
      setSettings(await response.json() as SettingsValues)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save settings.')
    } finally {
      setSavingSettings(false)
    }
  }

  const updateLayout = async (library_layout: SettingsValues['library_layout']): Promise<boolean> => {
    const previous = settings?.library_layout ?? 'stremio'
    setSettings((current) => current ? { ...current, library_layout } : current)
    setSavingLayout(true)
    const headers = new Headers({ 'Content-Type': 'application/json' })
    if (token) headers.set('Authorization', `Bearer ${token}`)
    try {
      const response = await fetch('/api/settings', { method: 'PUT', headers, body: JSON.stringify({ library_layout }) })
      if (!response.ok) throw new Error('Could not save the library layout.')
      setSettings(await response.json() as SettingsValues)
      setError(null)
      return true
    } catch (caught) {
      setSettings((current) => current ? { ...current, library_layout: previous } : current)
      setError(caught instanceof Error ? caught.message : 'Could not save the library layout.')
      return false
    } finally {
      setSavingLayout(false)
    }
  }

  const changeCalendarMonth = (month: string) => {
    setCalendarMonth(month)
    setCalendarDate(`${month}-01`)
  }

  const handleSectionChange = (value: string) => {
    if (value === 'home' || value === 'series' || value === 'movies' || value === 'library' || value === 'calendar' || value === 'activity' || value === 'download' || value === 'settings') {
      window.history.pushState({}, '', value === 'download' ? '/download' : value === 'library' ? '/libray' : '/')
      setSection(value)
      setSelectedSeriesId(null)
      setSelectedMovieId(null)
      setSelectedSeasonId(null)
      setFocusedEpisode(null)
      setDetailOwner(null)
    }
  }

  const refreshCalendar = () => {
    void runJob('calendar-refresh')
  }

  return (
    <div className="dark streaming-shell">
      <header className="streaming-nav">
        <a className="streaming-brand" href="#home" onClick={(event) => { event.preventDefault(); handleSectionChange('home') }} aria-label="py-stremio home">
          <span className="brand-emblem"><Tv size={17} /></span><span>STREMIO</span>
        </a>
        <Tabs className="top-tabs" value={section} onValueChange={handleSectionChange}>
          <TabsList variant="line" aria-label="Library sections">
            <TabsTrigger value="home">Home</TabsTrigger>
            <TabsTrigger value="series">Series</TabsTrigger>
            <TabsTrigger value="movies">Films</TabsTrigger>
            <TabsTrigger value="library">Library</TabsTrigger>
            <TabsTrigger value="calendar">Calendar</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
            <TabsTrigger value="download"><ArrowDownToLine data-icon="inline-start" size={15} /> Downloads</TabsTrigger>
            <TabsTrigger value="settings"><Settings2 data-icon="inline-start" size={15} /> Settings</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="nav-tools">
          <label className="nav-search"><Search size={16} /><Input aria-label="Search your library" placeholder="Search titles" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label className="token-field"><span>API token</span><Input aria-label="API token" type="password" autoComplete="off" placeholder="Optional" value={token} onChange={(event) => { setToken(event.target.value); setError(null) }} /></label>
          <DropdownMenu open={layoutMenuOpen} onOpenChange={setLayoutMenuOpen}>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="Open settings menu"><Settings2 /></Button>} />
            <DropdownMenuContent align="end" className="layout-menu w-64">
              <p className="layout-menu-label">Library Layout</p>
              <DropdownMenuRadioGroup
                value={settings?.library_layout ?? 'stremio'}
                onValueChange={(value) => {
                  if (value === 'stremio' || value === 'netflix' || value === 'apple-tv' || value === 'plex' || value === 'disney-plus' || value === 'prime-video') {
                    void updateLayout(value)
                    setLayoutMenuOpen(false)
                  }
                }}
              >
                <DropdownMenuRadioItem value="stremio" disabled={savingLayout}>Stremio</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="netflix" disabled={savingLayout}>Netflix</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="apple-tv" disabled={savingLayout}>Apple TV</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="plex" disabled={savingLayout}>Plex</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="disney-plus" disabled={savingLayout}>Disney+</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="prime-video" disabled={savingLayout}>Prime Video</DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => handleSectionChange('settings')}>Open full settings...</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <main className="streaming-main">
        {error && <div className="error-banner" role="alert">{error}</div>}
        {loading && !library ? <LoadingLibrary /> : section === 'home' ? <LibraryHome section="home" series={series} movies={movies} spotlight={spotlight} search={search} layout={settings?.library_layout ?? 'stremio'} onOpenSeries={openSeries} onOpenMovie={openMovie} onOpenSpotlight={openSpotlight} onRefreshSpotlight={() => void runJob('calendar-refresh')} />
          : section === 'library' ? <LibraryManager series={series} movies={movies} busy={busyAction !== null || Boolean(jobs?.active.some((job) => job.job === 'download' || job.job === 'download-quick'))} onOpenSeries={openSeries} onOpenMovie={openMovie} onSetEnabled={(entry, enabled) => void setLibraryEntryEnabled(entry, enabled)} onRemoveSeason={(entry) => void removeLibrarySeason(entry)} />
          : section === 'series' ? selectedSeries ? <SeriesDetail
            key={`${selectedSeries.id}-${selectedSeasonId}-${focusedEpisode ?? ''}`}
            series={selectedSeries}
            selectedSeason={selectedSeason}
            history={detailOwner?.kind === 'season' ? history : null}
            loading={detailLoading && detailOwner?.kind === 'season'}
            busyEpisode={busyAction?.startsWith(`season-${selectedSeasonId}-`) ? Number(busyAction.split('-').at(-1)) : null}
            initialEpisode={focusedEpisode}
            onBack={() => { setSelectedSeriesId(null); setSelectedSeasonId(null); setDetailOwner(null) }}
            onSelectSeason={selectSeason}
            onSetWatched={(episodes, watched) => selectedSeason && void setWatched({ id: selectedSeason.id, kind: 'season' }, episodes, watched)}
            onRedownload={(season, episode) => void redownload({ id: season.id, kind: 'season' }, episode)}
          /> : <LibraryHome section="series" series={series} movies={movies} spotlight={spotlight} search={search} layout={settings?.library_layout ?? 'stremio'} onOpenSeries={openSeries} onOpenMovie={openMovie} onOpenSpotlight={openSpotlight} onRefreshSpotlight={() => void runJob('calendar-refresh')} />
            : section === 'movies' ? selectedMovie ? <MovieDetail
              movie={selectedMovie}
              history={detailOwner?.kind === 'movie' ? history : null}
              loading={detailLoading && detailOwner?.kind === 'movie'}
              busy={busyAction === `movie-${selectedMovie.id}-0`}
              onBack={() => { setSelectedMovieId(null); setDetailOwner(null) }}
              onSetWatched={(watched) => void setWatched({ id: selectedMovie.id, kind: 'movie' }, [0], watched)}
              onRedownload={() => void redownload({ id: selectedMovie.id, kind: 'movie' })}
               /> : <LibraryHome section="movies" series={series} movies={movies} spotlight={spotlight} search={search} layout={settings?.library_layout ?? 'stremio'} onOpenSeries={openSeries} onOpenMovie={openMovie} onOpenSpotlight={openSpotlight} onRefreshSpotlight={() => void runJob('calendar-refresh')} />
                : section === 'download' ? <DownloadPage entries={library?.entries ?? []} events={events} jobOutput={jobOutput} running={Boolean(jobs?.active.some((job) => job.job === 'download' || job.job === 'download-quick' || job.job === 'configs'))} busy={busyAction !== null} onStart={(job) => void runJob(job)} onEnable={(entry) => void enableLibraryEntry(entry)} />
               : section === 'calendar' ? <CalendarPage
                month={calendarMonth}
                selectedDate={calendarDate}
                data={calendar}
                loading={calendarLoading}
                refreshing={busyAction === 'calendar-refresh' || Boolean(jobs?.active.some((job) => job.job === 'calendar-refresh'))}
                onMonthChange={changeCalendarMonth}
                onSelectDate={setCalendarDate}
                onRefresh={refreshCalendar}
              /> : section === 'settings' ? settings ? <SettingsPage settings={settings} saving={savingSettings} savingLayout={savingLayout} onSave={updateSettings} onLayoutChange={updateLayout} /> : <LoadingLibrary />
                : <OperationsPanel jobs={jobs} addons={addons} events={events} controls={controls} updateControls={updateControls} runJob={runJob} busyAction={busyAction} />}
      </main>
    </div>
  )
}

function LoadingLibrary() {
  return <div className="loading-library" aria-label="Loading library"><Skeleton className="hero-skeleton" /><div className="loading-covers">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="cover-skeleton" />)}</div></div>
}

function OperationsPanel({
  jobs,
  addons,
  events,
  controls,
  updateControls,
  runJob,
  busyAction,
}: {
  jobs: JobsResponse | null
  addons: AddonHealth[]
  events: ProgressEvent[]
  controls: ControlValues | null
  updateControls: (values: Partial<ControlValues>) => void
  runJob: (name: 'configs' | 'download') => void
  busyAction: string | null
}) {
  return <section className="operations-page">
    <div className="browse-heading"><span className="browse-heading-icon"><Activity size={18} /></span><h1>Activity</h1></div>
    <div className="operations-actions"><Button variant="outline" onClick={() => void runJob('configs')} disabled={busyAction !== null}>Refresh library</Button><Button onClick={() => void runJob('download')} disabled={busyAction !== null}>Download missing</Button></div>
    {controls && <section className="operation-block"><div className="section-title-line"><div><h2>Active download</h2><p>Changes apply to the running session.</p></div></div><div className="live-control-row"><div className="control-pair"><span>Workers</span><Button variant="outline" size="icon-sm" aria-label="Decrease workers" onClick={() => void updateControls({ threads: Math.max(1, controls.threads - 1) })}>−</Button><strong>{controls.threads}</strong><Button variant="outline" size="icon-sm" aria-label="Increase workers" onClick={() => void updateControls({ threads: Math.min(16, controls.threads + 1) })}>+</Button></div><div className="control-pair"><span>Speed</span><Button variant="outline" size="icon-sm" aria-label="Decrease speed" onClick={() => void updateControls({ speed_percent: Math.max(1, controls.speed_percent - 5) })}>−</Button><strong>{controls.speed_percent}%</strong><Button variant="outline" size="icon-sm" aria-label="Increase speed" onClick={() => void updateControls({ speed_percent: Math.min(100, controls.speed_percent + 5) })}>+</Button></div><Button variant={controls.allow_4k ? 'default' : 'outline'} onClick={() => void updateControls({ allow_4k: !controls.allow_4k })}>4K {controls.allow_4k ? 'enabled' : 'disabled'}</Button></div></section>}
    <div className="operations-grid">
      <section className="operation-block"><div className="section-title-line"><div><h2>Live activity</h2><p>Progress from the active downloader</p></div><span className="live-indicator"><i /> Live</span></div><div className="operations-list">{events.map((event) => <p className="live-event" key={event.id}><span className="activity-marker" />{event.message}</p>)}{events.length === 0 && <p className="quiet-empty">No active progress events.</p>}</div></section>
      <section className="operation-block"><div className="section-title-line"><div><h2>Recent runs</h2><p>Latest scheduled and manual jobs</p></div></div><div className="operations-list">{jobs?.history.slice(0, 10).map((run) => <div className="operation-row" key={run.id}><span className={`run-status ${run.status}`} /><span>{run.job}<small>{new Date(run.started_at).toLocaleString()}</small></span><Badge variant={run.status === 'failed' ? 'destructive' : 'outline'}>{run.status}</Badge></div>)}{!jobs?.history.length && <p className="quiet-empty">No runs recorded yet.</p>}</div></section>
      <section className="operation-block"><div className="section-title-line"><div><h2>Sources</h2><p>Verified add-ons from completed downloads</p></div></div><div className="operations-list">{addons.slice(0, 12).map((addon) => <div className="operation-row" key={addon.id}><span className={`run-status ${addon.status === 'working' ? 'ok' : addon.status === 'failed' ? 'failed' : ''}`} /><span className="operation-addon">{addon.url}<small>{addon.downloads_completed} completed downloads</small></span><Badge variant={addon.status === 'failed' ? 'destructive' : 'outline'}>{addon.status}</Badge></div>)}{!addons.length && <p className="quiet-empty">Verified sources appear after a completed download.</p>}</div></section>
    </div>
  </section>
}
