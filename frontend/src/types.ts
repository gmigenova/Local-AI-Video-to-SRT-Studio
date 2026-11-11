// API types mirroring backend/app/schemas.

export interface Health {
  status: string
  database: string
  worker: string
  gpu: string
}

export interface SystemInfo {
  app_name: string
  cpu: string
  cpu_cores: number | null
  total_ram_gb: number | null
  gpu: {
    name: string | null
    vram_total_mb: number | null
    cuda_available: boolean
    ctranslate2_cuda_devices: number
    note: string | null
  }
  ffmpeg_version: string | null
  models_available: { name: string; profile: string; installed: boolean }[]
  worker: { online: boolean; pid: number | null; busy_job_id: string | null }
}

export interface Project {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface AudioStream {
  stream_index: number
  codec_name: string
  channels: number | null
  sample_rate: number | null
  language: string | null
}

export interface MediaFile {
  id: string
  project_id: string
  original_name: string
  stored_name: string
  file_size: number
  duration_ms: number | null
  video_codec: string | null
  audio_codec: string | null
  width: number | null
  height: number | null
  audio_stream_index: number
  created_at: string
}

export interface UploadResult {
  media_id: string
  filename: string
  duration_ms: number | null
  status: string
  audio_streams: AudioStream[]
}

export type JobStatus =
  | 'queued'
  | 'validating'
  | 'extracting_audio'
  | 'transcribing'
  | 'processing_subtitles'
  | 'completed'
  | 'failed'
  | 'cancelling'
  | 'cancelled'

export const ACTIVE_JOB_STATUSES: JobStatus[] = [
  'queued',
  'validating',
  'extracting_audio',
  'transcribing',
  'processing_subtitles',
  'cancelling',
]

export interface Job {
  job_id: string
  media_id: string
  status: JobStatus
  model_name: string
  language: string | null
  detected_language: string | null
  language_probability: number | null
  progress: number
  current_stage: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface JobList {
  items: Job[]
  total: number
  limit: number
  offset: number
}

export interface Subtitle {
  id: string
  subtitle_index: number
  start_ms: number
  end_ms: number
  text: string
  original_text: string
  is_edited: boolean
  updated_at: string
}

export interface SyncSubtitleItem {
  subtitle_index: number
  start_ms: number
  end_ms: number
  text: string
  original_text: string
  is_edited: boolean
}

// ---- Google Cloud Translation (subtitle translation) ----

export interface TranslateLanguage {
  code: string
  name: string
}

export interface TranslationInfo {
  configured: boolean
  languages: TranslateLanguage[]
}

export type TranslateMode = 'replace' | 'dual'

export interface TranslateRequest {
  target_language: string
  source_language: string | null
  mode: TranslateMode
}

export interface TranslatedTextItem {
  index: number
  text: string
}

/** Cumulative Google Cloud Translation usage for the current month. */
export interface TranslationUsage {
  period: string
  characters_sent: number
  words_sent: number
  texts_translated: number
  requests: number
  jobs: number
  /** 0 = unlimited */
  monthly_char_limit: number
  remaining_chars: number | null
}

export interface TranslateResult {
  job_id: string
  target_language: string
  source_language: string | null
  detected_source_language: string | null
  mode: TranslateMode
  translated: number
  total: number
  subtitles: TranslatedTextItem[]
  usage: TranslationUsage
}

export type RenderStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelling'
  | 'cancelled'

export const ACTIVE_RENDER_STATUSES: RenderStatus[] = [
  'queued',
  'running',
  'cancelling',
]

export interface VideoRender {
  render_id: string
  job_id: string
  status: RenderStatus
  source: 'editor' | 'external'
  progress: number
  current_stage: string | null
  error_message: string | null
  font_name: string | null
  file_size: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TranscriptionSettings {
  beam_size?: number
  best_of?: number
  vad_filter?: boolean
  word_timestamps?: boolean
  condition_on_previous_text?: boolean
  initial_prompt?: string | null
  min_duration?: number
  max_duration?: number
  max_chars_per_line?: number
}

export interface CreateJobRequest {
  media_id: string
  model: string
  language: string | null
  settings: TranscriptionSettings
}
