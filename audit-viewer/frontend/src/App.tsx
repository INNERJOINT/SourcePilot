import { Link, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import EventList from "./pages/EventList";
import TraceDetail from "./pages/TraceDetail";
import Search from "./pages/Search";

export default function App() {
  return (
    <div className="min-h-screen text-slate-800">
      <nav className="bg-white border-b shadow-sm px-6 py-3 flex gap-6">
        <Link to="/" className="font-semibold text-slate-900">Audit Viewer</Link>
        <Link to="/" className="hover:text-blue-600">Dashboard</Link>
        <Link to="/events" className="hover:text-blue-600">Events</Link>
        <Link to="/search" className="hover:text-blue-600">Search</Link>
      </nav>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/events" element={<EventList />} />
          <Route path="/trace/:traceId" element={<TraceDetail />} />
          <Route path="/search" element={<Search />} />
        </Routes>
      </main>
    </div>
  );
}
