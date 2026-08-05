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
  const [topoEdges, setTopoEdges] = useState([]); // {parent_id, child_id, dt_id}
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);
  const [soundMuted, setSoundMuted] = useState(false);

  // Web Audio synthesis for control-room incident alert chime
  const playAlertChime = useCallback(() => {
    if (soundMuted) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
      osc.frequency.exponentialRampToValueAtTime(880.00, ctx.currentTime + 0.15); // A5
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch (err) {
      // Audio context suppressed by un-interacted browser policy
    }
  }, [soundMuted]);

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

      setIncidents((prev) => {
        if (incidentsRes.data.length > prev.length) {
          playAlertChime();
        }
        return incidentsRes.data;
      });

      // Fetch topology edges for all DTs (to draw wire lines on the map)
      const dtIds = dtsRes.data.map((d) => d.dt_id);
      const topoResults = await Promise.all(
        dtIds.map((dtId) => axios.get(`/api/network/topology/${dtId}`).catch(() => null))
      );
      const allEdges = [];
      topoResults.forEach((res, i) => {
        if (res && res.data && res.data.edges) {
          res.data.edges.forEach((edge) => {
            allEdges.push({ ...edge, dt_id: dtIds[i] });
          });
        }
      });
      setTopoEdges(allEdges);
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

    // Generic fallback for un-named events
    eventSource.onmessage = (event) => {
      fetchData();
    };

    // Named events sent by backend via broadcast_sse_event()
    const sseEvents = [
      'incident_created',
      'incident_updated',
      'incident_verified',
      'telemetry_update',
    ];
    sseEvents.forEach((evtName) => {
      eventSource.addEventListener(evtName, () => fetchData());
    });

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

  // Called by SimulatorPanel after injecting a fault.
  // The backend runs fault detection as a background task, so we do an
  // immediate refresh + a delayed one to catch the newly-created incident.
  const handleSimulatorRefresh = useCallback(() => {
    fetchData();
    setTimeout(fetchData, 1500);
    setTimeout(fetchData, 3500);
  }, [fetchData]);

  return (
    <div className="app-container">
      {/* Top Header Navbar */}
      <Navbar
        stats={stats}
        sseConnected={sseConnected}
        soundMuted={soundMuted}
        onToggleSound={() => setSoundMuted((m) => !m)}
      />

      {/* Main Workspace (Map + Incident Sidebar) */}
      <div className="main-content">
        <NetworkMap
          poles={poles}
          dts={dts}
          incidents={incidents}
          topoEdges={topoEdges}
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
        onRefresh={handleSimulatorRefresh}
      />
    </div>
  );
}
