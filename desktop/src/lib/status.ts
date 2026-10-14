import { createContext, useContext } from 'react'
import type { Status } from './api.ts'

export interface StatusCtx {
  status: Status | null
  refresh: () => void
}

export const StatusContext = createContext<StatusCtx>({ status: null, refresh: () => undefined })

export function useStatus(): StatusCtx {
  return useContext(StatusContext)
}
