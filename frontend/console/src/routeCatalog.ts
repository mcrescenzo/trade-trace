import rawRouteCatalog from './routeCatalog.json'

export type ConsoleRouteComponent =
  | 'overview'
  | 'trades'
  | 'catalog'
  | 'report'
  | 'process'
  | 'strategies'
  | 'playbooks'
  | 'events'
  | 'decisions'

export type ConsoleIconName =
  | 'Activity'
  | 'BarChart3'
  | 'BookOpen'
  | 'Boxes'
  | 'Gauge'
  | 'ListFilter'
  | 'NotebookText'
  | 'ShieldCheck'
  | 'TableProperties'

export type ConsoleRouteDefinition = {
  path: string
  label: string
  icon: ConsoleIconName
  component: ConsoleRouteComponent
  title?: string
  tool?: string
  endpoint?: string
  args?: Record<string, unknown>
}

export const consoleRouteCatalog = rawRouteCatalog as readonly ConsoleRouteDefinition[]

export const visibleConsoleRoutes = consoleRouteCatalog.map((route) => route.path)

export const primaryNavRoutes = consoleRouteCatalog.filter(
  (route) => !route.path.startsWith('/reports/')
)
