// Application route tree. BrowserRouter basename matches the SPA's mount point (/app), so a
// route like "/dashboard" resolves to /app/dashboard with clean, enterprise-standard URLs
// (no hash). The backend serves index.html for unknown /app/* paths so these deep links
// survive a hard reload. Heavy/privileged areas are lazy-loaded behind a Suspense boundary.
import { lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from '../layout/AppLayout';
import { ScribeWorkspace } from '../routes/ScribeWorkspace';
import { ProtectedRoute } from './ProtectedRoute';
import {
  TemplatesPage,
  TemplateBuilderPage,
  PatientsPage,
  ReportsPage,
  SettingsPage,
  ProfilePage,
  NotFound,
} from '../routes/Pages';

const AdminRoute = lazy(() => import('../routes/AdminRoute'));

export function AppRouter() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<ScribeWorkspace />} />

          <Route path="templates" element={<TemplatesPage />} />
          <Route path="templates/new" element={<TemplateBuilderPage />} />
          <Route path="templates/:id" element={<TemplateBuilderPage />} />

          <Route path="patients" element={<PatientsPage />} />
          <Route path="patients/:id" element={<PatientsPage />} />

          <Route path="reports" element={<ReportsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="profile" element={<ProfilePage />} />

          <Route path="admin/*" element={<ProtectedRoute role="admin"><AdminRoute /></ProtectedRoute>} />

          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
