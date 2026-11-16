import { useMemo } from 'react'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export type CalendarEvent = {
  id: number
  series_id: number
  series_title: string
  season: number
  episode: number
  title: string | null
  overview: string | null
  release_at: string
  thumbnail_url: string | null
  poster_url: string | null
  image_url: string | null
}

export type CalendarData = {
  year: number
  month: number
  events: CalendarEvent[]
  last_refreshed: string | null
  needs_refresh: boolean
}

type Props = {
  month: string
  selectedDate: string
  data: CalendarData | null
  loading: boolean
  refreshing: boolean
  onMonthChange: (month: string) => void
  onSelectDate: (date: string) => void
  onRefresh: () => void
}

export function CalendarPage({ month, selectedDate, data, loading, refreshing, onMonthChange, onSelectDate, onRefresh }: Props) {
  const monthDate = new Date(`${month}-01T00:00:00`)
  const monthTitle = monthDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const cells = useMemo(() => {
    const first = new Date(`${month}-01T00:00:00`)
    const startOffset = (first.getDay() + 6) % 7
    const start = new Date(first)
    start.setDate(first.getDate() - startOffset)
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start)
      date.setDate(start.getDate() + index)
      return {
        date,
        key: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
        inMonth: date.getMonth() === first.getMonth(),
      }
    })
  }, [month])
  const eventsByDate = new Map<string, CalendarEvent[]>()
  for (const event of data?.events ?? []) {
    const day = event.release_at.slice(0, 10)
    eventsByDate.set(day, [...(eventsByDate.get(day) ?? []), event])
  }
  const selectedEvents = eventsByDate.get(selectedDate) ?? []
  const previousMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() - 1, 1)
  const nextMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 1)
  const monthKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`

  return <section className="calendar-page">
    <header className="calendar-heading">
      <div><p className="detail-kicker">YOUR RELEASES</p><h1>Calendar</h1><p>Upcoming episodes across the series in your library.</p></div>
      <div className="calendar-month-controls">
        <Button variant="outline" size="icon" aria-label="Previous month" onClick={() => onMonthChange(monthKey(previousMonth))}><ChevronLeft /></Button>
        <strong>{monthTitle}</strong>
        <Button variant="outline" size="icon" aria-label="Next month" onClick={() => onMonthChange(monthKey(nextMonth))}><ChevronRight /></Button>
        <Button variant="secondary" onClick={onRefresh} disabled={refreshing}>{refreshing ? <RefreshCw className="spin" data-icon="inline-start" /> : <RefreshCw data-icon="inline-start" />}{refreshing ? 'Refreshing…' : 'Refresh calendar'}</Button>
      </div>
    </header>

    {data?.needs_refresh && <p className="calendar-hint">Release dates may be out of date. Refresh to check Cinemeta for recent schedule changes.</p>}
    <div className="calendar-layout">
      <section className="calendar-board" aria-label={`${monthTitle} release dates`}>
        <div className="calendar-weekdays">{['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((day) => <span key={day}>{day}</span>)}</div>
        {loading ? <div className="calendar-skeleton">{Array.from({ length: 35 }, (_, index) => <Skeleton key={index} />)}</div> : <div className="calendar-grid">
          {cells.map(({ date, key, inMonth }) => {
            const events = eventsByDate.get(key) ?? []
            return <Button className={`calendar-day${inMonth ? '' : ' calendar-day--outside'}${selectedDate === key ? ' calendar-day--selected' : ''}`} variant="ghost" key={key} onClick={() => onSelectDate(key)} aria-label={`${date.toLocaleDateString()}, ${events.length} releases`} aria-pressed={selectedDate === key}>
              <span className="calendar-day-number">{date.getDate()}</span>
              <span className="calendar-day-events">{events.slice(0, 3).map((event) => <span className="calendar-day-event" key={event.id} title={`${event.series_title} S${event.season}E${event.episode}`}>
                {event.image_url && <img src={event.image_url} alt="" loading="lazy" onError={(error) => { error.currentTarget.hidden = true }} />}
                <span>{event.series_title}</span>
              </span>)}{events.length > 3 && <small>+{events.length - 3} more</small>}</span>
              {events.length > 0 && <Badge className="calendar-count" variant="secondary">{events.length}</Badge>}
            </Button>
          })}
        </div>}
      </section>

      <aside className="calendar-agenda" aria-label="Releases on selected date">
        <div className="agenda-heading"><span>SELECTED DAY</span><h2>{new Date(`${selectedDate}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</h2></div>
        {selectedEvents.length ? selectedEvents.map((event) => <article className="agenda-event" key={event.id}>
          {event.image_url && <img src={event.image_url} alt="" loading="lazy" onError={(error) => { error.currentTarget.hidden = true }} />}
          <div><Badge variant="outline">S{String(event.season).padStart(2, '0')}E{String(event.episode).padStart(2, '0')}</Badge><h3>{event.title || event.series_title}</h3><p>{event.series_title}</p>{event.overview && <small>{event.overview}</small>}</div>
        </article>) : <div className="agenda-empty"><p>No cataloged episodes on this date.</p>{data?.last_refreshed && <small>Last checked {new Date(data.last_refreshed).toLocaleString()}</small>}</div>}
        {data?.last_refreshed && selectedEvents.length > 0 && <small className="calendar-updated">Calendar checked {new Date(data.last_refreshed).toLocaleDateString()}</small>}
      </aside>
    </div>
  </section>
}
