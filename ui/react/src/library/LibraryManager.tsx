import { Fragment, useState } from 'react'
import { Check, ChevronDown, FolderOpen, Plus, Search } from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/components/ui/drawer'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Toggle } from '@/components/ui/toggle'
import type { LibraryEntry, SeriesSummary } from './types'

type Props = {
  series: SeriesSummary[]
  movies: LibraryEntry[]
  busy: boolean
  onOpenMovie: (movie: LibraryEntry) => void
  onSetEnabled: (entry: LibraryEntry, enabled: boolean) => void
  onSetSeasonWatched: (entry: LibraryEntry, watched: boolean) => void
  onSetKnownSeasonWatched: (seriesId: number, season: number, watched: boolean) => void
  onAddSeason: (seriesId: number, season: number) => void
  onRemoveSeason: (entry: LibraryEntry) => void
}

export function LibraryManager({ series, movies, busy, onOpenMovie, onSetEnabled, onSetSeasonWatched, onSetKnownSeasonWatched, onAddSeason, onRemoveSeason }: Props) {
  const [view, setView] = useState<'active' | 'excluded'>('active')
  const [query, setQuery] = useState('')
  const [pendingSeasonRemoval, setPendingSeasonRemoval] = useState<{ entry: LibraryEntry; title: string } | null>(null)
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null)
  const [newSeasonNumber, setNewSeasonNumber] = useState('')
  const [missingSeasonsOpen, setMissingSeasonsOpen] = useState(false)
  const activeCount = series.flatMap((item) => item.seasons).filter((item) => item.enabled).length
    + movies.filter((item) => item.enabled).length
  const excludedCount = series.flatMap((item) => item.seasons).filter((item) => !item.enabled).length
    + movies.filter((item) => !item.enabled).length
  const visibleSeries = series.map((item) => ({
    ...item,
    seasons: item.seasons.filter((season) => season.enabled === (view === 'active'))
      .toSorted((left, right) => (left.season ?? 0) - (right.season ?? 0)),
  })).filter((item) => item.seasons.length > 0
    && item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
    .toSorted((left, right) => left.title.localeCompare(right.title))
  const visibleMovies = movies.filter((movie) => movie.enabled === (view === 'active')
    && movie.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
    .toSorted((left, right) => left.title.localeCompare(right.title))
  const selectedSeries = series.find((item) => item.id === selectedSeriesId)
  const onDiskSeasonNumbers = new Set((selectedSeries?.seasons ?? [])
    .filter((season) => season.folder_exists !== false)
    .map((season) => season.season ?? 1))
  const onDiskSeasons = (selectedSeries?.seasons ?? []).filter((season) => season.folder_exists !== false)
  const missingSeasonMap = new Map<number, { season: number; episode_count: number; episode_numbers: number[]; entry?: LibraryEntry; watched: boolean }>()
  for (const season of selectedSeries?.seasons ?? []) {
    if (season.folder_exists === false) {
      missingSeasonMap.set(season.season ?? 1, {
        season: season.season ?? 1,
        episode_count: season.total,
        episode_numbers: season.episode_numbers ?? [],
        entry: season,
        watched: Boolean(season.season_watched),
      })
    }
  }
  for (const season of selectedSeries?.known_seasons ?? []) {
    if (!onDiskSeasonNumbers.has(season.season)) {
      const existing = missingSeasonMap.get(season.season)
      missingSeasonMap.set(season.season, {
        ...season,
        entry: existing?.entry,
        watched: existing?.watched ?? false,
      })
    }
  }
  const missingSeasons = [...missingSeasonMap.values()].toSorted((left, right) => left.season - right.season)
  const removePendingSeason = () => {
    if (!pendingSeasonRemoval) return
    onRemoveSeason(pendingSeasonRemoval.entry)
    setPendingSeasonRemoval(null)
  }

  return <section className="library-manager">
    <header className="library-manager-heading">
      <div><span className="browse-heading-icon"><FolderOpen size={19} /></span><h1>Library</h1><p>Manage the seasons and films that define your download queue.</p></div>
      <label className="library-manager-search"><Search size={16} /><Input aria-label="Filter library" placeholder="Filter titles" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    </header>
    <div className="library-manager-toolbar">
      <Tabs value={view} onValueChange={(value) => {
        if (value === 'active' || value === 'excluded') setView(value)
      }}>
        <TabsList variant="line" aria-label="Library status">
          <TabsTrigger value="active">In library <Badge variant="outline">{activeCount}</Badge></TabsTrigger>
          <TabsTrigger value="excluded">Removed <Badge variant="outline">{excludedCount}</Badge></TabsTrigger>
        </TabsList>
      </Tabs>
      <p>Open a series to manage watched seasons, remove folders, or add a season.</p>
    </div>
    <div className="library-table-wrap">
      <Table className="library-data-table">
        <TableHeader><TableRow>
          <TableHead>Title / Season</TableHead><TableHead>On disk</TableHead><TableHead>Missing</TableHead><TableHead>Folder</TableHead><TableHead><span className="sr-only">Actions</span></TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {visibleSeries.map((item) => <Fragment key={`series-group-${item.id}`}>
            <TableRow className="library-series-heading" key={`series-${item.id}`}>
              <TableCell colSpan={5}><Button className="library-table-title" variant="link" onClick={() => setSelectedSeriesId(item.id)}>{item.title}</Button><span>{item.seasons.length} {item.seasons.length === 1 ? 'season' : 'seasons'} · {item.missing} missing episodes</span></TableCell>
            </TableRow>
            {item.seasons.map((season) => <TableRow key={`season-${season.id}`}>
              <TableCell><div className="library-season-indent"><Badge variant="secondary">Season {String(season.season ?? 1).padStart(2, '0')}</Badge>{season.season_watched && <Badge variant="outline">Watched</Badge>}</div></TableCell>
              <TableCell>{season.downloaded}/{season.total}</TableCell>
              <TableCell>{season.missing > 0 ? <Badge variant="outline">{season.missing}</Badge> : <Badge variant="secondary">Complete</Badge>}</TableCell>
              <TableCell className="library-table-path">{season.rel_path}</TableCell>
              <TableCell><Button variant="outline" size="sm" disabled={busy} onClick={() => setSelectedSeriesId(item.id)}>Manage</Button></TableCell>
            </TableRow>)}
          </Fragment>)}
          {visibleMovies.map((movie) => <TableRow key={`movie-${movie.id}`}>
            <TableCell><Button className="library-table-title" variant="link" onClick={() => onOpenMovie(movie)}>{movie.title}</Button><small className="library-table-imdb">Film</small></TableCell>
            <TableCell>{movie.downloaded}/{movie.total}</TableCell>
            <TableCell>{movie.missing > 0 ? <Badge variant="outline">{movie.missing}</Badge> : <Badge variant="secondary">Complete</Badge>}</TableCell>
            <TableCell className="library-table-path">{movie.rel_path}</TableCell>
            <TableCell>{view === 'active'
              ? <Button variant="outline" size="sm" disabled={busy} onClick={() => onSetEnabled(movie, false)}>Exclude film</Button>
              : <Button variant="outline" size="sm" disabled={busy} onClick={() => onSetEnabled(movie, true)}>Restore</Button>}</TableCell>
          </TableRow>)}
        </TableBody>
      </Table>
      {visibleSeries.length + visibleMovies.length === 0 && <p className="manager-empty">{view === 'active' ? 'No library items match this filter.' : 'No removed items match this filter.'}</p>}
    </div>
    <Drawer open={selectedSeries !== undefined} onOpenChange={(open) => {
      if (!open) {
        setSelectedSeriesId(null)
        setNewSeasonNumber('')
      }
    }} swipeDirection="right">
      <DrawerContent className="library-series-drawer">
        {selectedSeries && <>
          <DrawerHeader className="library-series-drawer-header">
            {selectedSeries.poster_url && <img src={selectedSeries.poster_url} alt="" />}
            <div><DrawerTitle>{selectedSeries.title}</DrawerTitle><DrawerDescription>{selectedSeries.imdb_id ?? 'Series management'} · {onDiskSeasons.length} season folder(s) · {selectedSeries.missing} missing episode(s)</DrawerDescription></div>
            <DrawerClose render={<Button variant="ghost" size="icon" aria-label="Close series management">×</Button>} />
          </DrawerHeader>
          <div className="library-series-drawer-body">
            <section className="library-season-management">
              <header className="library-series-section-heading"><div><h2>Season management</h2><p>Watched status and folder removal are remembered by the library.</p></div><Badge variant="outline">{onDiskSeasons.length}</Badge></header>
              {onDiskSeasons.toSorted((left, right) => (left.season ?? 0) - (right.season ?? 0)).map((season) => <article className={`library-season-management-row ${season.enabled ? '' : 'is-excluded'}`} key={season.id}>
                <div className="library-season-management-info"><div><strong>Season {String(season.season ?? 1).padStart(2, '0')}</strong>{!season.enabled && <Badge variant="outline">Excluded</Badge>}</div><span>{season.downloaded}/{season.total} on disk · {season.missing} missing</span><code>{season.rel_path}</code></div>
                <div className="library-season-management-actions">
                  <Toggle variant="outline" size="sm" pressed={Boolean(season.season_watched)} aria-label={`Mark ${selectedSeries.title} season ${season.season} watched`} disabled={busy} onPressedChange={(watched) => onSetSeasonWatched(season, watched)}><Check data-icon="inline-start" />{season.season_watched ? 'Watched' : 'Mark watched'}</Toggle>
                  {season.enabled
                    ? <Button variant="destructive" size="sm" disabled={busy} onClick={() => setPendingSeasonRemoval({ entry: season, title: selectedSeries.title })}>Remove folder</Button>
                    : <Button variant="outline" size="sm" disabled={busy} onClick={() => onSetEnabled(season, true)}>Restore folder</Button>}
                </div>
              </article>)}
              {onDiskSeasons.length === 0 && <p className="manager-empty">No season folders are currently in the library.</p>}
              {missingSeasons.length > 0 && <Collapsible className="library-missing-seasons" open={missingSeasonsOpen} onOpenChange={setMissingSeasonsOpen}>
                <CollapsibleTrigger className="library-missing-seasons-trigger"><span>Other known seasons</span><Badge variant="outline">{missingSeasons.length}</Badge><ChevronDown size={16} /></CollapsibleTrigger>
                <CollapsibleContent className="library-missing-seasons-content">
                  {missingSeasons.map((season) => <article className="library-missing-season-row" key={season.season}>
                    <div><strong>Season {String(season.season).padStart(2, '0')}</strong><span>{season.episode_count} released episode(s) · not on disk</span></div>
                    <div className="library-season-management-actions">
                      <Toggle variant="outline" size="sm" pressed={season.watched} aria-label={`Mark ${selectedSeries.title} season ${season.season} watched`} disabled={busy} onPressedChange={(watched) => onSetKnownSeasonWatched(selectedSeries.id, season.season, watched)}><Check data-icon="inline-start" />{season.watched ? 'Watched' : 'Mark watched'}</Toggle>
                      <Button size="sm" disabled={busy} onClick={() => season.entry
                        ? onSetEnabled(season.entry, true)
                        : onAddSeason(selectedSeries.id, season.season)}>Add season</Button>
                    </div>
                  </article>)}
                </CollapsibleContent>
              </Collapsible>}
            </section>
            <section className="library-add-season">
              <div><h2>Add a season</h2><p>Creates the season folder and adds it to the next library scan.</p></div>
              <form onSubmit={(event) => {
                event.preventDefault()
                const season = Number(newSeasonNumber)
                if (!Number.isInteger(season) || season < 0 || season > 999 || busy) return
                onAddSeason(selectedSeries.id, season)
                setNewSeasonNumber('')
              }}>
                <label htmlFor="library-add-season-number">Season number</label>
                <Input id="library-add-season-number" type="number" min="0" max="999" value={newSeasonNumber} onChange={(event) => setNewSeasonNumber(event.target.value)} />
                <Button type="submit" disabled={busy || newSeasonNumber === ''}><Plus data-icon="inline-start" size={15} /> Add season</Button>
              </form>
            </section>
          </div>
        </>}
      </DrawerContent>
    </Drawer>
    <AlertDialog open={pendingSeasonRemoval !== null} onOpenChange={(open) => {
      if (!open) setPendingSeasonRemoval(null)
    }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this season folder?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently deletes {pendingSeasonRemoval?.title} {pendingSeasonRemoval?.entry.season !== undefined ? `Season ${pendingSeasonRemoval.entry.season}` : 'season'} and every file in its folder. The season remains marked removed and its watched state is saved, so automatic scans will not recreate it. Add it back manually from the series drawer if you want to download it again.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={busy} onClick={removePendingSeason}>Delete season folder</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
}
