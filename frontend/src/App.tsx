// Route table and shared party state.

import { Route, Routes } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { SearchResultsPage } from "./pages/SearchResultsPage";
import { PartyProvider } from "./context/PartyContext";

export default function App() {
  return (
    <PartyProvider>
      <div className="app">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchResultsPage />} />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </div>
    </PartyProvider>
  );
}
