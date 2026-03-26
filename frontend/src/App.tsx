import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/Layout/Layout";
import DashboardPage from "@/pages/DashboardPage";
import MarketPage from "@/pages/MarketPage";
import MemoPage from "@/pages/MemoPage";
import ResultsPage from "@/pages/ResultsPage";
import UnderwritePage from "@/pages/UnderwritePage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/underwrite" replace />} />
        <Route path="/underwrite" element={<UnderwritePage />} />
        <Route path="/results/:dealId" element={<ResultsPage />} />
        <Route path="/market" element={<MarketPage />} />
        <Route path="/memo/:dealId" element={<MemoPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
      </Route>
    </Routes>
  );
}
