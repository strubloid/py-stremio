export type LibraryEntry = {
  kind: 'season' | 'movie'
  id: number
  series_id?: number
  title: string
  imdb_id?: string | null
  poster_url?: string | null
  background_url?: string | null
  season?: number
  downloaded: number
  total: number
  missing: number
  enabled: boolean
  episode_numbers?: number[]
  downloaded_episodes?: number[]
  watched_episodes?: number[]
  season_watched?: boolean
  folder_exists?: boolean
  watched?: boolean
  release_date?: string | null
  metadata_due_at: string | null
  rel_path?: string
}

export type LibraryMetadataRow = {
  title: string
  season: string
  episodes: string
  imdb_id: string
  status: string
}

export type SeriesSummary = {
  id: number
  title: string
  imdb_id?: string | null
  poster_url?: string | null
  background_url?: string | null
  seasons: LibraryEntry[]
  known_seasons?: KnownSeason[]
  downloaded: number
  total: number
  missing: number
  unwatchedDownloaded: number
}

export type KnownSeason = {
  season: number
  episode_count: number
  episode_numbers: number[]
}

export type EpisodeHistory = {
  files: {
    rel_path: string
    episode: number | null
    size: number | null
    mtime_ns: number | null
    is_part: number
  }[]
  attempts: {
    episode: number | null
    success: number | null
    server_url: string
    error: string
    started_at: string | null
    completed_at: string | null
    quality: string | null
  }[]
  watched_episodes: number[]
}

export type Section = 'home' | 'series' | 'movies' | 'library' | 'calendar' | 'activity' | 'download' | 'settings'
export type LibraryLayout = 'stremio' | 'netflix' | 'apple-tv' | 'plex' | 'disney-plus' | 'prime-video'

export type SpotlightItem = {
  kind: 'series' | 'movie'
  id: number
  series_id?: number
  title: string
  poster_url?: string | null
  background_url?: string | null
  episode_image_url?: string | null
  season?: number
  episode?: number
  episode_title?: string | null
  release_at: string
}
