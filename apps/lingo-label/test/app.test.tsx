import { describe, it, expect } from 'vitest'

// Basic test to verify testing setup works
describe('Template Frontend', () => {
  it('basic math operations work', () => {
    expect(2 + 2).toBe(4)
    expect(20 * 3).toBe(60)
  })

  it('string operations work', () => {
    const appName = 'template-frontend'
    expect(appName).toContain('template')
    expect(appName).toContain('frontend')
  })

  it('object structure test', () => {
    const appConfig = {
      name: 'template-frontend',
      port: 3000,
      backend: 'http://localhost:4002'
    }

    expect(appConfig.name).toBe('template-frontend')
    expect(appConfig.port).toBe(3000)
    expect(appConfig.backend).toContain('localhost')
  })
})