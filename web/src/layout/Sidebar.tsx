import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/topics', label: 'Topics' },
  { to: '/digests', label: 'Digests' },
  { to: '/drafts', label: 'Drafts' },
  { to: '/idea-validation', label: 'Idea Validation' },
  { to: '/eval', label: 'Eval' },
]

export function Sidebar() {
  return (
    <nav className="w-56 shrink-0 border-r border-surface-border bg-surface-raised p-4">
      <div className="mb-6 px-2 text-sm font-semibold tracking-wide text-gray-200">
        X Hype Finder
      </div>
      <ul className="space-y-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-pipeline-bg text-pipeline border border-pipeline-border'
                    : 'text-gray-400 hover:bg-surface hover:text-gray-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
