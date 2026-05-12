import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import SetupPage from "./pages/SetupPage";
import ProfilePage from "./pages/ProfilePage";
import MilestonePage from "./pages/MilestonePage";
import UsersPage from "./pages/UsersPage";
import LeaderboardPage from "./pages/LeaderboardPage";
import RecruitPage from "./pages/RecruitPage";
import AdvisorPage from "./pages/AdvisorPage";
import AdvisorChatPage from "./pages/AdvisorChatPage";
import MentionsFeedPage from "./pages/MentionsFeedPage";
import DocsPage from "./pages/DocsPage";

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

function NavLink({ to, current, label }: { to: string; current: string; label: string }) {
  const active = current === to || current.startsWith(to + "/");
  return (
    <Link
      to={to}
      className={`relative rounded-lg px-3 py-1.5 text-sm font-medium transition ${
        active
          ? "bg-indigo-50 text-indigo-700"
          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
      }`}
    >
      {label}
      {active && (
        <motion.span
          layoutId="nav-pill"
          className="absolute inset-0 rounded-lg border border-indigo-200"
          transition={{ type: "spring", stiffness: 380, damping: 30 }}
        />
      )}
    </Link>
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
        <div className="flex items-center gap-1">
          <NavLink to="/leaderboard" current={location.pathname} label="排行榜" />
          <NavLink to="/recruit" current={location.pathname} label="人才查询" />
          <NavLink to="/advisor" current={location.pathname} label="保研导师" />
          <NavLink to="/advisor/chat" current={location.pathname} label="导师推荐 AI" />
          <NavLink to="/advisor/mentions" current={location.pathname} label="口碑墙" />
          <NavLink to="/users" current={location.pathname} label="用户列表" />
          <NavLink to="/docs" current={location.pathname} label="文档" />
          {isHome && (
            <span className="ml-2 text-xs text-gray-400 border-l border-gray-200 pl-3">
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
        <Route path="/leaderboard" element={<LeaderboardPage />} />
        <Route path="/recruit" element={<RecruitPage />} />
        <Route path="/advisor" element={<AdvisorPage />} />
        <Route path="/advisor/chat" element={<AdvisorChatPage />} />
        <Route path="/advisor/mentions" element={<MentionsFeedPage />} />
        <Route path="/advisor/schools/:schoolId" element={<AdvisorPage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/profile/:id" element={<ProfilePage />} />
        <Route path="/milestones/:id" element={<MilestonePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
