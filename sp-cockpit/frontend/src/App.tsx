import { Link, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import EventList from "./pages/EventList";
import TraceDetail from "./pages/TraceDetail";
import Search from "./pages/Search";
import Repositories from "./pages/Repositories";
import RepoDetail from "./pages/RepoDetail";
import ProjectSelector, { ProjectProvider } from "./components/ProjectSelector";

export default function App() {
  return (
    <ProjectProvider>
      <div className="min-h-screen text-slate-800">
        <nav className="bg-white border-b shadow-sm px-6 py-3 flex gap-6 items-center">
          <Link to="/" className="font-semibold text-slate-900">SourcePilot Cockpit</Link>
          <ProjectSelector />
          <Link to="/" className="hover:text-blue-600">Dashboard</Link>
          <Link to="/events" className="hover:text-blue-600">Events</Link>
          <Link to="/search" className="hover:text-blue-600">Search</Link>
          <Link to="/repos" className="hover:text-blue-600">Repositories</Link>
        </nav>
        <main className="p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/events" element={<EventList />} />
            <Route path="/trace/:traceId" element={<TraceDetail />} />
            <Route path="/search" element={<Search />} />
            <Route path="/repos" element={<Repositories />} />
            <Route path="/repos/:id" element={<RepoDetail />} />
            <Route path="*" element={
              <div className="text-center py-20">
                <h1 className="text-4xl font-bold text-slate-300 mb-4">404</h1>
                <p className="text-slate-500 mb-4">Page not found</p>
                <Link to="/" className="text-blue-600 hover:underline">Back to Dashboard</Link>
              </div>
            } />
          </Routes>
        </main>
      </div>
    </ProjectProvider>
  );
}
