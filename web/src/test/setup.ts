// Общая подготовка тестов: матчеры Testing Library и уборка DOM между тестами.
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
