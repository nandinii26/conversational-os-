const { app, BrowserWindow, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')

let backendProcess = null
let mainWindow = null
const protocol = 'docpilot'

function tokenFromProtocolUrl(url) {
  try {
    return new URL(url).searchParams.get('token')
  } catch {
    return null
  }
}

function openAuthenticatedWindow(url) {
  const token = tokenFromProtocolUrl(url)
  if (!token || !mainWindow) return

  if (app.isPackaged) {
    // Packaged app: load the bundled index.html with the token as a query param
    const indexPath = path.join(__dirname, '..', 'dist', 'index.html')
    mainWindow.loadFile(indexPath, { query: { token } })
  } else {
    // Dev mode: load the Vite dev server URL with the token as a query param.
    // loadFile would look for dist/index.html which doesn't exist during development.
    mainWindow.loadURL(`http://localhost:5173/?token=${token}`)
  }
  mainWindow.show()
  mainWindow.focus()
}

// Google sign-in completes in the system browser and returns using this
// protocol, allowing the installed app to receive the JWT.
if (process.defaultApp) {
  app.setAsDefaultProtocolClient(protocol, process.execPath, [path.resolve(process.argv[1])])
} else {
  app.setAsDefaultProtocolClient(protocol)
}

const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  app.quit()
}

// ── Start the bundled Python backend ────────────────────────────────────────
function startBackend() {
  // In production: backend exe sits next to the Electron app
  // In dev: assume backend is already running manually
  const isPackaged = app.isPackaged

  if (isPackaged) {
    // Path to backend exe inside the installed app
    const backendExe = path.join(
      process.resourcesPath,
      'backend',
      'docpilot-backend.exe'
    )

    console.log('Starting backend from:', backendExe)

    backendProcess = spawn(backendExe, [], {
      detached: false,
      stdio: 'ignore', // hide the backend console window
    })

    backendProcess.on('error', (err) => {
      console.error('Backend failed to start:', err)
    })

    backendProcess.on('exit', (code) => {
      console.log('Backend exited with code:', code)
    })
  } else {
    console.log('Dev mode: assuming backend is already running on port 8001')
  }
}

// ── Create the main app window ───────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'DocPilot',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
    show: false,  // Don't show until ready to avoid flash of white
  })

  const isPackaged = app.isPackaged

  if (isPackaged) {
    // In packaged app: __dirname = resources/app/electron/
    // so dist is at: resources/app/dist/index.html
    const indexPath = path.join(__dirname, '..', 'dist', 'index.html')
    console.log('Loading index from:', indexPath)
    mainWindow.loadFile(indexPath).catch((err) => {
      console.error('Failed to load index.html:', err)
    })
  } else {
    // In development: load from Vite dev server
    mainWindow.loadURL('http://localhost:5173')
  }

  // Show window when content is ready (avoids white flash)
  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  // Open external links in the real browser, not Electron window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Also prevent will-navigate from sending the Electron window to any external
  // URL (e.g., if something uses window.location.href instead of window.open).
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const isLocalDevServer = url.startsWith('http://localhost:5173')
    const isLocalBackend = url.startsWith('http://localhost:8001') || url.startsWith('http://127.0.0.1:8001')
    const isFileUrl = url.startsWith('file://')
    if (!isLocalDevServer && !isLocalBackend && !isFileUrl) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}


// ── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  startBackend()

  // Wait 2 seconds for backend to fully start before showing the window
  const delay = app.isPackaged ? 2500 : 0
  setTimeout(createWindow, delay)

  const initialProtocolUrl = process.argv.find((arg) => arg.startsWith(`${protocol}://`))
  if (initialProtocolUrl) {
    app.whenReady().then(() => setTimeout(() => openAuthenticatedWindow(initialProtocolUrl), delay + 100))
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('second-instance', (_event, commandLine) => {
  const protocolUrl = commandLine.find((arg) => arg.startsWith(`${protocol}://`))
  if (protocolUrl) openAuthenticatedWindow(protocolUrl)
  else if (mainWindow) {
    mainWindow.show()
    mainWindow.focus()
  }
})

app.on('window-all-closed', () => {
  // Kill the backend process when the app is closed
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
  }
})
