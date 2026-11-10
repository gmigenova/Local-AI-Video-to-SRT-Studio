import { Navigate, Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import DashboardPage from './features/dashboard/DashboardPage'
import ProjectsPage from './features/projects/ProjectsPage'
import ProjectDetailPage from './features/projects/ProjectDetailPage'
import UploadPage from './features/uploads/UploadPage'
import ProcessingPage from './features/transcription/ProcessingPage'
import SubtitleEditorPage from './features/subtitle-editor/SubtitleEditorPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="projects/:projectId/upload" element={<UploadPage />} />
        <Route path="jobs/:jobId" element={<SubtitleEditorPage />} />
        <Route path="jobs/:jobId/processing" element={<ProcessingPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
