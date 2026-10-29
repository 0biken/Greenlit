import { createBrowserRouter, Navigate, useRouteError } from 'react-router'
import { ErrorState } from '../design/states'
import { EnrolTotp, RequestReset, ResetPassword, SignIn, SignUp, TwoStep, VerifyEmail } from '../features/auth/AuthPages'
import { InboxPage } from '../features/inbox/InboxPage'
import { AcceptInvite, Welcome } from '../features/orgs/OrgPages'
import { NotFound } from '../features/NotFound'
import { ProjectHome } from '../features/projects/ProjectHome'
import { ProjectsList } from '../features/projects/ProjectsList'
import { ReleasePage } from '../features/releases/ReleasePage'
import { RequirementsPage } from '../features/requirements/RequirementsPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { AppShell } from './AppShell'
import { Gate, SignedInOnly } from './Gate'

function RouteError() {
  const error = useRouteError()
  console.error(error)
  return <ErrorState message="Something went wrong on this screen. Reload to try again." onRetry={() => window.location.reload()} />
}

// URLs use display IDs and project keys: /hube, /hube/releases/2.4.1 (DATA §4).
export const router = createBrowserRouter([
  { path: '/sign-in', element: <SignIn /> },
  { path: '/sign-up', element: <SignUp /> },
  { path: '/two-step', element: <TwoStep /> },
  { path: '/verify-email/:key', element: <VerifyEmail /> },
  { path: '/reset-password', element: <RequestReset /> },
  { path: '/reset-password/:key', element: <ResetPassword /> },
  { path: '/two-step/setup', element: <SignedInOnly><EnrolTotp /></SignedInOnly> },
  { path: '/welcome', element: <SignedInOnly><Welcome /></SignedInOnly> },
  { path: '/invite/:token', element: <SignedInOnly><AcceptInvite /></SignedInOnly> },
  {
    element: (
      <Gate>
        <AppShell />
      </Gate>
    ),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/inbox" replace /> },
      { path: 'inbox', element: <InboxPage /> },
      { path: 'projects', element: <ProjectsList /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: ':projectKey/requirements', element: <RequirementsPage /> },
      { path: ':projectKey', element: <ProjectHome /> },
      { path: ':projectKey/releases/:version', element: <ReleasePage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
