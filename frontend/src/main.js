import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'
import { refreshAll } from './stores/model.js'

// When VITE_USE_FIXTURES=true the fetch interceptor is installed BEFORE
// refreshAll() so that every /api/* call hits the mock transport, not a
// real backend. The store code and applyMutation path are identical in both
// modes — the only difference is what fetch returns.
if (import.meta.env.VITE_USE_FIXTURES === 'true') {
  const { installMockServer } = await import('./lib/mockServer.js')
  await installMockServer()
}

// Initial load: pull document + assembly + registry in parallel, once.
refreshAll()

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
