import { useState } from 'react'
import { KeyRound, Save, Settings2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { LibraryLayout } from '@/library/types'

export type SecretName = 'real_debrid' | 'premiumize' | 'alldebrid' | 'hdhub' | 'torrent_proxy'

export type SettingsValues = {
  download_threads: number
  internet_speed_limit: number
  preferred_languages: string[]
  max_download_attempts: number
  configs_cache_hours: number
  library_layout: LibraryLayout
  root_folder: string
  storage_backend: string
  secrets_configured: Record<SecretName, boolean>
}

export type SettingsUpdate = {
  download_threads: number
  internet_speed_limit: number
  preferred_languages: string[]
  max_download_attempts: number
  configs_cache_hours: number
  library_layout?: LibraryLayout
  real_debrid_api_key?: string
  premiumize_api_key?: string
  alldebrid_api_key?: string
  hdhub_debrid_key?: string
  torrent_proxy_url?: string
  clear_secrets: SecretName[]
}

type Props = {
  settings: SettingsValues
  saving: boolean
  savingLayout: boolean
  onSave: (values: SettingsUpdate) => void
  onLayoutChange: (layout: LibraryLayout) => Promise<boolean>
}

export function SettingsPage({ settings, saving, savingLayout, onSave, onLayoutChange }: Props) {
  const [threads, setThreads] = useState(String(settings.download_threads))
  const [speed, setSpeed] = useState(String(settings.internet_speed_limit))
  const [languages, setLanguages] = useState(settings.preferred_languages.join(', '))
  const [attempts, setAttempts] = useState(String(settings.max_download_attempts))
  const [cacheHours, setCacheHours] = useState(String(settings.configs_cache_hours))
  const [layout, setLayout] = useState<LibraryLayout>(settings.library_layout)
  const [secrets, setSecrets] = useState<Partial<Record<SecretName, string>>>({})
  const [clearSecrets, setClearSecrets] = useState<SecretName[]>([])

  const secretFields: { name: SecretName; label: string; placeholder: string }[] = [
    { name: 'real_debrid', label: 'Real-Debrid API key', placeholder: 'Enter a key to set or replace it' },
    { name: 'premiumize', label: 'Premiumize API key', placeholder: 'Enter a key to set or replace it' },
    { name: 'alldebrid', label: 'AllDebrid API key', placeholder: 'Enter a key to set or replace it' },
    { name: 'hdhub', label: 'HDHub / TorBox key', placeholder: 'Enter a key to set or replace it' },
    { name: 'torrent_proxy', label: 'Torrent proxy URL', placeholder: 'http://127.0.0.1:11470' },
  ]

  const submit = () => {
    const update: SettingsUpdate = {
      download_threads: Number(threads),
      internet_speed_limit: Number(speed),
      preferred_languages: languages.split(',').map((value) => value.trim()).filter(Boolean),
      max_download_attempts: Number(attempts),
      configs_cache_hours: Number(cacheHours),
      clear_secrets: clearSecrets,
    }
    if (secrets.real_debrid) update.real_debrid_api_key = secrets.real_debrid
    if (secrets.premiumize) update.premiumize_api_key = secrets.premiumize
    if (secrets.alldebrid) update.alldebrid_api_key = secrets.alldebrid
    if (secrets.hdhub) update.hdhub_debrid_key = secrets.hdhub
    if (secrets.torrent_proxy) update.torrent_proxy_url = secrets.torrent_proxy
    onSave(update)
  }

  return <section className="settings-page">
    <div className="browse-heading"><span className="browse-heading-icon"><Settings2 size={19} /></span><h1>Settings</h1></div>
    <p className="settings-intro">Tune the downloader and manage the services it can use.</p>
    <div className="settings-layout">
      <Card className="settings-card">
        <CardHeader><CardTitle>Download preferences</CardTitle></CardHeader>
        <CardContent className="settings-fields">
          <label><span>Download threads</span><Input type="number" min="1" max="16" value={threads} onChange={(event) => setThreads(event.target.value)} /></label>
          <label><span>Speed limit (%)</span><Input type="number" min="1" max="100" value={speed} onChange={(event) => setSpeed(event.target.value)} /></label>
          <label className="settings-field-wide"><span>Preferred languages</span><Input value={languages} placeholder="english, spanish" onChange={(event) => setLanguages(event.target.value)} /><small>Comma-separated language preferences for new series seasons.</small></label>
          <label><span>Maximum download attempts</span><Input type="number" min="0" max="50" value={attempts} onChange={(event) => setAttempts(event.target.value)} /></label>
          <label><span>Metadata refresh window (hours)</span><Input type="number" min="0" max="168" step="0.5" value={cacheHours} onChange={(event) => setCacheHours(event.target.value)} /></label>
          <div className="settings-field-wide layout-setting"><span>Library Layout {savingLayout && <small>Saving…</small>}</span><ToggleGroup multiple={false} disabled={savingLayout} value={[layout]} onValueChange={(values) => {
            const value = values[0]
            if (value === 'stremio' || value === 'netflix' || value === 'apple-tv' || value === 'plex' || value === 'disney-plus' || value === 'prime-video') {
              setLayout(value)
              void onLayoutChange(value).then((saved) => { if (!saved) setLayout(settings.library_layout) })
            }
          }} variant="outline" aria-label="Default library layout">
            <ToggleGroupItem value="stremio">Stremio</ToggleGroupItem>
            <ToggleGroupItem value="netflix">Netflix</ToggleGroupItem>
            <ToggleGroupItem value="apple-tv">Apple TV</ToggleGroupItem>
            <ToggleGroupItem value="plex">Plex</ToggleGroupItem>
            <ToggleGroupItem value="disney-plus">Disney+</ToggleGroupItem>
            <ToggleGroupItem value="prime-video">Prime Video</ToggleGroupItem>
          </ToggleGroup><small>Selection saves immediately and updates every library view.</small></div>
          <div className="settings-readonly settings-field-wide"><span>Library folder</span><code>{settings.root_folder}</code></div>
          <div className="settings-readonly"><span>Storage</span><Badge variant="outline">{settings.storage_backend}</Badge></div>
          <div className="settings-save settings-field-wide"><Button onClick={submit} disabled={saving}><Save data-icon="inline-start" size={16} />{saving ? 'Saving…' : 'Save preferences'}</Button><small>Preferences are stored in the local catalog and applied to future runs.</small></div>
        </CardContent>
      </Card>

      <Card className="settings-card secrets-card">
        <CardHeader><CardTitle><KeyRound data-icon="inline-start" size={17} /> Debrid & network services</CardTitle></CardHeader>
        <CardContent className="settings-fields">
          {secretFields.map((field) => {
            const isClearing = clearSecrets.includes(field.name)
            const configured = settings.secrets_configured[field.name] && !isClearing
            return <label className="settings-field-wide secret-field" key={field.name}>
              <span>{field.label}<Badge variant={configured ? 'outline' : 'secondary'}>{configured ? 'Configured' : isClearing ? 'Will remove' : 'Not configured'}</Badge></span>
              <div className="secret-input-row">
                <Input
                  type="password"
                  autoComplete="new-password"
                  value={secrets[field.name] ?? ''}
                  placeholder={isClearing ? 'Marked for removal' : configured ? 'Leave blank to keep current value' : field.placeholder}
                  onChange={(event) => {
                    setSecrets((current) => ({ ...current, [field.name]: event.target.value }))
                    setClearSecrets((current) => current.filter((item) => item !== field.name))
                  }}
                />
                {settings.secrets_configured[field.name] && <Button type="button" variant="ghost" size="sm" onClick={() => {
                  setSecrets((current) => ({ ...current, [field.name]: '' }))
                  setClearSecrets((current) => isClearing ? current.filter((item) => item !== field.name) : [...current, field.name])
                }}>{isClearing ? 'Undo' : 'Remove'}</Button>}
              </div>
            </label>
          })}
          <div className="secret-note settings-field-wide">Keys are masked, stored in the owner-only local catalog, and never returned to the page. Environment variables remain supported and take effect when the API starts.</div>
          <div className="settings-save settings-field-wide"><Button variant="outline" onClick={submit} disabled={saving}><Save data-icon="inline-start" size={16} />{saving ? 'Applying…' : 'Apply service settings'}</Button></div>
        </CardContent>
      </Card>
    </div>
  </section>
}
