"use client"

import { useState, useEffect, useCallback } from "react"

// ── Types ─────────────────────────────────────────────────────────────────────

type JobStatus = "NEW" | "VIEWED" | "APPLYING" | "APPLIED" | "REJECTED" | "ARCHIVED"

interface Job {
  id: string
  source: string
  company: string
  title: string
  url: string
  location?: string
  salary_range?: string
  posted_date?: string
  scraped_at: string
  match_score: number
  match_keywords?: string  // JSON string
  status: JobStatus
  notes?: string           // JSON string with Claude ranking
}

interface StatsData {
  total_jobs: number
  new_today: number
  by_source: Record<string, number>
  by_status: Record<string, number>
  avg_match_score: number
  top_companies: { company: string; count: number }[]
  last_run?: {
    run_type: string
    finished_at?: string
    jobs_new: number
    status: string
  }
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_SCOUT_API ?? "http://localhost:8001"

const STATUS_ORDER: JobStatus[] = ["NEW", "VIEWED", "APPLYING", "APPLIED", "REJECTED", "ARCHIVED"]

const STATUS_COLORS: Record<JobStatus, string> = {
  NEW:       "bg-blue-500/20 text-blue-300 border-blue-500/30",
  VIEWED:    "bg-slate-500/20 text-slate-300 border-slate-500/30",
  APPLYING:  "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  APPLIED:   "bg-green-500/20 text-green-300 border-green-500/30",
  REJECTED:  "bg-red-500/20 text-red-300 border-red-500/30",
  ARCHIVED:  "bg-slate-700/30 text-slate-500 border-slate-700/30",
}

const SOURCE_COLORS: Record<string, string> = {
  lever:       "bg-purple-500/20 text-purple-300",
  greenhouse:  "bg-emerald-500/20 text-emerald-300",
  linkedin:    "bg-blue-600/20 text-blue-300",
  indeed:      "bg-orange-500/20 text-orange-300",
  wellfound:   "bg-pink-500/20 text-pink-300",
  career_page: "bg-teal-500/20 text-teal-300",
  web3career:  "bg-violet-500/20 text-violet-300",
}

const SCORE_COLOR = (score: number) => {
  if (score >= 9) return "bg-rose-500/30 text-rose-200 border-rose-500/50"
  if (score >= 7) return "bg-amber-500/30 text-amber-200 border-amber-500/50"
  if (score >= 5) return "bg-emerald-500/30 text-emerald-200 border-emerald-500/50"
  return "bg-slate-500/30 text-slate-300 border-slate-600/50"
}

const SCORE_LABEL = (score: number) => {
  if (score >= 9) return "🔥"
  if (score >= 7) return "⭐"
  if (score >= 5) return "✅"
  return "📋"
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseKeywords(raw?: string): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.slice(0, 6) : []
  } catch {
    return []
  }
}

function parseNotes(raw?: string): { reason?: string; fit_score?: number } | null {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function formatDate(iso?: string): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    })
  } catch {
    return "—"
  }
}

function formatRelative(iso?: string): string {
  if (!iso) return "—"
  const diff = Date.now() - new Date(iso).getTime()
  const h = Math.floor(diff / 3600000)
  if (h < 1) return "< 1h ago"
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

// ── Job Card Component ────────────────────────────────────────────────────────

function JobCard({
  job,
  onStatusChange,
}: {
  job: Job
  onStatusChange: (id: string, status: JobStatus) => void
}) {
  const [updating, setUpdating] = useState(false)
  const keywords = parseKeywords(job.match_keywords)
  const notes = parseNotes(job.notes)
  const nextStatus = STATUS_ORDER[STATUS_ORDER.indexOf(job.status) + 1] as JobStatus | undefined

  const handleStatusAdvance = async () => {
    if (!nextStatus || updating) return
    setUpdating(true)
    try {
      await fetch(`${API_BASE}/jobs/${job.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      })
      onStatusChange(job.id, nextStatus)
    } catch (err) {
      console.error("Status update failed:", err)
    } finally {
      setUpdating(false)
    }
  }

  const optimizerUrl = `/?jd_url=${encodeURIComponent(job.url)}`

  return (
    <div
      className={`
        bg-slate-900 border rounded-lg p-4 transition-all
        ${job.status === "NEW"
          ? "border-blue-500/40 shadow-sm shadow-blue-500/10"
          : "border-slate-800 hover:border-slate-700"
        }
        ${job.status === "ARCHIVED" ? "opacity-50" : ""}
      `}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: core info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            {/* Score badge */}
            <span
              className={`
                inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold
                border ${SCORE_COLOR(job.match_score)}
              `}
            >
              {SCORE_LABEL(job.match_score)} {job.match_score}/10
            </span>

            {/* Source badge */}
            <span
              className={`
                px-2 py-0.5 rounded text-xs font-medium
                ${SOURCE_COLORS[job.source] ?? "bg-slate-700 text-slate-300"}
              `}
            >
              {job.source.replace(/_/g, " ")}
            </span>

            {/* Status badge */}
            <span
              className={`
                px-2 py-0.5 rounded text-xs font-medium border
                ${STATUS_COLORS[job.status]}
              `}
            >
              {job.status}
            </span>
          </div>

          {/* Title + company */}
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-white font-semibold hover:text-blue-300 transition-colors text-sm leading-snug block"
          >
            {job.title} @ <span className="text-blue-400">{job.company}</span>
          </a>

          {/* Meta row */}
          <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
            {job.location && (
              <span>📍 {job.location}</span>
            )}
            {job.salary_range && (
              <span>💰 {job.salary_range}</span>
            )}
            <span>🕐 {formatRelative(job.scraped_at)}</span>
            {job.posted_date && (
              <span>📅 Posted {formatDate(job.posted_date)}</span>
            )}
          </div>

          {/* Claude AI reason (if ranked) */}
          {notes?.reason && (
            <p className="mt-2 text-xs text-slate-400 italic leading-relaxed line-clamp-2">
              🤖 {notes.reason}
            </p>
          )}

          {/* Keywords */}
          {keywords.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {keywords.map((kw) => (
                <span
                  key={kw}
                  className="px-1.5 py-0.5 rounded text-xs bg-slate-800 text-slate-400 border border-slate-700"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Right: actions */}
        <div className="flex flex-col gap-2 shrink-0">
          <a
            href={optimizerUrl}
            className="
              px-3 py-1.5 rounded text-xs font-semibold
              bg-blue-600 hover:bg-blue-500 text-white transition-colors
              whitespace-nowrap text-center
            "
          >
            ✨ Optimize
          </a>

          {nextStatus && nextStatus !== "ARCHIVED" && (
            <button
              onClick={handleStatusAdvance}
              disabled={updating}
              className="
                px-3 py-1.5 rounded text-xs font-medium
                bg-slate-800 hover:bg-slate-700 text-slate-300
                border border-slate-700 transition-colors
                disabled:opacity-50 whitespace-nowrap
              "
            >
              {updating ? "…" : `→ ${nextStatus}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Stats Bar ─────────────────────────────────────────────────────────────────

function StatsBar({ stats, loading }: { stats: StatsData | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-slate-900 border border-slate-800 rounded-lg p-3 animate-pulse">
            <div className="h-6 bg-slate-800 rounded w-12 mb-1" />
            <div className="h-3 bg-slate-800 rounded w-20" />
          </div>
        ))}
      </div>
    )
  }

  if (!stats) return null

  const sourcesActive = Object.keys(stats.by_source ?? {}).length

  const statItems = [
    { label: "Discovered Today", value: stats.new_today, icon: "🆕" },
    { label: "Total in DB", value: stats.total_jobs, icon: "📦" },
    { label: "Sources Active", value: sourcesActive, icon: "🔌" },
    { label: "Avg Score", value: stats.avg_match_score?.toFixed(1) ?? "—", icon: "⭐" },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      {statItems.map((item) => (
        <div
          key={item.label}
          className="bg-slate-900 border border-slate-800 rounded-lg p-3"
        >
          <div className="text-2xl font-bold text-white">
            {item.icon} {item.value}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">{item.label}</div>
        </div>
      ))}
    </div>
  )
}

// ── Filter Bar ────────────────────────────────────────────────────────────────

interface Filters {
  source: string
  minScore: number
  status: string
  search: string
}

function FilterBar({
  filters,
  sources,
  onChange,
}: {
  filters: Filters
  sources: string[]
  onChange: (f: Filters) => void
}) {
  return (
    <div className="flex flex-wrap gap-3 mb-5 p-4 bg-slate-900 border border-slate-800 rounded-lg">
      {/* Search */}
      <input
        type="text"
        placeholder="Search title, company…"
        value={filters.search}
        onChange={(e) => onChange({ ...filters, search: e.target.value })}
        className="
          px-3 py-1.5 rounded text-sm bg-slate-800 border border-slate-700
          text-white placeholder-slate-500 focus:outline-none focus:border-blue-500
          min-w-[180px]
        "
      />

      {/* Source filter */}
      <select
        value={filters.source}
        onChange={(e) => onChange({ ...filters, source: e.target.value })}
        className="px-3 py-1.5 rounded text-sm bg-slate-800 border border-slate-700 text-white"
      >
        <option value="">All Sources</option>
        {sources.map((s) => (
          <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
        ))}
      </select>

      {/* Status filter */}
      <select
        value={filters.status}
        onChange={(e) => onChange({ ...filters, status: e.target.value })}
        className="px-3 py-1.5 rounded text-sm bg-slate-800 border border-slate-700 text-white"
      >
        <option value="">All Statuses</option>
        {STATUS_ORDER.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      {/* Min score */}
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-400 whitespace-nowrap">Min score:</label>
        <select
          value={filters.minScore}
          onChange={(e) => onChange({ ...filters, minScore: Number(e.target.value) })}
          className="px-2 py-1.5 rounded text-sm bg-slate-800 border border-slate-700 text-white"
        >
          {[0, 3, 5, 7, 9].map((v) => (
            <option key={v} value={v}>{v}+</option>
          ))}
        </select>
      </div>

      {/* Clear */}
      {(filters.source || filters.status || filters.minScore > 0 || filters.search) && (
        <button
          onClick={() => onChange({ source: "", status: "NEW", minScore: 0, search: "" })}
          className="px-3 py-1.5 rounded text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
        >
          ✕ Clear
        </button>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<StatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>({
    source: "",
    status: "NEW",
    minScore: 0,
    search: "",
  })
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  // Derive unique sources from loaded jobs
  const sources = [...new Set(jobs.map((j) => j.source))].sort()

  // Fetch stats
  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const r = await fetch(`${API_BASE}/stats`)
      if (r.ok) {
        const data = await r.json()
        setStats(data)
      }
    } catch {
      // Stats are nice-to-have — silently fail
    } finally {
      setStatsLoading(false)
    }
  }, [])

  // Fetch jobs
  const loadJobs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (filters.source) params.set("source", filters.source)
      if (filters.status) params.set("status", filters.status)
      if (filters.minScore > 0) params.set("min_score", String(filters.minScore))
      params.set("limit", "100")

      const r = await fetch(`${API_BASE}/jobs?${params.toString()}`)
      if (!r.ok) throw new Error(`API error ${r.status}`)
      const data: Job[] = await r.json()
      setJobs(data)
      setLastRefresh(new Date())
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error"
      setError(`Could not load jobs: ${msg}. Is the scout API running on port 8001?`)
    } finally {
      setLoading(false)
    }
  }, [filters.source, filters.status, filters.minScore])

  // Initial load
  useEffect(() => {
    loadStats()
    loadJobs()
  }, [loadStats, loadJobs])

  // Status update handler (optimistic)
  const handleStatusChange = useCallback((id: string, status: JobStatus) => {
    setJobs((prev) =>
      prev.map((j) => (j.id === id ? { ...j, status } : j))
    )
  }, [])

  // Client-side search filter
  const filtered = jobs.filter((j) => {
    if (filters.search) {
      const q = filters.search.toLowerCase()
      if (
        !j.title.toLowerCase().includes(q) &&
        !j.company.toLowerCase().includes(q)
      ) return false
    }
    return true
  })

  // Group by status for sorted display
  const newJobs = filtered.filter((j) => j.status === "NEW")
  const otherJobs = filtered.filter((j) => j.status !== "NEW")

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 p-6">
      <div className="mx-auto max-w-5xl">

        {/* ── Header ── */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3">
              <a href="/" className="text-slate-500 hover:text-slate-300 text-sm transition-colors">
                ← Optimizer
              </a>
              <span className="text-slate-700">|</span>
              <h1 className="text-2xl font-bold text-white">🔍 Job Board</h1>
            </div>
            <p className="text-slate-500 text-sm mt-0.5">
              Auto-discovered jobs · Click Optimize to tailor your resume
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="text-xs text-slate-600">
                Refreshed {formatRelative(lastRefresh.toISOString())}
              </span>
            )}
            <button
              onClick={() => { loadJobs(); loadStats() }}
              disabled={loading}
              className="
                px-3 py-1.5 rounded text-sm
                bg-slate-800 hover:bg-slate-700 text-slate-300
                border border-slate-700 transition-colors
                disabled:opacity-50
              "
            >
              {loading ? "⏳" : "↻"} Refresh
            </button>
          </div>
        </div>

        {/* ── Stats Bar ── */}
        <StatsBar stats={stats} loading={statsLoading} />

        {/* ── Filters ── */}
        <FilterBar filters={filters} sources={sources} onChange={setFilters} />

        {/* ── Error State ── */}
        {error && (
          <div className="bg-red-950/50 border border-red-800/50 rounded-lg p-4 mb-5 text-red-300 text-sm">
            ⚠️ {error}
          </div>
        )}

        {/* ── Loading skeleton ── */}
        {loading && (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="bg-slate-900 border border-slate-800 rounded-lg p-4 animate-pulse"
              >
                <div className="flex gap-2 mb-2">
                  <div className="h-5 w-14 bg-slate-800 rounded" />
                  <div className="h-5 w-16 bg-slate-800 rounded" />
                </div>
                <div className="h-4 bg-slate-800 rounded w-3/4 mb-2" />
                <div className="h-3 bg-slate-800 rounded w-1/2" />
              </div>
            ))}
          </div>
        )}

        {/* ── Jobs ── */}
        {!loading && !error && (
          <>
            {/* NEW section */}
            {newJobs.length > 0 && (
              <div className="mb-6">
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
                    New
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-xs bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    {newJobs.length}
                  </span>
                </div>
                <div className="space-y-3">
                  {newJobs.map((job) => (
                    <JobCard key={job.id} job={job} onStatusChange={handleStatusChange} />
                  ))}
                </div>
              </div>
            )}

            {/* Other statuses */}
            {otherJobs.length > 0 && (
              <div>
                {newJobs.length > 0 && (
                  <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
                    In Progress / Archived
                  </h2>
                )}
                <div className="space-y-3">
                  {otherJobs.map((job) => (
                    <JobCard key={job.id} job={job} onStatusChange={handleStatusChange} />
                  ))}
                </div>
              </div>
            )}

            {/* Empty state */}
            {filtered.length === 0 && (
              <div className="text-center py-16">
                <div className="text-4xl mb-3">🔍</div>
                <p className="text-slate-400 font-medium">No jobs found</p>
                <p className="text-slate-600 text-sm mt-1">
                  {jobs.length === 0
                    ? "Run the scout pipeline to discover jobs."
                    : "Try adjusting your filters."}
                </p>
                {jobs.length === 0 && (
                  <code className="block mt-4 text-xs text-slate-600 bg-slate-900 rounded p-3 max-w-sm mx-auto">
                    cd scraper && python run.py --sources lever,greenhouse
                  </code>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
