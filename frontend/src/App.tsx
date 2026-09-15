import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

type Stage = 'transcribe' | 'score' | 'cut' | 'montage' | 'done' | null

interface Health {
  ffmpeg: boolean
  ollama: { connected: boolean; model: string; models: string[] }
  whisper_model: string
}

interface JobClip {
  id: number | string
  title: string
  start?: number | null
  end?: number | null
  duration?: number | null
  score?: number | null
  reason?: string
  file: string
  thumb: string | null
}

interface JobResult {
  clips: JobClip[]
  montage: { file: string; duration: number | null; clip_count: number }
}

interface JobStatus {
  status: 'uploaded' | 'ready' | 'download' | 'processing' | 'completed' | 'error' | 'cancelled'
  id?: string
  stage: Stage
  progress: number
  stage_detail?: string
  error: string | null
  result: JobResult | null
  created_at?: string
}

const STAGE_LABEL: Record<string, string> = {
  download: 'Скачиваю с YouTube…',
  transcribe: 'Распознаю речь (Whisper)…',
  score: 'Ищу интересные моменты…',
  cut: 'Режу клипы…',
  montage: 'Собираю монтаж…',
  done: 'Готово',
}

interface Preset {
  id: string
  label: string
  hint: string
  values: {
    aspect: string
    min_score: number
    max_clips: number
    clip_min_sec: number
    clip_max_sec: number
  }
}

const PRESETS: Preset[] = [
  {
    id: 'reels',
    label: 'Reels',
    hint: 'блюр · 6 кл. · до 90 с',
    values: { aspect: '9_16_blur', min_score: 70, max_clips: 6, clip_min_sec: 8, clip_max_sec: 90 },
  },
  {
    id: 'tiktok',
    label: 'TikTok',
    hint: 'обрезка · 8 кл. · до 60 с',
    values: { aspect: '9_16_crop', min_score: 60, max_clips: 8, clip_min_sec: 7, clip_max_sec: 60 },
  },
  {
    id: 'shorts',
    label: 'Shorts',
    hint: 'блюр · 4 кл. · до 45 с',
    values: { aspect: '9_16_blur', min_score: 75, max_clips: 4, clip_min_sec: 8, clip_max_sec: 45 },
  },
]

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [history, setHistory] = useState<JobStatus[]>([])
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)

  const [minScore, setMinScore] = useState(70)
  const [maxClips, setMaxClips] = useState(6)
  const [clipMinSec, setClipMinSec] = useState(8)
  const [clipMaxSec, setClipMaxSec] = useState(90)
  const [burnSubtitles, setBurnSubtitles] = useState(true)
  const [aspect, setAspect] = useState<string>('9_16_blur')
  const [language, setLanguage] = useState<string>('ru')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [reprocessJob, setReprocessJob] = useState<string | null>(null)
  const [retranscribe, setRetranscribe] = useState(false)

  const fileInput = useRef<HTMLInputElement>(null)
  const esRef = useRef<EventSource | null>(null)

  const loadHistory = useCallback(() => {
    fetch('/api/jobs')
      .then((r) => r.json())
      .then((j: { jobs: JobStatus[] }) => setHistory(j.jobs.filter((x) => x.status === 'completed')))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null))
    loadHistory()
  }, [loadHistory])

  const startStreaming = useCallback(
    (id: string) => {
      setActiveJobId(id)
      esRef.current?.close()
      const es = new EventSource(`/api/jobs/${id}/stream`)
      esRef.current = es
      const finish = () => {
        es.close()
        esRef.current = null
        loadHistory()
      }
      es.onmessage = (e) => {
        try {
          const s: JobStatus = JSON.parse(e.data)
          setStatus(s)
          if (s.status === 'completed' || s.status === 'error') finish()
        } catch {}
      }
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) esRef.current = null
      }
      es.addEventListener('done', (e) => {
        try {
          const s: JobStatus = JSON.parse((e as MessageEvent<string>).data)
          setStatus(s)
        } catch {}
        finish()
      })
      es.addEventListener('gone', () => {
        setStatus(null)
        finish()
      })
    },
    [loadHistory],
  )

  useEffect(() => () => esRef.current?.close(), [])

  const onFile = (f: File | undefined | null) => {
    if (f && /\.(mp4|mov|mkv|avi|webm|m4v|ts)$/i.test(f.name)) {
      setFile(f)
      setYoutubeUrl('')
      setReprocessJob(null)
      setStatus(null)
    }
  }

  const buildOptions = () => ({
    min_score: minScore,
    max_clips: maxClips,
    clip_min_sec: clipMinSec,
    clip_max_sec: clipMaxSec,
    burn_subtitles: burnSubtitles,
    aspect,
    language,
  })

  const activePreset =
    PRESETS.find(
      (p) =>
        p.values.aspect === aspect &&
        p.values.min_score === minScore &&
        p.values.max_clips === maxClips &&
        p.values.clip_min_sec === clipMinSec &&
        p.values.clip_max_sec === clipMaxSec,
    )?.id ?? null

  const applyPreset = (p: Preset) => {
    setMinScore(p.values.min_score)
    setMaxClips(p.values.max_clips)
    setAspect(p.values.aspect)
    setClipMinSec(p.values.clip_min_sec)
    setClipMaxSec(p.values.clip_max_sec)
  }

  const submit = async () => {
    if (reprocessJob) {
      setUploading(true)
      setStatus({ status: 'processing', stage: 'score', progress: 30, error: null, result: null })
      try {
        const proc = await fetch(`/api/process/${reprocessJob}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...buildOptions(), reuse_transcript: !retranscribe }),
        })
        if (!proc.ok) throw new Error(await proc.text())
        startStreaming(reprocessJob)
      } catch (e) {
        setStatus({ status: 'error', stage: null, progress: 0, error: String(e), result: null })
      } finally {
        setUploading(false)
      }
      return
    }
    if (!file && !youtubeUrl.trim()) return
    setUploading(true)
    setStatus({ status: 'uploaded', stage: null, progress: 0, error: null, result: null })
    try {
      let job_id: string
      if (youtubeUrl.trim()) {
        const dl = await fetch('/api/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: youtubeUrl.trim(), options: buildOptions() }),
        })
        if (!dl.ok) throw new Error(await dl.text())
        job_id = (await dl.json()).id
      } else if (file) {
        const fd = new FormData()
        fd.append('file', file)
        const up = await fetch('/api/upload', { method: 'POST', body: fd })
        if (!up.ok) throw new Error(await up.text())
        job_id = (await up.json()).job_id
        const proc = await fetch(`/api/process/${job_id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildOptions()),
        })
        if (!proc.ok) throw new Error(await proc.text())
      } else {
        return
      }
      startStreaming(job_id)
    } catch (e) {
      setStatus({ status: 'error', stage: null, progress: 0, error: String(e), result: null })
    } finally {
      setUploading(false)
    }
  }

  const busy = status?.status === 'processing' || status?.status === 'download' || uploading
  const done = status?.status === 'completed'
  const failed = status?.status === 'error'
  const cancelled = status?.status === 'cancelled'

  const cancelJob = async () => {
    if (!activeJobId) return
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, { method: 'POST' })
    } catch {
      /* SSE сообщит о фактическом состоянии */
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>AutoCut</h1>
        <p>Закинь видео — получи нарезку самых интересных моментов с субтитрами.</p>
        <div className="health">
          <span className={health?.ffmpeg ? 'ok' : 'bad'}>ffmpeg</span>
          <span className={health?.ollama.connected ? 'ok' : 'bad'}>Ollama·{health?.whisper_model}</span>
          {health?.ollama.connected && <em>{health.ollama.model}</em>}
        </div>
      </header>

      <main>
        {!done && (
          <section className="card uploader">
            {!reprocessJob ? (
              <>
                <input
                  className="url-input"
                  type="text"
                  placeholder="Или вставь ссылку на YouTube (скачается и нарежется)"
                  value={youtubeUrl}
                  disabled={busy}
                  onChange={(e) => {
                    setYoutubeUrl(e.target.value)
                    if (e.target.value.trim() && file) setFile(null)
                  }}
                />
                <div className="dropzone-sep">или</div>
              </>
            ) : (
              <div className="reprocess-note">
                Пере-нарезка готового видео <b>без повторного распознавания речи</b>.
                Измени настройки и нажми «Пере-нарезать».
                <label className="check" style={{ marginTop: 8 }}>
                  <input
                    type="checkbox"
                    checked={retranscribe}
                    disabled={busy}
                    onChange={(e) => setRetranscribe(e.target.checked)}
                  />
                  Пере-распознать речь заново (сменит язык субтитров)
                </label>
              </div>
            )}
            {!reprocessJob && (
            <div
              className={`dropzone${dragging ? ' active' : ''}`}
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                onFile(e.dataTransfer.files[0])
              }}
            >
              <input
                ref={fileInput}
                type="file"
                accept="video/*,.mp4,.mov,.mkv,.avi,.webm,.m4v,.ts"
                hidden
                onChange={(e) => onFile(e.target.files?.[0])}
              />
              {file ? (
                <div className="file-chosen">
                  <strong>{file.name}</strong>
                  <span>{(file.size / 1024 / 1024).toFixed(1)} МБ · нажми, чтобы заменить</span>
                </div>
              ) : (
                <>
                  <strong>Перетащи видео сюда</strong>
                  <span>или кликни, чтобы выбрать файл</span>
                </>
              )}
            </div>
          )}

            <div className="presets">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  className={`preset${activePreset === p.id ? ' active' : ''}`}
                  disabled={busy}
                  onClick={() => applyPreset(p)}
                >
                  <b>{p.label}</b>
                  <span>{p.hint}</span>
                </button>
              ))}
              <button
                className={`preset${!activePreset ? ' active' : ''}`}
                disabled={busy}
                onClick={() => {}}>
                <b>Своё</b>
                <span>ручные настройки</span>
              </button>
            </div>

            <div className="settings">
              <label>
                Порог «интересности»: <b>{minScore}</b>
                <input
                  type="range"
                  min={30}
                  max={95}
                  value={minScore}
                  disabled={busy}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                />
              </label>
              <label>
                Максимум клипов: <b>{maxClips}</b>
                <input
                  type="range"
                  min={1}
                  max={12}
                  value={maxClips}
                  disabled={busy}
                  onChange={(e) => setMaxClips(Number(e.target.value))}
                />
              </label>
              <label>
                Мин. длина клипа: <b>{clipMinSec} с</b>
                <input
                  type="range"
                  min={4}
                  max={20}
                  value={clipMinSec}
                  disabled={busy}
                  onChange={(e) => setClipMinSec(Number(e.target.value))}
                />
              </label>
              <label>
                Макс. длина клипа: <b>{clipMaxSec} с</b>
                <input
                  type="range"
                  min={20}
                  max={180}
                  step={5}
                  value={clipMaxSec}
                  disabled={busy}
                  onChange={(e) => setClipMaxSec(Number(e.target.value))}
                />
              </label>
              <label>
                Формат клипов:
                <select value={aspect} disabled={busy} onChange={(e) => setAspect(e.target.value)}>
                  <option value="9_16_blur">Вертикальный 9:16 · блюр-фон (Shorts/Reels)</option>
                  <option value="9_16_crop">Вертикальный 9:16 · обрезка</option>
                  <option value="original">Исходный формат</option>
                </select>
              </label>
              <label>
                Язык субтитров:
                <select value={language} disabled={busy} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="ru">Русский</option>
                  <option value="auto">Авто</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={burnSubtitles}
                  disabled={busy}
                  onChange={(e) => setBurnSubtitles(e.target.checked)}
                />
                Сжечь субтитры в кадр
              </label>
            </div>

            <button
              className="primary"
              disabled={(!file && !youtubeUrl.trim() && !reprocessJob) || busy}
              onClick={submit}
            >
              {uploading
                ? 'Загружаю…'
                : busy
                  ? 'Обрабатываю…'
                  : reprocessJob
                    ? 'Пере-нарезать'
                    : 'Нарезать'}
            </button>

            {busy && status && (
              <div className="progress">
                <div className="bar" style={{ width: `${status.progress}%` }} />
                <span>
                  {STAGE_LABEL[status.stage ?? ''] ?? 'Подготовка'} · {status.progress}%
                </span>
              </div>
            )}
            {busy && status?.stage_detail && (
              <div className="progress-detail">{status.stage_detail}</div>
            )}
            {busy && (
              <div className="progress-actions">
                <button className="cancel" onClick={cancelJob} disabled={uploading}>
                  Отменить обработку
                </button>
              </div>
            )}
            {cancelled && (
              <div className="error note">
                Обработка отменена. Можно запустить заново.
                <button onClick={() => setStatus(null)}>ОК</button>
              </div>
            )}
            {failed && (
              <div className="error">
                <b>Не получилось:</b> {status?.error}
                <button onClick={() => setStatus(null)}>Попробовать снова</button>
              </div>
            )}
            {health && !health.ffmpeg && !busy && (
              <div className="error hint">ffmpeg не найден. Установи ffmpeg или добавь его в PATH.</div>
            )}
            {health && !health.ollama.connected && !busy && (
              <div className="error hint">
                Ollama не отвечает. Запусти <code>ollama serve</code> и&nbsp;
                <code>ollama pull qwen2.5:7b-instruct</code>.
              </div>
            )}
          </section>
        )}

        {done && status?.result && (
          <>
            <section className="card montage">
              <h2>
                Полный монтаж · {status.result.montage.clip_count} клипов ·{' '}
                {status.result.montage.duration ? `${status.result.montage.duration.toFixed(1)} с` : ''}
              </h2>
              <video controls src={status.result.montage.file} />
              <div className="result-actions">
                <a className="download" href={status.result.montage.file} download>
                  Скачать highlights.mp4
                </a>
                <button
                  className="ghost"
                  onClick={() => {
                    if (!activeJobId && status.id) setActiveJobId(status.id)
                    setReprocessJob(activeJobId || status.id || '')
                    setStatus(null)
                  }}
                >
                  Пере-нарезать с другими настройками
                </button>
              </div>
            </section>

            <section className="clips">
              {status.result.clips.map((c) => (
                <div className="card clip" key={c.id}>
                  <div className="clip-head">
                    {c.score != null && <span className="score">{c.score}</span>}
                    <div>
                      <h3>{c.title}</h3>
                      <p>{c.reason}</p>
                    </div>
                  </div>
                  <video controls preload="none" poster={c.thumb ?? undefined} src={c.file} />
                  <div className="clip-meta">
                    {c.duration != null && <span>⏱ {c.duration.toFixed(1)} с</span>}
                    {c.start != null && c.end != null && (
                      <span>
                        📍 {fmtTs(c.start)} – {fmtTs(c.end)}
                      </span>
                    )}
                    <a href={c.file} download>
                      Скачать
                    </a>
                  </div>
                </div>
              ))}
            </section>
          </>
        )}
      {history.length > 0 && !busy && (
          <section className="card history">
            <h2>Недавние нарезки</h2>
            <div className="history-list">
              {history.map((h) => (
                <button
                  key={h.created_at ?? h.id ?? String(Math.random())}
                  className="history-item"
                  onClick={() => {
                    setStatus(h)
                    setActiveJobId(h.id ?? null)
                    setReprocessJob(null)
                  }}
                >
                  {h.result?.clips[0]?.thumb ? (
                    <img className="history-thumb" src={h.result.clips[0].thumb} alt="" loading="lazy" />
                  ) : (
                    <span className="history-thumb empty" />
                  )}
                  <span className="history-count">{h.result?.montage.clip_count ?? 0} клипов</span>
                  <span className="history-dur">
                    {h.result?.montage.duration ? `${h.result.montage.duration.toFixed(0)} с` : ''}
                  </span>
                  <span className="history-hint">открыть →</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

function fmtTs(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default App