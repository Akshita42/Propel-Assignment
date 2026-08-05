import React from 'react';
import { Zap, AlertTriangle, CheckCircle, Radio, Cpu, Volume2, VolumeX } from 'lucide-react';

export default function Navbar({ stats, sseConnected, soundMuted, onToggleSound }) {
  return (
    <header className="navbar">
      <div className="brand">
        <Zap className="brand-icon" size={24} />
        <div>
          <div className="brand-title">KSPDB Fault Localizer</div>
          <div className="brand-subtitle">Karnataka State Power Distribution Board — SD-07</div>
        </div>
      </div>

      <div className="stats-bar">
        <div className="stat-item">
          <span className="stat-value" style={{ color: stats.active_incidents > 0 ? '#ef4444' : '#22c55e' }}>
            {stats.active_incidents || 0}
          </span>
          <span className="stat-label">Active Incidents</span>
        </div>

        <div className="stat-item">
          <span className="stat-value" style={{ color: '#22c55e' }}>
            {stats.live_poles || 0}
          </span>
          <span className="stat-label">Live Poles</span>
        </div>

        <div className="stat-item">
          <span className="stat-value" style={{ color: stats.dark_poles > 0 ? '#ef4444' : '#94a3b8' }}>
            {stats.dark_poles || 0}
          </span>
          <span className="stat-label">Dark Poles</span>
        </div>

        <div className="stat-item">
          <span className="stat-value" style={{ color: stats.device_failures > 0 ? '#eab308' : '#94a3b8' }}>
            {stats.device_failures || 0}
          </span>
          <span className="stat-label">Device Anomalies</span>
        </div>

        <div className="stat-item" style={{ borderLeft: '1px solid var(--border-color)', paddingLeft: '1.25rem' }}>
          <span className="stat-value" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem' }}>
            <Radio size={14} style={{ color: sseConnected ? '#22c55e' : '#ef4444' }} />
            {sseConnected ? 'LIVE STREAM' : 'OFFLINE'}
          </span>
          <span className="stat-label">Telemetry Feed</span>
        </div>

        <button
          onClick={onToggleSound}
          title={soundMuted ? 'Unmute alert audio' : 'Mute alert audio'}
          style={{
            background: 'none',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            color: soundMuted ? '#64748b' : '#3b82f6',
            padding: '0.4rem',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginLeft: '0.5rem',
          }}
        >
          {soundMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
      </div>
    </header>
  );
}
