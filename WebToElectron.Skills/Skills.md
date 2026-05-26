---
name: web-to-electron
description: >
  Convert a Vite+React web application into a dedicated Electron desktop app
  correctly the first time. Covers electron main/preload/IPC scaffolding,
  HashRouter requirement, custom protocols, frameless titlebar, Zustand
  persist via SQLite KV, electron-builder packaging, and the dev-loop pitfalls
  (cross-env env var leak, stale dist/, BrowserRouter under file://, native
  modules in asar) that silently break Electron renders.
  Trigger: "convert to electron", "make this a desktop app", "package as electron"
***

# web-to-electron

> Generic recipe for converting any **Vite + React** web app into a packaged Electron desktop app — without falling into the same 50-iteration debug loop.

***

## When to Use

- User says "convert to Electron", "make this a desktop app", "package as Electron"
- Need native OS features (file system, tray, notifications, native menus)
- App requires local SQLite/native modules that can't run in a browser
- Offline-first app where a browser tab isn't acceptable UX
- Custom window chrome (frameless, custom titlebar, splash screen)

***

## Pre-Flight Checks

Before writing a single line of Electron code, inventory the web app:

| Area | Question | Electron implication |
|---|---|---|
| **Router** | Is it using `BrowserRouter`? | Must swap to `HashRouter` |
| **Storage** | Any `localStorage` / `sessionStorage`? | Bridge to SQLite KV via IPC |
| **File uploads** | `blob:` or `data:` URLs? | Use custom file protocol + `userData` path |
| **External URLs** | `fetch()` to third-party APIs? | CORS + CSP policy — check `webSecurity` |
| **Env vars** | `import.meta.env.VITE_*` or `process.env.*`? | Confirm only Vite build-time vars |
| **Native modules** | `better-sqlite3`, `sharp`, `canvas`? | Needs `asarUnpack` in builder config |
| **SSR / server** | Next.js SSR, API routes? | Electron is static-file only — no Node server in renderer |

Every item in the last column is a bridge point: either replace it with an IPC call, or rethink the architecture before proceeding.

***

## Step-by-Step Recipe

### 3.1 Install Dependencies

```bash
# Runtime
npm install electron

# Build tooling
npm install -D electron-builder concurrently wait-on

# Optional but recommended
npm install -D electron-window-state   # persist window size/position

# Native DB (pick one)
npm install node-sqlite3-wasm          # pure WASM — no native rebuild needed (recommended)
# OR
npm install better-sqlite3             # requires native rebuild, needs asarUnpack
```

### 3.2 Create `electron/` Directory

```
electron/
├── main.ts          ← entry point (BrowserWindow, protocol, IPC bootstrap)
├── preload.ts       ← contextBridge — the ONLY renderer↔main bridge
├── ipc.ts           ← all ipcMain.handle() registrations
├── storage/
│   ├── db.ts        ← DB init, WAL, migration runner, kv helpers
│   └── migrations.ts← versioned SQL migrations
└── tsconfig.json    ← separate TS config (CommonJS, ES2022)
```

### 3.3 `electron/main.ts` Skeleton

```ts
import { app, BrowserWindow, protocol, ipcMain } from 'electron';
import path from 'path';
import { registerIpc } from './ipc';

// ✅ MUST be BEFORE app.whenReady() — silent failure if inside whenReady
protocol.registerSchemesAsPrivileged([
  { scheme: 'app-media', privileges: { secure: true, standard: true, stream: true } },
]);

// ✅ CORRECT: no env vars, no cross-env. app.isPackaged is the canonical Electron way.
const isDev = !app.isPackaged;

// Single-instance lock — prevent two app windows racing on the same DB
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

let mainWindow: BrowserWindow | null = null;

app.whenReady().then(async () => {
  // Register custom file protocol INSIDE whenReady
  protocol.registerFileProtocol('app-media', (request, callback) => {
    const filePath = path.join(app.getPath('userData'), 'media', decodeURIComponent(
      new URL(request.url).pathname
    ));
    callback({ path: filePath });
  });

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    frame: false,          // frameless for custom titlebar
    show: false,           // prevent white flash — show in ready-to-show
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,   // ✅ security: isolate renderer from Node
      nodeIntegration: false,   // ✅ security: no Node in renderer
      sandbox: false,           // needed for preload ipcRenderer to work
      webSecurity: !isDev,      // allow localhost:5173 CORS in dev
    },
  });

  // Wait for React to mount before showing (eliminates white flash)
  mainWindow.once('ready-to-show', () => mainWindow?.show());

  // Load app
  if (isDev) {
    await mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  registerIpc(mainWindow);

  // Second instance: focus existing window
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

### 3.4 `electron/preload.ts` Skeleton

```ts
import { contextBridge, ipcRenderer } from 'electron';

// Expose ONLY what the renderer needs — no raw ipcRenderer
contextBridge.exposeInMainWorld('myApp', {
  platform: process.platform,

  kv: {
    get: (key: string) => ipcRenderer.invoke('kv:get', key),
    set: (key: string, value: string) => ipcRenderer.invoke('kv:set', key, value),
    delete: (key: string) => ipcRenderer.invoke('kv:delete', key),
  },

  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close:    () => ipcRenderer.invoke('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
  },

  app: {
    getVersion: () => ipcRenderer.invoke('app:version'),
    openUserDataFolder: () => ipcRenderer.invoke('app:openUserData'),
  },

  // Event subscriptions (main → renderer push)
  on: (channel: string, cb: (...args: unknown[]) => void) => {
    ipcRenderer.on(channel, (_event, ...args) => cb(...args));
  },
  off: (channel: string, cb: (...args: unknown[]) => void) => {
    ipcRenderer.off(channel, cb);
  },
});
```

### 3.5 `electron/ipc.ts` Skeleton

```ts
import { ipcMain, BrowserWindow, app, shell } from 'electron';
import { kvGet, kvSet, kvDelete } from './storage/db';

export function registerIpc(win: BrowserWindow) {
  // KV store
  ipcMain.handle('kv:get',    (_, key: string) => kvGet(key));
  ipcMain.handle('kv:set',    (_, key: string, value: string) => kvSet(key, value));
  ipcMain.handle('kv:delete', (_, key: string) => kvDelete(key));

  // Window controls
  ipcMain.handle('window:minimize',   () => win.minimize());
  ipcMain.handle('window:maximize',   () => win.isMaximized() ? win.unmaximize() : win.maximize());
  ipcMain.handle('window:close',      () => win.close());
  ipcMain.handle('window:isMaximized',() => win.isMaximized());

  // App
  ipcMain.handle('app:version',       () => app.getVersion());
  ipcMain.handle('app:openUserData',  () => shell.openPath(app.getPath('userData')));
}
```

### 3.6 Renderer Bridge (`src/bridge/`)

**`src/bridge/desktop.ts`** — typed surface + environment detection:

```ts
export interface MyAppApi {
  platform: string;
  kv: {
    get(key: string): Promise<string | null>;
    set(key: string, value: string): Promise<void>;
    delete(key: string): Promise<void>;
  };
  window: {
    minimize(): Promise<void>;
    maximize(): Promise<void>;
    close(): Promise<void>;
    isMaximized(): Promise<boolean>;
  };
  app: {
    getVersion(): Promise<string>;
    openUserDataFolder(): Promise<void>;
  };
  on(channel: string, cb: (...args: unknown[]) => void): void;
  off(channel: string, cb: (...args: unknown[]) => void): void;
}

declare global {
  interface Window { myApp?: MyAppApi; }
}

export const isDesktop = (): boolean => typeof window !== 'undefined' && !!window.myApp;
export const desktopApi = (): MyAppApi => window.myApp!;
```

**`src/bridge/storage-adapter.ts`** — Zustand `StateStorage` that forks to IPC on desktop, `localStorage` on web:

```ts
import { StateStorage } from 'zustand/middleware';
import { isDesktop, desktopApi } from './desktop';

export const desktopStorage: StateStorage = {
  getItem: async (key) => {
    if (isDesktop()) return desktopApi().kv.get(key);
    return localStorage.getItem(key);
  },
  setItem: async (key, value) => {
    if (isDesktop()) return desktopApi().kv.set(key, value);
    localStorage.setItem(key, value);
  },
  removeItem: async (key) => {
    if (isDesktop()) return desktopApi().kv.delete(key);
    localStorage.removeItem(key);
  },
};
```

**Usage in Zustand store:**
```ts
import { persist, createJSONStorage } from 'zustand/middleware';
import { desktopStorage } from '../bridge/storage-adapter';

export const useMyStore = create(
  persist(
    (set) => ({ /* ... state ... */ }),
    {
      name: 'my-store-key',               // stable key — never change
      storage: createJSONStorage(() => desktopStorage),
    }
  )
);
```

### 3.7 Router Swap

```tsx
// src/main.tsx — BEFORE (breaks under file://)
import { BrowserRouter } from 'react-router-dom';
// AFTER (✅ works in both browser and packaged Electron)
import { HashRouter } from 'react-router-dom';
```

This is **non-negotiable** for packaged builds. `BrowserRouter` depends on a server to resolve `/today` → Electron serves via `file://` with no server.

### 3.8 `vite.config.ts`

```ts
export default defineConfig({
  base: './',          // ✅ relative paths — required for file:// loading
  build: {
    outDir: 'dist',
  },
  // ...rest of config
});
```

Without `base: './'`, Vite outputs absolute `/assets/...` paths that 404 under `file://`.

### 3.9 `electron/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "node",
    "outDir": "../dist-electron",
    "rootDir": ".",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["./**/*.ts"],
  "exclude": ["node_modules"]
}
```

Electron main process is CommonJS — keep it separate from the Vite/ESM renderer tsconfig.

### 3.10 Frameless `<Titlebar />` Component

```tsx
// src/components/desktop/Titlebar.tsx
import { isDesktop, desktopApi } from '../../bridge/desktop';

export function Titlebar() {
  if (!isDesktop()) return null;
  const api = desktopApi();

  return (
    <div style={{ WebkitAppRegion: 'drag' as React.CSSProperties['WebkitAppRegion'] }}
         className="titlebar">
      <span className="titlebar-title">My App</span>
      <div className="titlebar-controls" style={{ WebkitAppRegion: 'no-drag' as any }}>
        <button onClick={() => api.window.minimize()} aria-label="Minimize">─</button>
        <button onClick={() => api.window.maximize()} aria-label="Maximize">□</button>
        <button onClick={() => api.window.close()}    aria-label="Close">✕</button>
      </div>
    </div>
  );
}
```

```css
.titlebar {
  -webkit-app-region: drag;    /* entire bar draggable */
  display: flex;
  align-items: center;
  height: 38px;
  padding: 0 12px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  user-select: none;
}
.titlebar-controls {
  -webkit-app-region: no-drag; /* buttons must NOT be draggable */
  display: flex;
  gap: 8px;
  margin-left: auto;
}
```

### 3.11 `package.json` Scripts

```json
{
  "main": "dist-electron/main.js",
  "scripts": {
    "dev":              "vite",
    "dev:electron":     "concurrently -k -n vite,electron \"npm run dev\" \"npm run dev:electron:wait\"",
    "dev:electron:wait":"wait-on http://localhost:5173 && npm run build:electron && electron .",
    "build":            "vite build",
    "build:electron":   "tsc -p electron/tsconfig.json",
    "package":          "npm run build && npm run build:electron && electron-builder",
    "package:win":      "npm run package -- --win",
    "package:mac":      "npm run package -- --mac",
    "package:linux":    "npm run package -- --linux"
  }
}
```

### 3.12 `electron-builder` Config (`electron-builder.config.js`)

```js
module.exports = {
  appId:   'com.myorg.myapp',
  productName: 'My App',
  directories: { output: 'release' },

  files: ['dist/**', 'dist-electron/**'],

  asar: true,
  asarUnpack: [
    'node_modules/node-sqlite3-wasm/**',   // ✅ WASM must be outside asar
    'node_modules/better-sqlite3/**',       // if using better-sqlite3
  ],

  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
  },
  mac: {
    target: [{ target: 'dmg', arch: ['x64', 'arm64'] }],
    category: 'public.app-category.productivity',
  },
  linux: {
    target: [{ target: 'AppImage', arch: ['x64'] }],
    category: 'Utility',
  },

  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
  },
};
```

***

## Anti-Patterns (Pitfall Table)

These broke a real app across 50+ debug iterations. Learn them by heart.

| ❌ Anti-pattern | ✅ Correct pattern | Why |
|---|---|---|
| `cross-env MY_VAR=1 electron .` to detect dev mode | `const isDev = !app.isPackaged;` | Env vars don't propagate reliably on Windows; `app.isPackaged` is the canonical Electron API |
| `BrowserRouter` in renderer | `HashRouter` | `BrowserRouter` needs a server for route resolution; `file://` has none — blank page on every sub-route |
| `base: '/'` (default) in `vite.config.ts` | `base: './'` | Vite emits absolute `/assets/...` URLs → 404 under `file://` |
| `protocol.registerSchemesAsPrivileged()` inside `app.whenReady()` | Call it **before** `app.whenReady()` at top of `main.ts` | Schemes must be registered before the app is ready; calling inside `whenReady` silently fails |
| `webSecurity: true` in dev | `webSecurity: !isDev` | Strict CORS blocks `localhost:5173` renderer requests during development |
| `nodeIntegration: true` | `contextIsolation: true, nodeIntegration: false` | Prevents prototype pollution and Node API leakage into renderer |
| `blob:` / `data:` URLs for user-uploaded media | Custom `app-media://` protocol → `userData/media/{file}` | Blob URLs are memory-bound and lost on reload; large files OOM |
| Native modules inside asar archive | `asarUnpack: ["node_modules/my-native-module/**"]` | Native `.node` binaries can't execute from inside an asar archive |
| No single-instance lock | `app.requestSingleInstanceLock()` at top of `main.ts` | Two app instances racing on the same SQLite DB causes corruption |
| `BrowserWindow.show()` immediately | `show: false` + `mainWindow.once('ready-to-show', () => win.show())` | Shows a white flash while React mounts |
| Running stale `dist/` after edits | Nuke `dist/` and `dist-electron/`, fully quit, restart `dev:electron` | HMR doesn't help if `isDev` path resolves incorrectly |
| `localStorage` in packaged app for Zustand persist | `createJSONStorage(() => desktopStorage)` adapter via IPC → SQLite KV | `localStorage` can be wiped by the OS/browser engine; can't share state with main process |

***

## Verification Checklist

After conversion, validate every item:

- [ ] `npm run dev` opens browser at `http://localhost:5173` — app works normally
- [ ] `npm run dev:electron` opens Electron window with **same content** (not blank, not stale)
- [ ] All routes navigate correctly under `HashRouter` (check sub-routes like `/settings`)
- [ ] User-uploaded file persists across app **restart** (not just reload)
- [ ] `npm run package:win` (or mac/linux) produces installer in `release/`
- [ ] Installed packaged app launches without crash
- [ ] State persists across close → relaunch in packaged build
- [ ] Window minimize / maximize / close buttons work (if using frameless titlebar)
- [ ] DevTools `console.log` in main process shows correct `isDev = false` in packaged build

***

## Debugging Blank Electron Page

Decision tree — work top to bottom:

```
1. Header/footer visible but body blank?
   → console.log(app.isPackaged) in main.ts
   → If "true" in dev: isDev = false → stale dist/ being served
   → FIX: nuke dist/ and dist-electron/, quit everything, restart npm run dev:electron

2. Whole window blank?
   → Open DevTools (mainWindow.webContents.openDevTools())
   → Check console for "Cannot GET /" or 404 on routes
   → CAUSE: BrowserRouter under file://
   → FIX: swap to HashRouter in src/main.tsx

3. Asset 404s (JS/CSS chunks not loading)?
   → Check Network tab for /assets/... 404s
   → CAUSE: base: '/' in vite.config.ts
   → FIX: base: './'

4. Crash on first SQLite call after packaging?
   → Check main process console for WASM/native module errors
   → CAUSE: native module inside asar
   → FIX: add to asarUnpack in electron-builder config

5. Custom protocol returns nothing?
   → Check if registerSchemesAsPrivileged is called before app.whenReady()
   → Check scheme name matches exactly between registration and usage
   → FIX: move registration to top of main.ts before all app.* calls

6. Still blank after all above?
   → Add console.log to main.ts: log isDev, loaded URL, and __dirname
   → Confirm dist/index.html exists and is not empty
   → Re-run npm run build && npm run build:electron before electron .
```

***

## Dev Loop Reference

```bash
# Full fresh restart (use when page is blank or stale)
rm -rf dist dist-electron
npm run dev:electron

# Quick rebuild Electron main process only (no Vite change)
npm run build:electron && electron .

# Package for current platform
npm run package:win   # Windows NSIS installer
npm run package:mac   # macOS DMG
npm run package:linux # Linux AppImage
```