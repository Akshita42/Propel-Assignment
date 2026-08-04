import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

import Navbar from './components/Navbar';
import NetworkMap from './components/NetworkMap';
import IncidentList from './components/IncidentList';
import IncidentDetailModal from './components/IncidentDetailModal';
import SimulatorPanel from './components/SimulatorPanel';
import { Sliders } from 'lucide-react';
import './App.css';

export default function App() {
  const [stats, setStats] = useState({});
  const [poles, setPoles] = useState([]);
  const [dts, setDts] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);

  // Fetch initial state
  const fetchData = useCallback(async () => {
    try {
      const [statsRes, polesRes, dtsRes, incidentsRes] = await Promise.all([
        axios.get('/api/network/stats'),
        axios.get('/api/network/poles'),
        axios.get('/api/network/dts'),
        axios.get('/api/incidents/active'),
      ]);

      setStats(statsRes.data);
      setPoles(polesRes.data);
      setDts(dtsRes.data);
      setIncidents(incidentsRes.data);
    } catch (err) {
      console.error('Error fetching grid data:', err);
    }
  }, []);

  useEffect(() => {
    fetchData();

    // Setup SSE Real-time Telemetry Stream
    const eventSource = new EventSource('/api/sse');

    eventSource.onopen = () => {
      setSseConnected(true);
    };

    eventSource.onmessage = (event) => {
      // Re-fetch state whenever telemetry update arrives
      fetchData();
    };

    eventSource.onerror = (err) => {
      setSseConnected(false);
    };

    return () => {
      eventSource.close();
    };
  }, [fetchData]);

  const handleUpdateStatus = async (incidentId, newStatus) => {
    await axios.patch(`/api/incidents/${incidentId}/status`, { status: newStatus });
    fetchData();
    if (selectedIncident && selectedIncident.id === incidentId) {
      const updated = await axios.get(`/api/incidents/${incidentId}`);
      setSelectedIncident(updated.data);
    }
  };

  return (
    <div className="app-container">
      {/* Top Header Navbar */}
      <Navbar stats={stats} sseConnected={sseConnected} />

      {/* Main Workspace (Map + Incident Sidebar) */}
      <div className="main-content">
        <NetworkMap
          poles={poles}
          dts={dts}
          incidents={incidents}
          selectedIncident={selectedIncident}
          onSelectIncident={setSelectedIncident}
        />

        <IncidentList
          incidents={incidents}
          selectedIncident={selectedIncident}
          onSelectIncident={setSelectedIncident}
        />

        {/* Selected Incident Detail Drawer */}
        {selectedIncident && (
          <IncidentDetailModal
            incident={selectedIncident}
            onClose={() => setSelectedIncident(null)}
            onUpdateStatus={handleUpdateStatus}
          />
        )}
      </div>

      {/* Floating Digital Twin Simulator FAB */}
      <button className="simulator-fab" onClick={() => setSimulatorOpen(!simulatorOpen)}>
        <Sliders size={18} />
        {simulatorOpen ? 'Close Simulator' : 'Open Fault Simulator'}
      </button>

      {/* Simulator Control Drawer */}
      <SimulatorPanel
        isOpen={simulatorOpen}
        onClose={() => setSimulatorOpen(false)}
        onRefresh={fetchData}
      />
    </div>
  );
}
