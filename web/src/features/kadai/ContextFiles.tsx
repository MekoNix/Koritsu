/**
 * ContextFiles — папка файлов контекста одного решения.
 *
 * У каждого решения работы своя папка: методичка, исходники и таблица данных
 * одной задачи в промпт другой не едут. Причина не в порядке, а в цене — чужая
 * методичка сбивает модель ровно так же, как чужое условие, и платит за это
 * человек.
 *
 * **Общие файлы работы показываются вторым блоком, с галочками.** Файл,
 * приложенный ко всей работе (опись `GET …/materials` без `run`), к отдельной
 * её задаче отношения может не иметь вовсе, поэтому галочки сняты по умолчанию:
 * в промпт решения такой файл уезжает только после того, как его подключили
 * руками. Служба хранит выбранное, а не снятое, и файл, положенный в работу
 * завтра, сам ни в один промпт не попадёт — платит за промпт человек, не видя
 * его.
 *
 * **«Убрать» уносит файл с тома, а не только из папки.** Файл, положенный
 * сюда, принадлежит этому решению, и «убрал из папки, а он остался в работе»
 * было бы состоянием, которого человек не просил и не видит. Файл условия при
 * этом убрать нельзя: он помечен «условие», и меняется оно своим шагом.
 *
 * Версий условия в папке не бывает: условие живёт в решении текстом и правится
 * на месте, а файл — то, из чего его вынули, и он один.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines } from '@/ui'
import { useDeleteMaterial, useUploadMaterial } from '@/features/projects/data'
import { FileDrop } from '@/features/projects/FileDrop'

import { useContextMaterials, useKadaiCommonFiles, useSetKadaiCommonFiles } from './data'

/**
 * Что принимает разбор материалов: те же виды, что и опись работы.
 *
 * Книги Excel (`.xlsx`, `.xlsm`) стоят здесь наравне с текстом: данные к
 * заданию чаще приносят таблицей, чем набирают руками, а разбор кладёт их
 * листами строк — так же, как текст любого другого файла.
 */
export const ПРИНИМАЕМ = '.docx,.doc,.pdf,.txt,.md,.png,.jpg,.jpeg,.xlsx,.xlsm,.py,.cs,.cpp,.c,.h'

export function ContextFiles({
  projectId,
  runId,
  conditionId,
  disabled,
}: {
  projectId: string
  runId: string
  /** Файл условия: его из папки не убирают — условие меняют своим шагом. */
  conditionId: string | undefined
  disabled: boolean
}) {
  const t = useT()
  const files = useContextMaterials(projectId, runId)
  const upload = useUploadMaterial()
  const remove = useDeleteMaterial()
  const [беда, setБеда] = useState<string | null>(null)

  async function положить(список: File[]) {
    setБеда(null)
    try {
      // По запросу на файл: приём материалов у службы поштучный, а разбор всё
      // равно идёт очередью, и пачка не сделала бы его быстрее.
      for (const файл of список) {
        await upload.mutateAsync({ projectId, file: файл, runId })
      }
      await files.refetch()
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <>
      <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
        <header className="flex flex-wrap items-center gap-s2">
          <Icon name="file" size={16} className="text-muted" />
          <span className="font-semibold text-ink-strong">{t('kadai.context.title')}</span>
          <span className="text-xs text-muted">{t('kadai.context.hint')}</span>
        </header>

        {files.isPending ? (
          <SkeletonLines count={2} />
        ) : (files.data ?? []).length === 0 ? (
          <p className="text-xs text-muted">{t('kadai.context.empty')}</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm text-ink" data-testid="kadai-context-list">
            {(files.data ?? []).map((m) => (
              <li key={m.id} className="flex items-center gap-s2">
                <Icon name="file" size={14} className="text-muted" />
                <span className="truncate">{m.name}</span>
                {m.id === conditionId ? (
                  <span className="ml-auto rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">
                    {t('kadai.context.isCondition')}
                  </span>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    disabled={disabled || remove.isPending}
                    onClick={() => remove.mutate({ projectId, materialId: m.id })}
                  >
                    {t('kadai.context.remove')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        <FileDrop
          multiple
          accept={ПРИНИМАЕМ}
          disabled={disabled || upload.isPending}
          label={t('kadai.context.drop')}
          hint={t('kadai.context.dropHint')}
          onFiles={(список) => void положить(список)}
        />

        {беда && <p className="text-xs text-err">{беда}</p>}
        {remove.isError && <p className="text-xs text-err">{errorText(remove.error)}</p>}
      </section>

      <CommonFiles projectId={projectId} runId={runId} disabled={disabled} />
    </>
  )
}

/**
 * Общие файлы работы: что из них видит модель этого решения.
 *
 * Блок стоит рядом с папкой решения, а не в настройках работы, потому что
 * вопрос здесь про решение: один и тот же файл бывает нужен одной задаче и
 * лишним в другой, и выбор одной соседнюю не задевает.
 *
 * Галочки по умолчанию сняты, и ставятся поштучно. Служба хранит выбранное, а
 * не снятое, поэтому файл, приложенный к работе позже, приезжает сюда без
 * галочки: за промпт, в который он уехал бы сам, платит человек, не увидев его
 * там.
 */
function CommonFiles({
  projectId,
  runId,
  disabled,
}: {
  projectId: string
  runId: string
  disabled: boolean
}) {
  const t = useT()
  const общие = useKadaiCommonFiles(projectId, runId)
  const выбор = useSetKadaiCommonFiles()

  /** Подключённые после этой галочки — списком целиком: служба заменяет весь. */
  function переключить(materialId: string, включён: boolean) {
    const выбранные = (общие.data ?? [])
      .filter((ф) => (ф.id === materialId ? включён : ф.selected))
      .map((ф) => ф.id)
    выбор.mutate({ projectId, runId, included: выбранные })
  }

  return (
    <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
      <header className="flex flex-wrap items-center gap-s2">
        <Icon name="file" size={16} className="text-muted" />
        <span className="font-semibold text-ink-strong">{t('kadai.common.title')}</span>
        <span className="text-xs text-muted">{t('kadai.common.hint')}</span>
      </header>

      {общие.isPending ? (
        <SkeletonLines count={2} />
      ) : (общие.data ?? []).length === 0 ? (
        <p className="text-xs text-muted">{t('kadai.common.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm text-ink" data-testid="kadai-common-list">
          {(общие.data ?? []).map((ф) => (
            <li key={ф.id}>
              <label className="flex items-center gap-s2">
                <input
                  type="checkbox"
                  className="accent-[var(--accent)]"
                  checked={ф.selected}
                  disabled={disabled || выбор.isPending}
                  onChange={(e) => переключить(ф.id, e.target.checked)}
                />
                <span className="truncate">{ф.name}</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {/* Пояснение показывается, пока не подключён ни один файл: снятые галочки
          сами по себе читаются как «файлы почему-то отключены», а это
          умолчание, и держится оно на том, что общий файл работы нужен не
          каждой её задаче. */}
      {(общие.data ?? []).length > 0 && !(общие.data ?? []).some((ф) => ф.selected) && (
        <p className="text-xs text-muted">{t('kadai.common.off')}</p>
      )}

      {выбор.isError && <p className="text-xs text-err">{errorText(выбор.error)}</p>}
    </section>
  )
}
