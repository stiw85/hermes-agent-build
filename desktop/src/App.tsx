import { IconPlugConnectedX, IconRefresh, IconSettings } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { EmptyGlass, GlassButton } from './components/glass.tsx'
import { ConfirmHost, ToastHost } from './components/overlays.tsx'
import { Sidebar, TitleBar, type PageId } from './components/Shell.tsx'
import { Wallpaper } from './components/Wallpaper.tsx'
import { trader, useBackendState, usePoll, type Status } from './lib/api.ts'
import { StatusContext } from './lib/status.ts'
import { BrainPage } from './pages/Brain.tsx'
import { JournalPage } from './pages/Journal.tsx'
import { MarketsPage } from './pages/Markets.tsx'
import { OverviewPage } from './pages/Overview.tsx'
import { SettingsPage } from './pages/Settings.tsx'
import { StrategiesPage } from './pages/Strategies.tsx'

function Offline({ onSettings }: { onSettings: () => void }) {
  const backend = useBackendState()
  const [busy, setBusy] = useState(false)
  const starting = backend?.phase === 'starting'
  return (
    <div className="flex h-full items-center justify-center p-10">
      <EmptyGlass
        className="glass w-[560px] border-solid"
        icon={<IconPlugConnectedX />}
        title={starting ? 'Starting the trading backend…' : 'Not connected to the trading backend'}
        description={
          starting ? (
            'Launching hermes-trader serve. This takes a few seconds the first time.'
          ) : (
            <span className="selectable">{backend?.error ?? 'The backend is stopped.'}</span>
          )
        }
        action={
          !starting && (
            <div className="flex gap-2">
              <GlassButton
                variant="primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  await trader().backendRestart()
                  setBusy(false)
                }}
              >
                <IconRefresh /> Retry
              </GlassButton>
              <GlassButton onClick={onSettings}>
                <IconSettings /> Settings
              </GlassButton>
            </div>
          )
        }
      />
    </div>
  )
}

export function App() {
  const [page, setPage] = useState<PageId>('overview')
  const backend = useBackendState()
  const ready = backend?.phase === 'ready'
  const { data: status, refresh } = usePoll<Status>(ready ? '/api/status' : null, 3000)

  useEffect(() => {
    if (ready) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready])

  const body = (() => {
    if (page === 'settings') return <SettingsPage />
    if (!ready) return <Offline onSettings={() => setPage('settings')} />
    switch (page) {
      case 'overview':
        return <OverviewPage onPage={setPage} />
      case 'markets':
        return <MarketsPage />
      case 'strategies':
        return <StrategiesPage />
      case 'journal':
        return <JournalPage />
      case 'brain':
        return <BrainPage />
    }
  })()

  return (
    <ToastHost>
      <ConfirmHost>
        <StatusContext.Provider value={{ status: ready ? status : null, refresh }}>
          <Wallpaper />
          <div className="relative flex h-full flex-col">
            <TitleBar status={ready ? status : null} />
            <div className="flex min-h-0 flex-1 gap-3 px-3 pb-3">
              <Sidebar page={page} onPage={setPage} status={ready ? status : null} backend={backend} />
              <main key={page} className="glass page-enter min-w-0 flex-1 overflow-hidden rounded-2xl">
                {body}
              </main>
            </div>
          </div>
        </StatusContext.Provider>
      </ConfirmHost>
    </ToastHost>
  )
}
