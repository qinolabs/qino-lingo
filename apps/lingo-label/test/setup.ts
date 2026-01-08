import { beforeAll, afterEach, afterAll } from 'vitest'

// Import common setup from shared testing utilities
import '@qinolabs/testing/vitest-setup'

// App-specific test setup
beforeAll(() => {
  // In browser mode, environment variables are already set via Vite
  // No need to mock them here
})

afterEach(() => {
  // Clean up any app-specific state after each test
})

afterAll(() => {
  // Final cleanup
})