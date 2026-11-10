// TanStack Query hooks wrapping the API client.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, uploadMedia } from './client'
import { ACTIVE_JOB_STATUSES, type CreateJobRequest } from '../types'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })
}

export function useSystemInfo() {
  return useQuery({ queryKey: ['system'], queryFn: api.systemInfo, staleTime: 60_000 })
}

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
}

export function useCreateProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      api.createProject(name, description),
    onSuccess: () => client.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: ['project', id],
    queryFn: () => api.getProject(id!),
    enabled: Boolean(id),
  })
}

export function useMedia(projectId: string | undefined) {
  return useQuery({
    queryKey: ['media', projectId],
    queryFn: () => api.listMedia(projectId!),
    enabled: Boolean(projectId),
  })
}

export function useMediaItem(mediaId: string | undefined) {
  return useQuery({
    queryKey: ['media-item', mediaId],
    queryFn: () => api.getMedia(mediaId!),
    enabled: Boolean(mediaId),
  })
}

export function useMediaStreams(mediaId: string | undefined) {
  return useQuery({
    queryKey: ['media-streams', mediaId],
    queryFn: () => api.mediaStreams(mediaId!),
    enabled: Boolean(mediaId),
  })
}

export function useSelectAudioStream() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ mediaId, streamIndex }: { mediaId: string; streamIndex: number }) =>
      api.selectAudioStream(mediaId, streamIndex),
    onSuccess: (media) => {
      client.invalidateQueries({ queryKey: ['media', media.project_id] })
    },
  })
}

/** Job polling: fast while active (§11.4), stops on terminal states. */
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ACTIVE_JOB_STATUSES.includes(status) ? 1_500 : false
    },
  })
}

export function useJobs(limit = 100) {
  return useQuery({
    queryKey: ['jobs', limit],
    queryFn: () => api.listJobs({ limit }),
  })
}

export function useCreateJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateJobRequest) => api.createJob(payload),
    onSuccess: () => client.invalidateQueries({ queryKey: ['jobs'] }),
  })
}

export function useCancelJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: (data) => client.invalidateQueries({ queryKey: ['job', data.job_id] }),
  })
}

export function useRetryJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.retryJob(jobId),
    onSuccess: (job) => client.invalidateQueries({ queryKey: ['job', job.job_id] }),
  })
}

export function useSubtitles(jobId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['subtitles', jobId],
    queryFn: () => api.listSubtitles(jobId!),
    enabled: Boolean(jobId) && enabled,
  })
}

export function useUpload() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      file,
      projectId,
      onProgress,
    }: {
      file: File
      projectId: string
      onProgress: (fraction: number) => void
    }) => uploadMedia(file, projectId, onProgress),
    onSuccess: (_data, variables) =>
      client.invalidateQueries({ queryKey: ['media', variables.projectId] }),
  })
}
