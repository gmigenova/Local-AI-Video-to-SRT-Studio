// Thin fetch/XHR client for the backend REST API.
// Requests go through the Vite dev proxy (/api -> 127.0.0.1:8000).

import type {
  CreateJobRequest,
  Health,
  Job,
  JobList,
  MediaFile,
  AudioStream,
  Project,
  Subtitle,
  SyncSubtitleItem,
  SystemInfo,
  UploadResult,
  VideoRender,
} from '../types'

const BASE = '/api/v1'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* keep default */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function mediaStreamUrl(mediaId: string): string {
  return `${BASE}/media/${mediaId}/stream`
}

export function exportUrl(jobId: string, format: string): string {
  return `${BASE}/jobs/${jobId}/export/${format}`
}

export function renderDownloadUrl(renderId: string): string {
  return `${BASE}/renders/${renderId}/download`
}

export const api = {
  health: () => request<Health>('/health'),
  systemInfo: () => request<SystemInfo>('/system/info'),

  // projects
  listProjects: () => request<Project[]>('/projects'),
  createProject: (name: string, description?: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: 'DELETE' }),

  // media
  listMedia: (projectId: string) =>
    request<MediaFile[]>(`/media?project_id=${encodeURIComponent(projectId)}`),
  getMedia: (id: string) => request<MediaFile>(`/media/${id}`),
  mediaStreams: (id: string) => request<AudioStream[]>(`/media/${id}/streams`),
  selectAudioStream: (id: string, streamIndex: number) =>
    request<MediaFile>(`/media/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ stream_index: streamIndex }),
    }),

  // jobs
  createJob: (payload: CreateJobRequest) =>
    request<{ job_id: string; status: string }>('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  listJobs: (params: { status?: string; media_id?: string; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.status) query.set('status', params.status)
    if (params.media_id) query.set('media_id', params.media_id)
    query.set('limit', String(params.limit ?? 50))
    return request<JobList>(`/jobs?${query.toString()}`)
  },
  cancelJob: (id: string) =>
    request<{ job_id: string; status: string }>(`/jobs/${id}/cancel`, {
      method: 'POST',
    }),
  retryJob: (id: string) =>
    request<Job>(`/jobs/${id}/retry`, { method: 'POST' }),

  // subtitles
  listSubtitles: (jobId: string) => request<Subtitle[]>(`/jobs/${jobId}/subtitles`),
  syncSubtitles: (jobId: string, subtitles: SyncSubtitleItem[]) =>
    request<{ job_id: string; saved: number }>(`/jobs/${jobId}/subtitles/sync`, {
      method: 'POST',
      body: JSON.stringify({ subtitles }),
    }),
  updateSubtitle: (
    jobId: string,
    subtitleId: string,
    body: { start_ms?: number; end_ms?: number; text?: string },
  ) =>
    request<Subtitle>(`/jobs/${jobId}/subtitles/${subtitleId}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  reprocessSubtitles: (jobId: string) =>
    request<{ job_id: string; subtitles: number; warnings: number }>(
      `/jobs/${jobId}/subtitles/reprocess`,
      { method: 'POST' },
    ),

  // video render (subtitle burn-in)
  startRender: (jobId: string, fontName?: string) =>
    request<{ render_id: string; status: string }>(`/jobs/${jobId}/render`, {
      method: 'POST',
      body: JSON.stringify(fontName ? { font_name: fontName } : {}),
    }),
  getLatestRender: (jobId: string) =>
    request<VideoRender>(`/jobs/${jobId}/render`),
  cancelRender: (renderId: string) =>
    request<{ render_id: string; status: string }>(`/renders/${renderId}/cancel`, {
      method: 'POST',
    }),
}

/// Upload with progress (fetch cannot report upload progress; use XHR).
export function uploadMedia(
  file: File,
  projectId: string,
  onProgress: (fraction: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    form.append('project_id', projectId)
    form.append('audio_stream_index', '0')

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/media/upload`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadResult)
      } else {
        let detail = `Upload failed (${xhr.status})`
        try {
          detail = (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? detail
        } catch {
          /* keep default */
        }
        reject(new ApiError(xhr.status, detail))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error during upload.'))
    xhr.send(form)
  })
}
