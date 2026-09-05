/**
 * WorkspacePage — рабочее пространство: имя, участники, корзина.
 *
 * Правило: участники workspace — своя страница, приглашение по email, роли.
 * Отсюда состав экрана и три вещи, которые он держит:
 *
 * 1. **имя и роль спрашивающего** — по роли решается всё остальное: кнопки
 *    правки видит только владелец (участники — дело владельца, `editor` меняет
 *    проекты, а не людей);
 * 2. **участники** — почта, аватар, роль, дата вступления; пригласить по
 *    почте, сменить роль, убрать (с подтверждением);
 * 3. **корзина пространств** — своя, а не общая с корзиной проектов: у службы
 *    это разные объекты и разные сроки очистки.
 *
 * Адрес двойной: `/workspace` — текущее (то, что выбрано в переключателе), а
 * `/workspace/:id` — названное. Второй нужен затем, чтобы в чужое пространство
 * можно было заглянуть по ссылке, не переключая своё рабочее место.
 *
 * Обязательные состояния — все четыре: скелетон, пусто (у участников его не
 * бывает: владелец всегда есть), ошибка с повтором, «нет прав» на 403/404.
 * Тосты — только на отказ службы: успешную смену роли человек видит в строке.
 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, errorText } from '@/api'
import { setCurrentWorkspaceId, useCurrentWorkspaceId, useMe } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { formatDate } from '@/features/settings/format'
import {
  Avatar,
  Button,
  Card,
  Chip,
  Dialog,
  EmptyState,
  ErrorState,
  ForbiddenState,
  Icon,
  Input,
  Select,
  SkeletonLines,
  useToast,
} from '@/ui'

import { InviteDialog } from './InviteDialog'
import {
  useMembers,
  useRemoveMember,
  useRenameWorkspace,
  useRestoreWorkspace,
  useSetMemberRole,
  useTrashWorkspace,
  useWorkspaceCard,
  useWorkspaces,
} from './data'
import { ROLES, canManageMembers, workspaceLabel, type Member } from './types'
import { usePersonalName } from './usePersonalName'

const TH =
  'whitespace-nowrap border-b border-line px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2 align-middle'

export function WorkspacePage() {
  const t = useT()
  const toast = useToast()
  const { id: fromUrl } = useParams<{ id: string }>()
  const текущее = useCurrentWorkspaceId()
  const личное = useWorkspaces()
  // Хук — до всех досрочных возвратов: порядок хуков в React обязан совпадать
  // от отрисовки к отрисовке.
  const имяЛичного = usePersonalName()

  // Какое пространство открыто: названное в адресе, выбранное переключателем
  // или личное. Личное ищется в списке, а не спрашивается отдельно: список тут
  // всё равно нужен — из него растёт и корзина, и переключатель.
  const личноеИз = личное.data?.find((ws) => ws.personal)?.id
  const id = fromUrl ?? текущее ?? личноеИз

  const карточка = useWorkspaceCard(id)
  useDocumentCrumb(карточка.data?.name)

  if (личное.isLoading || (!!id && карточка.isLoading)) return <SkeletonLines count={6} />
  if (личное.error) return <ErrorState error={личное.error} onRetry={() => void личное.refetch()} />
  if (карточка.error instanceof ApiError && [403, 404].includes(карточка.error.status))
    return <ForbiddenState />
  if (карточка.error)
    return <ErrorState error={карточка.error} onRetry={() => void карточка.refetch()} />
  if (!карточка.data) return <ErrorState error={t('workspace.notFound')} />

  const ws = карточка.data
  const хозяин = canManageMembers(ws.role)
  // Личное пространство на экране зовётся ником хозяина.
  const имя = workspaceLabel(ws, имяЛичного)

  return (
    <div className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wider text-muted">{t('workspace.title')}</p>
          <h1 className="truncate font-display text-xl font-bold tracking-tight text-ink-strong">
            {имя}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-s2">
          <Chip tone={ws.role === 'owner' ? 'ok' : 'info'}>{t(`workspace.role.${ws.role}`)}</Chip>
          {текущее !== ws.id && !ws.personal && (
            <Button
              variant="secondary"
              onClick={() => {
                setCurrentWorkspaceId(ws.id)
                toast.success(t('workspace.switched', { name: имя }))
              }}
            >
              <Icon name="check" size={16} />
              {t('workspace.makeCurrent')}
            </Button>
          )}
        </div>
      </header>

      <NameCard
        id={ws.id}
        label={имя}
        personal={ws.personal}
        createdAt={ws.created_at}
        canEdit={хозяин}
        onFail={(error) => toast.error(errorText(error))}
      />

      <MembersCard workspaceId={ws.id} canManage={хозяин} />

      {хозяин && !ws.personal && <DangerCard id={ws.id} name={имя} />}

      <TrashCard />
    </div>
  )
}

/** Имя пространства и когда оно заведено. Переименовывает только владелец. */
function NameCard({
  id,
  label,
  personal,
  createdAt,
  canEdit,
  onFail,
}: {
  id: string
  /**
   * Имя на экране: у нетронутого личного пространства оно переведено
   * («Personal» службы — это «Личное»). Сохранение шлёт службе то, что в поле,
   * поэтому переименованное личное перестаёт переводиться и остаётся таким,
   * каким его назвал человек.
   */
  label: string
  personal: boolean
  createdAt: string
  canEdit: boolean
  onFail: (error: unknown) => void
}) {
  const t = useT()
  const [draft, setDraft] = useState(label)
  const rename = useRenameWorkspace()

  return (
    <Card title={t('workspace.name.title')} desc={t('workspace.name.desc')}>
      <div className="flex flex-wrap items-end gap-s3">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={!canEdit}
          maxLength={200}
          aria-label={t('workspace.name.label')}
          wrapperClassName="w-[360px] max-w-full"
        />
        {canEdit && (
          <Button
            variant="primary"
            disabled={!draft.trim() || draft.trim() === label}
            loading={rename.isPending}
            onClick={() => rename.mutate({ id, name: draft.trim() }, { onError: onFail })}
          >
            {t('workspace.name.save')}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted">
        {personal ? `${t('workspace.personal')} · ` : ''}
        {t('workspace.created', { date: formatDate(createdAt) })}
      </p>
    </Card>
  )
}

/** Участники: почта, роль, дата. Приглашение и правка — у владельца. */
function MembersCard({ workspaceId, canManage }: { workspaceId: string; canManage: boolean }) {
  const t = useT()
  const toast = useToast()
  const me = useMe()
  const members = useMembers(workspaceId)
  const setRole = useSetMemberRole()
  const remove = useRemoveMember()
  const [inviting, setInviting] = useState(false)
  const [removing, setRemoving] = useState<Member | null>(null)

  const fail = (error: unknown) => toast.error(errorText(error))

  return (
    <Card
      title={t('workspace.members.title')}
      desc={t('workspace.members.desc')}
      action={
        canManage ? (
          <Button variant="primary" onClick={() => setInviting(true)}>
            <Icon name="plus" size={16} />
            {t('workspace.members.invite')}
          </Button>
        ) : null
      }
    >
      {members.isLoading && <SkeletonLines count={3} />}
      {members.error && <ErrorState error={members.error} onRetry={() => void members.refetch()} />}
      {members.data && members.data.length === 0 && (
        <EmptyState compact icon="users" title={t('workspace.members.empty')} />
      )}
      {members.data && members.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className={TH}>{t('workspace.members.col.person')}</th>
                <th className={TH}>{t('workspace.members.col.role')}</th>
                <th className={TH}>{t('workspace.members.col.since')}</th>
                <th className={TH} />
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <tr key={m.user_id}>
                  <td className={TD}>
                    <span className="flex items-center gap-s2">
                      <Avatar id={m.user_id} size={28} />
                      <span className="min-w-0">
                        {/* Ник крупно, почта мелко:
                            зовут человека ником, а почта — то, по чему его
                            приглашали и чем различают тёзок. */}
                        <span className="block break-all font-medium text-ink-strong">
                          {m.nickname ?? m.email ?? m.user_id}
                        </span>
                        {m.email && <span className="block text-xs text-muted">{m.email}</span>}
                        {m.user_id === me.data?.id && (
                          <span className="block text-xs text-muted">
                            {t('workspace.members.you')}
                          </span>
                        )}
                      </span>
                    </span>
                  </td>
                  <td className={TD}>
                    {canManage ? (
                      <Select
                        value={m.role}
                        aria-label={t('workspace.members.col.role')}
                        className="w-[150px]"
                        onChange={(e) =>
                          setRole.mutate(
                            { id: workspaceId, userId: m.user_id, role: e.target.value },
                            { onError: fail },
                          )
                        }
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {t(`workspace.role.${role}`)}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Chip tone={m.role === 'owner' ? 'ok' : 'info'}>
                        {t(`workspace.role.${m.role}`)}
                      </Chip>
                    )}
                  </td>
                  <td className={`${TD} whitespace-nowrap text-muted`}>
                    {formatDate(m.created_at)}
                  </td>
                  <td className={`${TD} text-right`}>
                    {canManage && (
                      <Button
                        variant="ghost"
                        size="sm"
                        iconOnly
                        aria-label={t('workspace.members.remove')}
                        onClick={() => setRemoving(m)}
                      >
                        <Icon name="trash" size={16} className="text-err" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <InviteDialog open={inviting} onOpenChange={setInviting} workspaceId={workspaceId} />

      {/* Убрать человека — действие без отмены: подтверждение обязательно. */}
      <Dialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t('workspace.members.remove')}
        description={t('workspace.members.removeAsk', {
          who: removing?.nickname ?? removing?.email ?? removing?.user_id ?? '',
        })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('workspace.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => {
                if (!removing) return
                remove.mutate(
                  { id: workspaceId, userId: removing.user_id },
                  { onError: fail, onSettled: () => setRemoving(null) },
                )
              }}
            >
              {t('workspace.members.remove')}
            </Button>
          </>
        }
      />
    </Card>
  )
}

/** Опасная зона: пространство в корзину. Личное служба удалять не даёт. */
function DangerCard({ id, name }: { id: string; name: string }) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const trash = useTrashWorkspace()
  const [ask, setAsk] = useState(false)

  return (
    <Card tone="danger" title={t('workspace.trash.title')} desc={t('workspace.trash.desc')}>
      <div>
        <Button variant="danger" onClick={() => setAsk(true)}>
          <Icon name="trash" size={16} />
          {t('workspace.trash.action')}
        </Button>
      </div>
      <Dialog
        open={ask}
        onOpenChange={setAsk}
        title={t('workspace.trash.action')}
        description={t('workspace.trash.ask', { name })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAsk(false)}>
              {t('workspace.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={trash.isPending}
              onClick={() =>
                trash.mutate(id, {
                  onError: (error) => toast.error(errorText(error)),
                  onSuccess: () => {
                    // Текущим осталось бы то, чего нет: возвращаем человека в
                    // личное и уводим на его же страницу.
                    setCurrentWorkspaceId(null)
                    navigate('/workspace', { replace: true })
                  },
                  onSettled: () => setAsk(false),
                })
              }
            >
              {t('workspace.trash.action')}
            </Button>
          </>
        }
      />
    </Card>
  )
}

/** Корзина пространств: что удалено и до какого числа лежит. */
function TrashCard() {
  const t = useT()
  const имяЛичного = usePersonalName()
  const toast = useToast()
  const trashed = useWorkspaces(true)
  const restore = useRestoreWorkspace()

  if (trashed.isLoading || (trashed.data && trashed.data.length === 0)) return null

  return (
    <Card title={t('workspace.bin.title')} desc={t('workspace.bin.desc')}>
      {trashed.error && <ErrorState error={trashed.error} onRetry={() => void trashed.refetch()} />}
      <ul className="flex flex-col gap-s2">
        {(trashed.data ?? []).map((ws) => (
          <li
            key={ws.id}
            className="flex flex-wrap items-center justify-between gap-s2 rounded-sm border border-line px-3 py-2"
          >
            <span className="min-w-0">
              <span className="block truncate font-medium text-ink-strong">
                {workspaceLabel(ws, имяЛичного)}
              </span>
              <span className="block text-xs text-muted">
                {t('workspace.bin.until', { date: formatDate(ws.purge_after) })}
              </span>
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={ws.role !== 'owner'}
              onClick={() =>
                restore.mutate(ws.id, { onError: (error) => toast.error(errorText(error)) })
              }
            >
              <Icon name="restore" size={16} />
              {t('workspace.bin.restore')}
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
