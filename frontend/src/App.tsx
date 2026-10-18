import { Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/ui";
import { EventExplorer } from "./pages/EventExplorer";
import { ExperimentLab } from "./pages/ExperimentLab";
import { Incidents } from "./pages/Incidents";
import { Investigation } from "./pages/Investigation";
import { Overview } from "./pages/Overview";
import { Policies } from "./pages/Policies";
import { RecoveryVault } from "./pages/RecoveryVault";
import { ReplayLab } from "./pages/ReplayLab";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/investigation" element={<Investigation />} />
        <Route path="/investigation/:incidentId" element={<Investigation />} />
        <Route path="/replay" element={<ReplayLab />} />
        <Route path="/experiment" element={<ExperimentLab />} />
        <Route path="/policies" element={<Policies />} />
        <Route path="/recovery" element={<RecoveryVault />} />
        <Route path="/events" element={<EventExplorer />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<EmptyState title="Page not found"><Link className="text-accent-300 underline" to="/">Back to overview</Link></EmptyState>} />
      </Routes>
    </Layout>
  );
}
