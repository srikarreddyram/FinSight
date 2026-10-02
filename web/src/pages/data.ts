// Data loading and links shared by the dashboard pages.
import { useEffect, useState } from 'react'

export function useData<T>(load: () => Promise<T>, key = ''): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null })
  useEffect(() => {
    let live = true
    setState({ data: null, error: null })
    load()
      .then((data) => live && setState({ data, error: null }))
      .catch((e: Error) => live && setState({ data: null, error: e.message }))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

export function link(path: string): string {
  return `#${path}`
}
