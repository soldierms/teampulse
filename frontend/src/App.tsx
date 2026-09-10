import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { PersonDetail } from "./pages/PersonDetail";
import { Settings } from "./pages/Settings";
import { TeamDetail } from "./pages/TeamDetail";
import { Spinner } from "./components/ui";

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
          isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export function App() {
  const { user, loading, logout } = useAuth();

  if (loading) return <Spinner />;
  if (!user) return <Login />;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-6 py-3">
          <span className="text-lg font-semibold">TeamPulse</span>
          <nav className="flex gap-1">
            <NavItem to="/">Overview</NavItem>
            <NavItem to="/settings">Settings</NavItem>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
            <span>{user.name}</span>
            <button
              type="button"
              onClick={logout}
              className="rounded-lg border border-slate-300 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/teams/:teamId" element={<TeamDetail />} />
          <Route path="/people/:userId" element={<PersonDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
