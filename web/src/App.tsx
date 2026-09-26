/**
 * Routes (PLAN.md "UI"). Every page is a lazily-loaded module `src/pages/<Name>/index.tsx` with a default export;
 * page agents replace those modules without touching this file.
 */
import { lazy, Suspense } from 'react';
import { createBrowserRouter, Link, RouterProvider } from 'react-router';
import { EmptyState } from '@/components/EmptyState';
import { AppShell } from '@/layout/AppShell';
import { BootScreen } from '@/layout/BootScreen';
import { RequireAuth } from '@/layout/RequireAuth';
import { Compass } from 'lucide-react';

const CommandCenter = lazy(() => import('@/pages/CommandCenter'));
const Pipeline = lazy(() => import('@/pages/Pipeline'));
const MapPage = lazy(() => import('@/pages/MapPage'));
const Detail = lazy(() => import('@/pages/Detail'));
const Activity = lazy(() => import('@/pages/Activity'));
const Inbox = lazy(() => import('@/pages/Inbox'));
const Needs = lazy(() => import('@/pages/Needs'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const Models = lazy(() => import('@/pages/Models'));
const Usage = lazy(() => import('@/pages/Usage'));
const Agents = lazy(() => import('@/pages/Agents'));
const Settings = lazy(() => import('@/pages/Settings'));
const Login = lazy(() => import('@/pages/Login'));

function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Nothing at this address"
      hint="The page you asked for doesn't exist."
      action={
        <Link to="/" className="text-sm font-medium text-cyan-300 hover:text-cyan-200">
          Back to Command Center
        </Link>
      }
    />
  );
}

const router = createBrowserRouter([
  {
    path: '/login',
    element: (
      <Suspense fallback={<BootScreen />}>
        <Login />
      </Suspense>
    ),
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <CommandCenter /> },
      { path: 'pipeline', element: <Pipeline /> },
      { path: 'map', element: <MapPage /> },
      { path: 'o/:id', element: <Detail /> },
      { path: 'activity', element: <Activity /> },
      { path: 'inbox', element: <Inbox /> },
      { path: 'needs', element: <Needs /> },
      { path: 'analytics', element: <Analytics /> },
      { path: 'models', element: <Models /> },
      { path: 'usage', element: <Usage /> },
      { path: 'agents', element: <Agents /> },
      { path: 'settings', element: <Settings /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
