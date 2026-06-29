/**
 * mockServer.js — transport-layer fetch interceptor for fixture-backed dev mode.
 *
 * Installed from main.js when VITE_USE_FIXTURES=true. Intercepts window.fetch
 * and routes /api/* requests to static fixture JSON or plausible stubs so the
 * SAME store code and SAME applyMutation path run in both mock and live modes.
 *
 * Limitations (acceptable for a dev convenience):
 *   - Mutations are NOT stateful: POST/PATCH/DELETE/PUT succeed but the
 *     subsequent GET re-fetch still returns the original fixture data.
 *     UI stores will refresh but show the pre-mutation fixture state.
 *     This is intentional — the mock is for UI layout / loading-state work,
 *     not for testing mutation logic (use the real backend for that).
 *   - Model-management stubs (GET /api/models, POST /api/models, etc.) return
 *     a static list. Creates and deletes succeed but do NOT change the list on
 *     the next GET — same stateless limitation as element/module stubs above.
 *   - /simulate is served from a fixture too, so the ParameterTable scenario
 *     toy runs through the SAME runSimulate() path in mock and live modes.
 *     /identifiability and /topology.svg fall through to the real fetch.
 *   - Model-scoped GET handlers match on the URL SUFFIX (/document, /assembly,
 *     /registry) rather than the literal uid 'default', so they work for any
 *     uid the router might open (including ones created via the home page stubs).
 */

// Lazy-load fixtures. Vite resolves these as static JSON imports.
async function loadFixtureMap() {
  const [assemblyMod, documentMod, registryMod, simulateMod] = await Promise.all([
    import('../fixtures/assembly.json'),
    import('../fixtures/document.json'),
    import('../fixtures/registry.json'),
    import('../fixtures/simulate.json'),
  ]);
  return {
    assembly: assemblyMod.default,
    document: documentMod.default,
    registry: registryMod.default,
    simulate: simulateMod.default,
  };
}

/**
 * Install the mock. Must be called before any store action runs (i.e. before
 * refreshAll() in main.js). Safe to call only once.
 */
export async function installMockServer() {
  const fixtures = await loadFixtureMap();
  const realFetch = window.fetch.bind(window);

  // Static fixture data for the model-list home page.
  const MOCK_MODELS = [
    { uid: 'default', name: 'Default' },
    { uid: 'example-light', name: 'Light office (example copy)' },
  ];
  const MOCK_EXAMPLES = [
    { key: 'light_office', name: 'Light office' },
    { key: 'heavy_apartment', name: 'Heavy apartment' },
  ];

  window.fetch = async function mockFetch(input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();

    // -----------------------------------------------------------------------
    // Model-management endpoints  (/api/models[/...])
    // These come BEFORE the model-scoped suffix checks so the more-specific
    // paths are matched first.
    // -----------------------------------------------------------------------

    // GET /api/models/examples
    if (method === 'GET' && url.endsWith('/api/models/examples')) {
      return jsonResponse(MOCK_EXAMPLES);
    }
    // GET /api/models  (list — must not match /api/models/examples above)
    if (method === 'GET' && url.match(/\/api\/models\/?$/)) {
      return jsonResponse(MOCK_MODELS);
    }
    // POST /api/models/from_example
    if (method === 'POST' && url.includes('/api/models/from_example')) {
      return jsonResponse({ uid: 'example-light', name: 'Example copy' }, 201);
    }
    // POST /api/models  (create blank)
    if (method === 'POST' && url.match(/\/api\/models\/?$/)) {
      return jsonResponse({ uid: 'default', name: 'New model' }, 201);
    }
    // PATCH /api/models/{uid}  (rename)
    if (method === 'PATCH' && url.match(/\/api\/models\/[^/]+\/?$/)) {
      const name = (() => { try { return JSON.parse(init?.body ?? '{}').name; } catch { return 'Renamed'; } })();
      const uid = url.split('/').pop();
      return jsonResponse({ uid, name });
    }
    // DELETE /api/models/{uid}  (must match before the element/module DELETE checks)
    if (method === 'DELETE' && url.match(/\/api\/models\/[^/]+\/?$/) &&
        !url.includes('/elements/') && !url.includes('/modules/')) {
      return emptyResponse(204);
    }

    // -----------------------------------------------------------------------
    // GETs: serve fixture JSON (match on suffix so any uid works)
    // -----------------------------------------------------------------------
    if (method === 'GET') {
      if (url.includes('/registry')) {
        return jsonResponse(fixtures.registry);
      }
      if (url.includes('/assembly')) {
        return jsonResponse(fixtures.assembly);
      }
      if (url.includes('/document')) {
        return jsonResponse(fixtures.document);
      }
      // topology.svg — fall through to real fetch (or 404 gracefully)
    }

    // -----------------------------------------------------------------------
    // Mutations: acknowledge without mutating fixture state
    // -----------------------------------------------------------------------
    // POST elements → return first fixture element as a plausible stub
    if (method === 'POST' && url.includes('/elements')) {
      return jsonResponse(fixtures.document.elements[0] ?? {}, 201);
    }
    // PATCH elements/{eid}
    if (method === 'PATCH' && url.includes('/elements/')) {
      return jsonResponse(fixtures.document.elements[0] ?? {}, 200);
    }
    // DELETE elements/{eid}
    if (method === 'DELETE' && url.includes('/elements/')) {
      return emptyResponse(204);
    }
    // POST modules
    if (method === 'POST' && url.includes('/modules') && !url.includes('/routing')) {
      return jsonResponse(fixtures.document.modules[0] ?? {}, 201);
    }
    // DELETE modules/{mid}
    if (method === 'DELETE' && url.includes('/modules/')) {
      return emptyResponse(204);
    }
    // PUT modules/{mid}/routing
    if (method === 'PUT' && url.includes('/routing')) {
      return jsonResponse(fixtures.document.modules[0] ?? {}, 200);
    }
    // POST simulate → serve fixture simulation result
    if (method === 'POST' && url.includes('/simulate')) {
      return jsonResponse(fixtures.simulate, 200);
    }

    // Anything else (identifiability, topology.svg) — real fetch
    return realFetch(input, init);
  };
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function emptyResponse(status = 204) {
  return new Response(null, { status });
}
