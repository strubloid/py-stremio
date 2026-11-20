import { Fragment, useState } from 'react'
import { FolderOpen, Search } from 'lucide-react'
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
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { LibraryEntry, SeriesSummary } from './types'

type Props = {
  series: SeriesSummary[]
  movies: LibraryEntry[]
  busy: boolean
  onOpenSeries: (id: number) => void
  onOpenMovie: (movie: LibraryEntry) => void
  onSetEnabled: (entry: LibraryEntry, enabled: boolean) => void
  onRemoveSeason: (entry: LibraryEntry) => void
}

export function LibraryManager({ series, movies, busy, onOpenSeries, onOpenMovie, onSetEnabled, onRemoveSeason }: Props) {
  const [view, setView] = useState<'active' | 'excluded'>('active')
  const [query, setQuery] = useState('')
  const [pendingSeasonRemoval, setPendingSeasonRemoval] = useState<{ entry: LibraryEntry; title: string } | null>(null)
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
      <p>Remove a season to delete its folder and files. Films can be excluded without deleting their files.</p>
    </div>
    <div className="library-table-wrap">
      <Table className="library-data-table">
        <TableHeader><TableRow>
          <TableHead>Title / Season</TableHead><TableHead>On disk</TableHead><TableHead>Missing</TableHead><TableHead>Folder</TableHead><TableHead><span className="sr-only">Actions</span></TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {visibleSeries.map((item) => <Fragment key={`series-group-${item.id}`}>
            <TableRow className="library-series-heading" key={`series-${item.id}`}>
              <TableCell colSpan={5}><Button className="library-table-title" variant="link" onClick={() => onOpenSeries(item.id)}>{item.title}</Button><span>{item.seasons.length} {item.seasons.length === 1 ? 'season' : 'seasons'} · {item.missing} missing episodes</span></TableCell>
            </TableRow>
            {item.seasons.map((season) => <TableRow key={`season-${season.id}`}>
              <TableCell><div className="library-season-indent"><Badge variant="secondary">Season {String(season.season ?? 1).padStart(2, '0')}</Badge></div></TableCell>
              <TableCell>{season.downloaded}/{season.total}</TableCell>
              <TableCell>{season.missing > 0 ? <Badge variant="outline">{season.missing}</Badge> : <Badge variant="secondary">Complete</Badge>}</TableCell>
              <TableCell className="library-table-path">{season.rel_path}</TableCell>
              <TableCell>{view === 'active'
                ? <Button variant="destructive" size="sm" disabled={busy} onClick={() => setPendingSeasonRemoval({ entry: season, title: item.title })}>Remove season</Button>
                : <Button variant="outline" size="sm" disabled={busy} onClick={() => onSetEnabled(season, true)}>Restore</Button>}</TableCell>
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
    <AlertDialog open={pendingSeasonRemoval !== null} onOpenChange={(open) => {
      if (!open) setPendingSeasonRemoval(null)
    }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this season folder?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently deletes {pendingSeasonRemoval?.title} {pendingSeasonRemoval?.entry.season !== undefined ? `Season ${pendingSeasonRemoval.entry.season}` : 'season'} and all files inside its folder. This cannot be undone.
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
