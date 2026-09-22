import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock scrollIntoView for jsdom
window.HTMLElement.prototype.scrollIntoView = vi.fn()

// Mock ResizeObserver for jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
