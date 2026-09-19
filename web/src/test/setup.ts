import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock scrollIntoView for jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn()
