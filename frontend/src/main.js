import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

// When VITE_USE_FIXTURES=true the fetch interceptor is installed BEFORE
// the app mounts so that every /api/* call hits the mock transport, not a
// real backend. The store code and applyMutation path are identical in both
// modes — the only difference is what fetch returns.
if (import.meta.env.VITE_USE_FIXTURES === 'true') {
  const { installMockServer } = await import('./lib/mockServer.js')
  await installMockServer()
}

// Route-aware boot: App.svelte's $effect handles setModelId + refreshAll for
// both the initial load (when the hash is already #/models/{uid}) and for
// subsequent navigations from the home page. We do NOT call refreshAll()
// unconditionally here — if the route is home, the model stores stay idle
// until the user opens a model.

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
