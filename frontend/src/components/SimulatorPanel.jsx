import React, { useState, useEffect } from 'react';
import { X, Play, RefreshCw, AlertTriangle, ShieldCheck, Zap, Radio } from 'lucide-react';
import axios from 'axios';

export default function SimulatorPanel({ isOpen, onClose, onRefresh }) {
  const [dts, setDts] = useState([]);
  const [selectedDt, setSelectedDt] = useState('');
  const [poles, setPoles] = useState([]);
  const [selectedSpanFrom, setSelectedSpanFrom] = useState('');
  const [selectedSpanTo, setSelectedSpanTo] = useState('');
  const [selectedNoiseType, setSelectedNoiseType] = useState('duplicate');
  const [loading, setLoading] = useState(false);
  const [log, setLog] = useState(null);

  useEffect(() => {
    if (isOpen) {
      axios.get('/api/simulate/dts').then((res) => {
        setDts(res.data);
        if (res.data.length > 0) {
          setSelectedDt(res.data[0].dt_id);
        }
      });
    }
  }, [isOpen]);

  useEffect(() => {
    if (selectedDt) {
      axios.get(`/api/simulate/dts/${selectedDt}/poles`).then((res) => {
        setPoles(res.data);
        if (res.data.length >= 2) {
          setSelectedSpanFrom(res.data[0].pole_id);
          setSelectedSpanTo(res.data[1].pole_id);
        }
      });
    }
  }, [selectedDt]);

  if (!isOpen) return null;

  const runSimulation = async (endpoint, payload) => {
    setLoading(true);
    setLog(null);
    try {
      const res = await axios.post(`/api/simulate/${endpoint}`, payload);
      setLog({ type: 'success', text: res.data.note });
      onRefresh();
    } catch (err) {
      setLog({ type: 'error', text: err.response?.data?.detail || 'Simulation failed' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      bottom: '80px',
      left: '24px',
      width: '420px',
      backgroundColor: 'var(--bg-card)',
      border: '1px solid var(--border-color)',
      borderRadius: '12px',
      boxShadow: '0 20px 50px rgba(0,0,0,0.6)',
      zIndex: 1000,
      padding: '1.25rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '1rem' }}>
          <Zap style={{ color: '#3b82f6' }} size={20} /> Digital Twin Fault Simulator
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <X size={18} />
        </button>
      </div>

      {/* Target DT Picker */}
      <div>
        <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.35rem' }}>
          TARGET TRANSFORMER (DT)
        </label>
        <select
          value={selectedDt}
          onChange={(e) => setSelectedDt(e.target.value)}
          style={{ width: '100%', padding: '0.5rem', backgroundColor: '#0f172a', color: 'white', border: '1px solid var(--border-color)', borderRadius: '6px' }}
        >
          {dts.map((dt) => (
            <option key={dt.dt_id} value={dt.dt_id}>
              {dt.dt_id} ({dt.pole_count} poles) — {dt.topology_source}
            </option>
          ))}
        </select>
      </div>

      {/* Simulation Scenario Buttons */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <button
          onClick={() => runSimulation('span-fault', { dt_id: selectedDt, span_from_pole_id: selectedSpanFrom, span_to_pole_id: selectedSpanTo })}
          disabled={loading}
          style={{ padding: '0.6rem', backgroundColor: '#ef4444', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Play size={14} /> 1. Inject Span Fault (Boundary Detection)
        </button>

        <button
          onClick={() => runSimulation('dt-fault', { dt_id: selectedDt })}
          disabled={loading}
          style={{ padding: '0.6rem', backgroundColor: '#f97316', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Play size={14} /> 2. Inject DT Fault (Entire Transformer Dark)
        </button>

        <button
          onClick={() => runSimulation('device-failure', { pole_id: selectedSpanFrom })}
          disabled={loading}
          style={{ padding: '0.6rem', backgroundColor: '#eab308', color: '#0f172a', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <AlertTriangle size={14} /> 3. Inject Dead Sensor (Should NOT Create Ticket)
        </button>

        <button
          onClick={() => runSimulation('noise', { dt_id: selectedDt, noise_type: selectedNoiseType })}
          disabled={loading}
          style={{ padding: '0.6rem', backgroundColor: '#64748b', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Radio size={14} /> 4. Inject Duplicate/Stale Noise
        </button>
      </div>

      {/* Output Log */}
      {log && (
        <div style={{
          padding: '0.75rem',
          borderRadius: '6px',
          fontSize: '0.75rem',
          backgroundColor: log.type === 'error' ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)',
          color: log.type === 'error' ? '#f87171' : '#4ade80',
          border: log.type === 'error' ? '1px solid #ef4444' : '1px solid #22c55e',
          lineHeight: 1.4,
        }}>
          {log.text}
        </div>
      )}
    </div>
  );
}
