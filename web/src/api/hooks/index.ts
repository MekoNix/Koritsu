// Все хуки оболочки одной дверью: `import { useMe, useUsage } from '@/api/hooks'`.
export { useBootstrap, fetchBootstrap, type Bootstrap } from './useBootstrap'
export { useMe, useLogout, useUpdateProfile, type ProfilePatch } from './useMe'
export { useModules } from './useModules'
export { useUsage } from './useUsage'
export {
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
  useDeleteNotification,
  СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ,
} from './useNotifications'
export { useJobStream, type Job, type JobStreamState } from './useJobStream'
export { useUserEvents } from './useUserEvents'
export {
  useCurrentWorkspace,
  useCurrentWorkspaceId,
  useWorkspaceScopeReset,
  setCurrentWorkspaceId,
  type Workspace,
} from './useCurrentWorkspace'
export { useIsAdmin } from './useIsAdmin'
