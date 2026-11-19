import { useState } from 'react'
import { ArrowDownToLine, ArrowDownWideNarrow, Check, Circle, HardDrive, Pause, Play, Search, Settings2, Wifi } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { LibraryEntry } from '@/library/types'

type DownloadPageProps = {
  entries: LibraryEntry[]
  events: { id: number; message: string }[]
  running: boolean
  busy: boolean
  onStart: () => void
}

export function DownloadPage({ entries, events, running, busy, onStart }: DownloadPageProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState('')
  const [activeTab, setActiveTab] = useState<'queue' | 'completed'>('queue')
  const [selectedSource, setSelectedSource] = useState('Automatic · best match')
  const queue = entries.filter((entry) => entry.missing > 0 && entry.enabled)
    .filter((entry) => entry.title.toLowerCase().includes(filter.toLowerCase()))
  const selected = queue.find((entry) => entry.id === selectedId) ?? queue[0]
  const current = events[0]?.message
  const sources = [
    { name: 'Automatic · best match', quality: 'Recommended', size: 'Adaptive', speed: 'Auto', detail: 'Let py-stremio choose the most reliable available source.' },
    { name: 'Torrentio RD', quality: '1080p', size: '4.1 GB', speed: '1.2 MB/s', detail: 'Real-Debrid · cached stream' },
    { name: 'Comet', quality: '1080p', size: '4.4 GB', speed: '980 KB/s', detail: 'Real-Debrid · 42 seeders' },
    { name: 'MediaFusion', quality: '720p', size: '1.8 GB', speed: '504 KB/s', detail: 'WEB · H.264 · 13 seeders' },
  ]

  return <section className="download-page">
    <header className="download-heading">
      <div><p className="download-eyebrow"><ArrowDownToLine size={14} /> DOWNLOAD MANAGER</p><h1>Your downloads, in control.</h1><p>Choose what to queue, compare sources, and keep an eye on every transfer.</p></div>
      <Button className="download-start" onClick={onStart} disabled={busy || running}><Play data-icon="inline-start" size={15} />{running ? 'Downloads running' : busy ? 'Starting…' : 'Start all downloads'}</Button>
    </header>
    <div className="download-summary"><div><span className="download-summary-icon is-live"><Wifi size={16} /></span><span><strong>{running ? 'Downloading now' : 'Ready when you are'}</strong><small>{current ?? 'Your queue is up to date'}</small></span></div><div><strong>{queue.length}</strong><span>in queue</span></div><div><strong>{events.length ? '2.1' : '0'}<small> MB/s</small></strong><span>total speed</span></div><div><strong>{queue.reduce((sum, item) => sum + item.missing, 0)}</strong><span>episodes left</span></div></div>
    <div className="download-layout">
      <aside className="download-queue-panel">
        <div className="download-panel-heading"><div><h2>Downloads</h2><Badge variant="outline">{queue.length}</Badge></div><Button size="icon-sm" variant="ghost" aria-label="Queue settings"><Settings2 size={16} /></Button></div>
        <div className="download-tabs"><button className={activeTab === 'queue' ? 'is-active' : ''} onClick={() => setActiveTab('queue')}>Queue <span>{queue.length}</span></button><button className={activeTab === 'completed' ? 'is-active' : ''} onClick={() => setActiveTab('completed')}>Completed <span>{entries.filter((entry) => entry.missing === 0).length}</span></button></div>
        <label className="download-search"><Search size={15} /><Input aria-label="Filter downloads" placeholder="Find in downloads" value={filter} onChange={(event) => setFilter(event.target.value)} /></label>
        <div className="download-queue-list">{(activeTab === 'queue' ? queue : entries.filter((entry) => entry.missing === 0)).map((item, index) => <button key={`${item.kind}-${item.id}`} className={`download-queue-item ${selected?.id === item.id && activeTab === 'queue' ? 'is-selected' : ''}`} onClick={() => { setSelectedId(item.id); setActiveTab('queue') }}>
          <span className={`download-queue-status ${index === 0 && running && activeTab === 'queue' ? 'is-active' : ''}`}>{index === 0 && running && activeTab === 'queue' ? <ArrowDownToLine size={14} /> : <Circle size={9} />}</span><span className="download-queue-copy"><strong>{item.title}</strong><small>{item.kind === 'movie' ? 'Movie' : `Season ${String(item.season ?? 1).padStart(2, '0')}`} · {activeTab === 'completed' ? 'Completed' : `${item.missing} episodes remaining`}</small>{index === 0 && running && activeTab === 'queue' && <span className="download-mini-progress"><i /></span>}</span><span className="download-queue-trailing">{index === 0 && running && activeTab === 'queue' ? <Pause size={15} /> : <span>{activeTab === 'queue' ? index + 1 : <Check size={14} />}</span>}</span>
        </button>)}{(activeTab === 'queue' ? queue : entries.filter((entry) => entry.missing === 0)).length === 0 && <p className="download-queue-empty">Nothing here yet.</p>}</div>
        <div className="queue-footer"><HardDrive size={15} /><span>Library storage</span><strong>{entries.reduce((sum, entry) => sum + entry.downloaded, 0)} files</strong></div>
      </aside>
      <div className="download-detail-column">
        <section className="download-current-panel">
          <div className="download-panel-heading"><div><div className="download-live-label"><i /> CURRENT DOWNLOAD</div><h2>{current ?? (selected ? selected.title : 'Nothing in the queue')}</h2><p>{current ? 'Live progress from the downloader' : selected ? `${selected.kind === 'movie' ? 'Movie' : `Season ${selected.season ?? 1}`} · ${selected.missing} episodes waiting` : 'Add items from your library to get started.'}</p></div><Button variant="outline" onClick={onStart} disabled={busy || running}>{running ? <><Pause data-icon="inline-start" size={14} /> Running</> : <><Play data-icon="inline-start" size={14} /> Start queue</>}</Button></div>
          <div className="download-progress-track"><i style={{ width: running ? '42%' : '0%' }} /></div><div className="download-transfer-stats"><span><strong>{running ? '42%' : '0%'}</strong> complete</span><span><strong>{running ? '1.2 MB/s' : '—'}</strong> speed</span><span><strong>{running ? '4.1 GB' : '—'}</strong> total size</span><span><strong>{running ? '56 min' : '—'}</strong> time left</span></div>
        </section>
        <section className="download-sources-panel"><div className="download-sources-heading"><div><p className="download-eyebrow"><ArrowDownWideNarrow size={14} /> SOURCE SELECTOR</p><h2>Choose your source</h2><p>Compare quality, size, and speed. Your selection will be used for this download.</p></div><Badge variant="outline">{sources.length} sources</Badge></div>
          <div className="source-list">{sources.map((source, index) => <button key={source.name} className={`source-card ${selectedSource === source.name ? 'is-selected' : ''}`} onClick={() => setSelectedSource(source.name)}><span className="source-radio">{selectedSource === source.name && <i />}</span><span className="source-main"><span className="source-title"><strong>{source.name}</strong>{index === 0 && <Badge>Recommended</Badge>}{index === 1 && <span className="source-cached">● Cached</span>}</span><small>{source.detail}</small></span><span className="source-stat"><strong>{source.quality}</strong><small>QUALITY</small></span><span className="source-stat"><strong>{source.size}</strong><small>SIZE</small></span><span className="source-stat"><strong>{source.speed}</strong><small>SPEED</small></span><span className="source-action">{selectedSource === source.name ? <Check size={17} /> : <Play size={16} />}</span></button>)}</div>
          <div className="source-note">Source results are shown as a preview. The downloader currently chooses sources automatically when a job runs.</div>
        </section>
      </div>
    </div>
  </section>
}
