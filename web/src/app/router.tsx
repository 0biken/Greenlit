import { createBrowserRouter, Navigate, useRouteError } from 'react-router'
import { ErrorState } from '../design/states'
import { EnrolTotp, RequestReset, ResetPassword, SignIn, SignUp, TwoStep, VerifyEmail } from '../features/auth/AuthPages'
import { DefectDetailPage } from '../features/defects/DefectDetailPage'
import { DefectsList } from '../features/defects/DefectsList'
import { NewDefectPage } from '../features/defects/NewDefectPage'
import { InboxPage } from '../features/inbox/InboxPage'
import { AcceptInvite, Welcome } from '../features/orgs/OrgPages'
import { NotFound } from '../features/NotFound'
import { ProjectHome } from '../features/projects/ProjectHome'
import { ProjectsList } from '../features/projects/ProjectsList'
import { ReleasePage } from '../features/releases/ReleasePage'
import { ReleasesList } from '../features/releases/ReleasesList'
import { RunPage } from '../features/runs/RunPage'
import { RunsList } from '../features/runs/RunsList'
import { SettingsPage } from '../features/settings/SettingsPage'
import { SharedReportPage } from '../features/shared/SharedReportPage'
import { AppShell } from './AppShell'
import { Gate, SignedInOnly } from './Gate'

function RouteError() {
  const error = useRouteError()
  console.error(error)
  return <ErrorState message="Something went wrong on this screen. Reload to try again." onRetry={() => window.location.reload()} />
}

// URLs use display IDs and project keys: /hube, /hube/releases/2.4.1 (DATA §4).
export const router = createBrowserRouter([
  // A share link: no sign-in, the token in the address is the credential.
  { path: '/shared/:token', element: <SharedReportPage /> },
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
      { path: ':projectKey', element: <ProjectHome /> },
      { path: ':projectKey/releases', element: <ReleasesList /> },
      { path: ':projectKey/releases/:version', element: <ReleasePage /> },
      { path: ':projectKey/runs', element: <RunsList /> },
      { path: ':projectKey/runs/:no', element: <RunPage /> },
      { path: ':projectKey/bugs', element: <DefectsList /> },
      { path: ':projectKey/bugs/new', element: <NewDefectPage /> },
      { path: ':projectKey/bugs/:no', element: <DefectDetailPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
