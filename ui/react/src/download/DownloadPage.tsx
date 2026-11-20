import { useEffect, useRef, useState } from 'react'
import { AlertCircle, ArrowDownToLine, Check, Circle, HardDrive, LoaderCircle, Play, Search, Wifi, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/components/ui/drawer'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { LibraryEntry, LibraryMetadataRow } from '@/library/types'

type DownloadEvent = {
  id: number
  message: string
  title?: string
  type?: string
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
}

type DownloadPageProps = {
  entries: LibraryEntry[]
  events: DownloadEvent[]
  jobOutput: { id: number; message: string; timestamp: string; status?: string; item?: LibraryMetadataRow }[]
  running: boolean
  busy: boolean
  onStart: (job: 'configs' | 'download' | 'download-quick') => void
  onEnable: (entry: LibraryEntry) => void
}

export function DownloadPage({ entries, events, jobOutput, running, busy, onStart, onEnable }: DownloadPageProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState('')
  const [activeTab, setActiveTab] = useState<'queue' | 'completed'>('queue')
  const [logOpen, setLogOpen] = useState(false)
  const [logDismissed, setLogDismissed] = useState(false)
  const logViewport = useRef<HTMLDivElement>(null)
  const queue = entries.filter((entry) => entry.missing > 0)
    .filter((entry) => entry.title.toLowerCase().includes(filter.toLowerCase()))
  const completed = entries.filter((entry) => entry.missing === 0)
  const selected = queue.find((entry) => entry.id === selectedId) ?? queue[0]
  const current = events[0]
  const activeTransfers = events.filter((event) => event.type !== 'episode_done')
  const working = running || busy
  const metadataRows = new Map<string, LibraryMetadataRow>()
  for (const line of jobOutput) {
    if (line.item) metadataRows.set(`${line.item.title}\0${line.item.season}`, line.item)
  }
  const drawerDescription = events.length
    ? `Live transfer progress · ${activeTransfers.length} active download(s). You can close this drawer and the job will continue.`
    : working
      ? `Live library activity · ${metadataRows.size} folder(s) checked so far. You can close this drawer and the job will continue.`
      : `Activity from the most recent job · ${metadataRows.size} folder(s) checked.`
  const recentActivity = jobOutput.filter((line) => !line.item).slice(-10)
  const totalSpeed = activeTransfers.reduce((sum, event) => sum + (event.rate_bps ?? 0), 0)
  const progress = current?.bytes_total && current.bytes_total > 0
    ? Math.min(100, Math.round((current.downloaded ?? 0) / current.bytes_total * 100))
    : 0
  const formatBytes = (bytes: number) => bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
  const transferStatus = (event: DownloadEvent) => {
    if (event.outcome === 'cancelled') return 'Cancelled'
    if (event.type === 'episode_done') return event.success ? 'Complete' : 'Failed'
    if (event.type === 'bytes') return 'Downloading'
    if (event.server_total && event.server_current !== undefined && event.server_current < event.server_total) {
      return `Searching addons · ${event.server_current}/${event.server_total}`
    }
    if (event.live_total && event.live_current !== undefined && event.live_current < event.live_total) {
      return `Resolving streams · ${event.live_current}/${event.live_total}`
    }
    if (event.experimental_total && event.experimental_current !== undefined && event.experimental_current < event.experimental_total) {
      return `Searching extra sources · ${event.experimental_current}/${event.experimental_total}`
    }
    return 'Finding a source'
  }

  useEffect(() => {
    if (logViewport.current) logViewport.current.scrollTop = logViewport.current.scrollHeight
  }, [jobOutput])

  const startJob = (job: 'configs' | 'download' | 'download-quick') => {
    setLogDismissed(false)
    setLogOpen(true)
    onStart(job)
  }

  return <section className="download-page">
    <header className="download-heading">
      <div><p className="download-eyebrow"><ArrowDownToLine size={14} /> DOWNLOAD MANAGER</p><h1>Your library, ready to download.</h1><p>The library is the source of truth for missing episodes and movies.</p></div>
      <div className="download-actions">
        <Button variant="outline" onClick={() => startJob('configs')} disabled={busy || running}>Update library</Button>
        <Button variant="outline" onClick={() => startJob('download-quick')} disabled={busy || running}><Play data-icon="inline-start" size={15} /> Download only</Button>
        <Button className="download-start" onClick={() => startJob('download')} disabled={busy || running}><Play data-icon="inline-start" size={15} />{running ? 'Downloads running' : busy ? 'Starting…' : 'Update & download'}</Button>
      </div>
    </header>
    <div className="download-summary"><div><span className="download-summary-icon is-live"><Wifi size={16} /></span><span><strong>{running ? 'Job running in background' : 'Ready when you are'}</strong><small>{current?.message ?? 'This job keeps running if you leave this page.'}</small></span></div><div><strong>{queue.length}</strong><span>missing library items</span></div><div><strong>{(totalSpeed / 1_000_000).toFixed(1)}<small> MB/s</small></strong><span>live speed</span></div><div><strong>{queue.reduce((sum, item) => sum + item.missing, 0)}</strong><span>episodes left</span></div></div>
    <div className="download-layout">
      <aside className="download-queue-panel">
        <div className="download-panel-heading"><div><h2>Library queue</h2><Badge variant="outline">{queue.length}</Badge></div></div>
        <div className="download-tabs"><button className={activeTab === 'queue' ? 'is-active' : ''} onClick={() => setActiveTab('queue')}>Missing <span>{queue.length}</span></button><button className={activeTab === 'completed' ? 'is-active' : ''} onClick={() => setActiveTab('completed')}>Complete <span>{completed.length}</span></button></div>
        <label className="download-search"><Search size={15} /><Input aria-label="Filter downloads" placeholder="Find in downloads" value={filter} onChange={(event) => setFilter(event.target.value)} /></label>
        <div className="download-queue-list">{(activeTab === 'queue' ? queue : completed).map((item) => <button key={`${item.kind}-${item.id}`} className={`download-queue-item ${selected?.id === item.id && activeTab === 'queue' ? 'is-selected' : ''}`} onClick={() => { setSelectedId(item.id); setActiveTab('queue') }}>
          <span className={`download-queue-status ${running && current?.title === item.title ? 'is-active' : ''}`}>{running && current?.title === item.title ? <ArrowDownToLine size={14} /> : activeTab === 'completed' ? <Check size={14} /> : <Circle size={9} />}</span><span className="download-queue-copy"><strong>{item.title}</strong><small>{item.kind === 'movie' ? 'Movie' : `Season ${String(item.season ?? 1).padStart(2, '0')}`} · {activeTab === 'completed' ? 'Complete' : `${item.missing} episodes remaining`}</small></span><span className="download-queue-trailing">{!item.enabled && activeTab === 'queue' ? <Badge variant="outline">Disabled</Badge> : `${item.downloaded}/${item.total}`}</span>
        </button>)}{(activeTab === 'queue' ? queue : completed).length === 0 && <p className="download-queue-empty">{activeTab === 'queue' ? 'No missing items in the library.' : 'No fully downloaded items yet.'}</p>}</div>
        <div className="queue-footer"><HardDrive size={15} /><span>Library storage</span><strong>{entries.reduce((sum, entry) => sum + entry.downloaded, 0)} files</strong></div>
      </aside>
      <div className="download-detail-column">
        <section className="download-current-panel">
          <div className="download-panel-heading"><div><div className="download-live-label"><i /> {running ? 'CURRENT JOB' : 'DOWNLOAD STATUS'}</div><h2>{current?.title ?? (selected ? selected.title : 'Nothing in the queue')}</h2><p>{current?.message ?? (selected ? `${selected.kind === 'movie' ? 'Movie' : `Season ${selected.season ?? 1}`} · ${selected.missing} episodes waiting` : 'Update your library or start a download job.')}</p></div>{selected && !selected.enabled && <Button variant="outline" size="sm" onClick={() => onEnable(selected)} disabled={busy}>Enable downloads</Button>}</div>
          <div className="download-progress-track"><i style={{ width: `${progress}%` }} /></div><div className="download-transfer-stats"><span><strong>{progress}%</strong> complete</span><span><strong>{current?.rate_bps ? `${(current.rate_bps / 1_000_000).toFixed(1)} MB/s` : '—'}</strong> speed</span><span><strong>{current?.bytes_total ? formatBytes(current.bytes_total) : '—'}</strong> total size</span><span><strong>{current?.downloaded ? formatBytes(current.downloaded) : '—'}</strong> received</span></div>
        </section>
        <section className="download-sources-panel"><div className="download-sources-heading"><div><p className="download-eyebrow"><ArrowDownToLine size={14} /> RUN MODES</p><h2>Start like the terminal</h2><p>Each action runs in the API background, independent of this page.</p></div></div>
          <div className="download-run-modes">
            <article className="download-run-mode"><span className="source-main"><span className="source-title"><strong>0 · Download only</strong><Badge variant="outline">Fast</Badge></span><small>Scan the existing library folders and download missing items without refreshing metadata.</small></span><Button variant="outline" onClick={() => startJob('download-quick')} disabled={busy || running}>Start</Button></article>
            <article className="download-run-mode"><span className="source-main"><span className="source-title"><strong>1 · Update & download</strong><Badge>Recommended</Badge></span><small>Refresh the library and metadata first, then download enabled missing items.</small></span><Button onClick={() => startJob('download')} disabled={busy || running}>Start</Button></article>
            <article className="download-run-mode"><span className="source-main"><span className="source-title"><strong>2 · Update library</strong></span><small>Scan folders and refresh metadata without starting downloads.</small></span><Button variant="outline" onClick={() => startJob('configs')} disabled={busy || running}>Run</Button></article>
          </div>
          <div className="source-note">Jobs continue on the server if you navigate away. Progress and job status return when you come back.</div>
        </section>
      </div>
    </div>
    <Drawer open={logOpen || (running && !logDismissed)} onOpenChange={(open) => {
      setLogOpen(open)
      if (!open) setLogDismissed(true)
    }}>
      <DrawerContent className="download-job-drawer">
        <DrawerHeader className="download-job-header">
          <div><span className={`download-job-indicator ${working ? 'is-running' : ''}`} />
            <DrawerTitle>{working ? 'Job in progress' : 'Job activity'}</DrawerTitle>
            <DrawerDescription>{drawerDescription}</DrawerDescription>
          </div>
          <DrawerClose render={<Button variant="ghost" size="icon" aria-label="Close job output"><X /></Button>} />
        </DrawerHeader>
        <div className="download-job-activity" ref={logViewport} role="log" aria-live="polite" aria-label="Background job activity">
          {jobOutput.length > 0 && <div className="download-job-current"><span className={working ? 'is-working' : ''}>{working ? <LoaderCircle size={19} /> : <Check size={19} />}</span><div><small>{working ? 'CURRENT STEP' : 'LATEST STEP'}</small><strong>{jobOutput.at(-1)?.message}</strong></div></div>}
          {metadataRows.size > 0 && <Table className="download-job-table">
            <TableHeader><TableRow><TableHead>Series</TableHead><TableHead>Season</TableHead><TableHead>Episodes</TableHead><TableHead>IMDb</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>{[...metadataRows].map(([key, item]) => <TableRow key={key}>
              <TableCell className="download-job-cell-title">{item.title}</TableCell>
              <TableCell>{item.season}</TableCell>
              <TableCell>{item.episodes}</TableCell>
              <TableCell>{item.imdb_id}</TableCell>
              <TableCell><Badge variant={item.status === 'Failed' ? 'destructive' : item.status === 'Checking' ? 'outline' : 'secondary'}>{item.status}</Badge></TableCell>
            </TableRow>)}</TableBody>
          </Table>}
          {events.length > 0 && <section className="download-live-transfers" aria-label="Episode download progress">
            <header><strong>Episode transfers</strong><Badge variant="outline">{activeTransfers.length} active</Badge></header>
            <div className="download-live-transfer-list">{events.map((event) => {
              const episode = event.season !== null && event.season !== undefined && event.episode !== null && event.episode !== undefined
                ? `S${String(event.season).padStart(2, '0')}E${String(event.episode).padStart(2, '0')}`
                : 'Movie'
              const percentage = event.bytes_total && event.bytes_total > 0
                ? Math.min(100, Math.round((event.downloaded ?? 0) / event.bytes_total * 100))
                : event.type === 'episode_done' && event.success ? 100 : null
              const transferStatusText = transferStatus(event)
              const failed = transferStatusText === 'Failed' || transferStatusText === 'Cancelled'
              return <article className="download-live-transfer" key={event.id}>
                <div className="download-live-transfer-heading"><strong>{event.title} · {episode}</strong><Badge variant={failed ? 'destructive' : event.type === 'episode_done' ? 'secondary' : 'outline'}>{transferStatusText}</Badge></div>
                <Progress value={percentage} aria-label={`${event.title} ${episode} progress`} className="download-transfer-progress" />
                <div className="download-live-transfer-stats"><span>{percentage === null ? 'Progress sizing' : `${percentage}%`}</span><span>{event.downloaded ? formatBytes(event.downloaded) : 'Waiting for data'}{event.bytes_total ? ` / ${formatBytes(event.bytes_total)}` : ''}</span><span>{event.rate_bps ? `${(event.rate_bps / 1_000_000).toFixed(1)} MB/s` : '—'}</span></div>
              </article>
            })}</div>
          </section>}
          {recentActivity.length > 0
            ? <ol className="download-activity-list">{recentActivity.map((line, index) => {
              const isCurrent = working && index === recentActivity.length - 1
              const isFailed = line.message.startsWith('✗')
              const isComplete = !isCurrent && !isFailed
              return <li className={`download-activity-item ${isCurrent ? 'is-current' : ''} ${isComplete ? 'is-complete' : ''} ${isFailed ? 'is-failed' : ''}`} key={line.id}>
                <span className="download-activity-icon">{isFailed ? <AlertCircle size={16} /> : isCurrent ? <LoaderCircle size={16} /> : isComplete ? <Check size={16} /> : <Circle size={12} />}</span>
                <span className="download-activity-copy"><strong>{line.message}</strong><time>{new Date(line.timestamp).toLocaleTimeString()}</time></span>
              </li>
            })}</ol>
            : !metadataRows.size && !events.length && <div className="download-job-empty">{working && <LoaderCircle className="is-working" size={20} />}<span>{working ? 'Waiting for the first scan or transfer update…' : 'No activity was returned for this job.'}</span></div>}
        </div>
      </DrawerContent>
    </Drawer>
  </section>
}
