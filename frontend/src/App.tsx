import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import BatchesPage from "./pages/BatchesPage";
import WaferListPage from "./pages/WaferListPage";
import WaferMapPage from "./pages/WaferMapPage";
import DieDetailPage from "./pages/DieDetailPage";
import JobsPage from "./pages/JobsPage";
import RulesPage from "./pages/RulesPage";

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>二极管参数提取</h1>
        <nav>
          <NavLink to="/batches">批次与晶圆</NavLink>
          <NavLink to="/jobs">作业进度</NavLink>
          <NavLink to="/rules">规则版本</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/batches" replace />} />
          <Route path="/batches" element={<BatchesPage />} />
          <Route path="/batches/:batchId" element={<WaferListPage />} />
          <Route path="/wafers/:waferId" element={<WaferMapPage />} />
          <Route
            path="/wafers/:waferId/dies/:x/:y"
            element={<DieDetailPage />}
          />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:waferId" element={<JobsPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/rules/:waferId" element={<RulesPage />} />
        </Routes>
      </main>
    </div>
  );
}
