import React, { useState } from 'react';
import { X, Bot, AlertTriangle, ShieldCheck, UserCheck, Wrench, CheckCircle, Navigation } from 'lucide-react';

export default function IncidentDetailModal({ incident, onClose, onUpdateStatus }) {
  const [errorMsg, setErrorMsg] = useState(null);
  const [loading, setLoading] = useState(false);

  if (!incident) return null;

  const handleStatusChange = async (newStatus) => {
    setErrorMsg(null);
    setLoading(true);
    try {
      await onUpdateStatus(incident.id, newStatus);
    } catch (err) {
      if (err.response && err.response.data && err.response.data.detail) {
        const detail = err.response.data.detail;
        setErrorMsg(typeof detail === 'object' ? detail.message : detail);
      } else {
        setErrorMsg('Failed to update status.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'absolute',
      right: '420px',
      top: 0,
      bottom: 0,
      width: '450px',
      backgroundColor: 'var(--bg-card)',
      borderLeft: '1px solid var(--border-color)',
      boxShadow: '-10px 0 30px rgba(0,0,0,0.5)',
      zIndex: 600,
      display: 'flex',
      flexDirection: 'column',
      overflowY: 'auto',
    }}>
      {/* Header */}
      <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span style={{ fontSize: '0.7rem', color: '#ef4444', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            INCIDENT DETAILS
          </span>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginTop: '0.2rem' }}>
            {incident.fault_type} Fault — DT {incident.dt_id}
          </h2>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
          <X size={20} />
        </button>
      </div>

      <div style={{ padding: '1.25rem', flex: 1 }}>
        {/* Navigation Coordinates Banner */}
        <div style={{ background: '#1e293b', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#3b82f6', fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.35rem' }}>
            <Navigation size={16} /> GPS Dispatch Target
          </div>
          <p style={{ fontSize: '0.95rem', fontWeight: 700, color: '#f8fafc', fontFamily: 'monospace' }}>
            {incident.fault_lat?.toFixed(6)}° N, {incident.fault_lon?.toFixed(6)}° E
          </p>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            PIN {incident.pincode || '560078'} • Ward {incident.ward || 'W-084'}
          </p>
        </div>

        {/* Gemini AI Summary */}
        <div style={{ background: 'rgba(168, 85, 247, 0.1)', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: '8px', padding: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#a855f7', fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>
            <Bot size={16} /> Gemini AI Dispatch Summary
          </div>
          <p style={{ fontSize: '0.825rem', color: '#e9d5ff', lineHeight: 1.5 }}>
            {incident.ai_summary || 'Generating summary...'}
          </p>
        </div>

        {/* Telemetry Verification Guard Error Notice */}
        {errorMsg && (
          <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', borderRadius: '8px', padding: '1rem', marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#ef4444', fontWeight: 700, fontSize: '0.85rem', marginBottom: '0.35rem' }}>
              <AlertTriangle size={16} /> Resolution Blocked by Telemetry Guard
            </div>
            <p style={{ fontSize: '0.8rem', color: '#f87171', lineHeight: 1.4 }}>
              {errorMsg}
            </p>
          </div>
        )}

        {/* Status Lifecycle Controls */}
        <div style={{ marginTop: '1.5rem' }}>
          <h3 style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
            WORKFLOW ACTIONS
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {incident.status === 'DETECTED' && (
              <button
                onClick={() => handleStatusChange('ACKNOWLEDGED')}
                disabled={loading}
                style={{ padding: '0.65rem', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
              >
                <UserCheck size={16} /> Acknowledge Incident
              </button>
            )}

            {incident.status === 'ACKNOWLEDGED' && (
              <button
                onClick={() => handleStatusChange('CREW_ASSIGNED')}
                disabled={loading}
                style={{ padding: '0.65rem', background: '#a855f7', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
              >
                <Wrench size={16} /> Assign Crew to Field
              </button>
            )}

            {(incident.status === 'CREW_ASSIGNED' || incident.status === 'ACKNOWLEDGED') && (
              <button
                onClick={() => handleStatusChange('RESOLVED')}
                disabled={loading}
                style={{ padding: '0.65rem', background: 'var(--bg-card-hover)', color: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}
              >
                <CheckCircle size={16} /> Mark Fixed (Requires Telemetry Verification)
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
