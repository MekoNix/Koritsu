/**
 * BlockVersions — история списка блоков со сравнением и возвратом.
 *
 * Рисует общий компонент `features/reports/VersionHistory` (агент C): он не
 * знает ни про теги, ни про блоки — на входе список версий, хук «дай текст
 * версии N» и обработчик возврата. Второй такой же экран рядом с первым
 * разошёлся бы с ним на первой же правке.
 *
 * **Список версионируется целиком, а не поблочно.** Половина правок
 * переставляет блоки местами, и поблочная версия об этом молчит
 * (`versions/routes.py`). Поэтому сравниваются не тексты одного блока, а весь
 * список одним текстом: имя блока и его содержимое строками подряд.
 *
 * **Возврат ничего не удаляет.** Служба дописывает выбранный список новой
 * версией, и номер в ответе больше того, к которому вернулись.
 */
import { useT } from '@/i18n'
import { VersionHistory, type VersionText } from '@/features/reports/VersionHistory'

import { useBlockVersion, useBlockVersions, useRollbackBlocks } from './data'
import { blocksText } from './stages'
import type { BlockRecordBody } from './types'

export function BlockVersions({
  projectId,
  blocks,
  canEdit,
}: {
  projectId: string
  /** Текущий список: правая сторона сравнения, когда отмечена одна версия. */
  blocks: BlockRecordBody[] | undefined
  canEdit: boolean
}) {
  const t = useT()
  const versions = useBlockVersions(projectId)
  const rollback = useRollbackBlocks(projectId)

  /**
   * «Дай текст версии N» для сравнения. Хук пропсом, а не адрес маршрута:
   * маршруты у тега и у блоков разные, и знать про оба в общем компоненте
   * значило бы завести там ветвление по области.
   */
  function useVersionText(n: number | null): VersionText {
    const версия = useBlockVersion(projectId, n)
    return {
      text: n === null ? undefined : версия.data ? blocksText(версия.data.blocks) : undefined,
      loading: n !== null && версия.isPending,
      error: n === null ? null : versionError(версия.error),
    }
  }

  return (
    <VersionHistory
      entries={versions.data}
      loading={versions.isPending}
      error={versions.error}
      useVersionText={useVersionText}
      currentText={blocksText(blocks)}
      onRollback={(n) => rollback.mutate(n)}
      canEdit={canEdit}
      rollbackPending={rollback.isPending}
      rollbackError={rollback.error}
      sourceLabel={(source) =>
        source === 'manual' ? t('kadai.blocks.byHuman') : t('kadai.blocks.byAgent')
      }
      emptyText={t('kadai.versions.none')}
    />
  )
}

/** Беда запроса версии. `null` — её нет; иначе она уезжает наружу как есть. */
function versionError(error: unknown): unknown {
  return error ?? null
}
