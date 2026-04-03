import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import SetupPage from "./pages/SetupPage";
import ProfilePage from "./pages/ProfilePage";
import MilestonePage from "./pages/MilestonePage";
import UsersPage from "./pages/UsersPage";

function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="logoBg" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#a855f7" />
        </linearGradient>
        <linearGradient id="logoBar" x1="0" y1="48" x2="0" y2="16" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#c4b5fd" />
          <stop offset="100%" stopColor="#ffffff" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#logoBg)" />
      <rect x="12" y="36" width="8" height="16" rx="2" fill="url(#logoBar)" opacity="0.7" />
      <rect x="24" y="28" width="8" height="24" rx="2" fill="url(#logoBar)" opacity="0.85" />
      <rect x="36" y="20" width="8" height="32" rx="2" fill="url(#logoBar)" opacity="0.95" />
      <circle cx="50" cy="16" r="5" fill="#fbbf24" />
      <line x1="40" y1="20" x2="46" y2="18" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" opacity="0.8" />
    </svg>
  );
}

function TopBar() {
  const location = useLocation();
  const isHome = location.pathname === "/";

  return (
    <header className="sticky top-0 z-50 border-b border-gray-200/60 bg-white/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2.5">
        <Link to="/" className="flex items-center gap-2.5 transition hover:opacity-80">
          <motion.div
            whileHover={{ rotate: [0, -8, 8, -4, 0], scale: 1.1 }}
            transition={{ duration: 0.5 }}
          >
            <Logo size={30} />
          </motion.div>
          <span className="text-lg font-bold tracking-tight text-gray-900">
            Impact<span className="text-indigo-600">Hub</span>
          </span>
        </Link>
        <div className="flex items-center gap-4">
          <Link
            to="/users"
            className="text-sm text-gray-500 transition hover:text-indigo-600"
          >
            用户列表
          </Link>
          {isHome && (
            <span className="text-xs text-gray-400">
              科研影响力看板
            </span>
          )}
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <TopBar />
      <Routes>
        <Route path="/" element={<SetupPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/profile/:id" element={<ProfilePage />} />
        <Route path="/milestones/:id" element={<MilestonePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
