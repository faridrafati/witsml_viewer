import { Route, Routes } from 'react-router-dom';
import { Alert, Box, Typography } from '@mui/material';
import { Layout } from './pages/Layout';
import { WellsPage } from './pages/WellsPage';
import { DashboardPage } from './pages/DashboardPage';
import { PagesPage } from './pages/PagesPage';
import { ComparisonPage } from './pages/ComparisonPage';

function Placeholder({ title }: { title: string }) {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Alert severity="info">This section is coming in a later phase.</Alert>
    </Box>
  );
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<WellsPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/pages" element={<PagesPage />} />
        <Route path="/comparison" element={<ComparisonPage />} />
        <Route path="/formulas" element={<Placeholder title="Formulas" />} />
        <Route path="/reports" element={<Placeholder title="Reports" />} />
        <Route path="/admin" element={<Placeholder title="Admin" />} />
        <Route path="*" element={<Placeholder title="Not Found" />} />
      </Routes>
    </Layout>
  );
}
