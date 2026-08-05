import React, { useState, useEffect } from 'react';
import { AlertCircle, ShieldAlert, Clock, MapPin, Users, ChevronRight, CheckCircle2 } from 'lucide-react';
import { formatDistanceToNow, differenceInMinutes } from 'date-fns';

export default function IncidentList({ incidents, selectedIncident, onSelectIncident }) {
  const [now, setNow] = useState(new Date());

  // 1-second live ticker update for SLA elapsed timer
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const getAgeSlaColor = (createdAt) => {
    const mins = differenceInMinutes(now, new Date(createdAt));
    if (mins >= 30) return { color: '#ef4444', label: `${mins}m (OVERDUE)`, isUrgent: true };
    if (mins >= 15) return { color: '#eab308', label: `${mins}m elapsed`, isUrgent: false };
    return { color: 'var(--text-muted)', label: formatDistanceToNow(new Date(createdAt), { addSuffix: true }), isUrgent: false };
  };

  return (
    <div className="sidebar">
      <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1rem', fontWeight: 700 }}>Incident Queue</h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Sorted by severity & households affected
          </span>
        </div>
        <span style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#ef4444', padding: '0.2rem 0.6rem', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700 }}>
          {incidents.length} OPEN
        </span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem' }}>
        {incidents.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
            <CheckCircle2 size={40} style={{ color: 'var(--color-green)', marginBottom: '0.75rem' }} />
            <p style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Grid Fully Energized</p>
            <p style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>No active electrical faults detected.</p>
          </div>
        ) : (
          incidents.map((inc) => {
            const isSelected = selectedIncident && selectedIncident.id === inc.id;
            const sla = getAgeSlaColor(inc.created_at);

            // Confidence / Status Traffic Light Badge
            let badgeClass = 'badge-high';
            let confidenceText = 'Confirmed Span';
            if (inc.status === 'SUPPRESSED' || inc.is_suppressed) {
              badgeClass = 'badge-suppressed';
              confidenceText = 'Planned Outage';
            } else if (inc.confidence_level === 'MEDIUM') {
              badgeClass = 'badge-medium';
              confidenceText = 'Estimated Zone';
            } else if (inc.confidence_level === 'LOW') {
              badgeClass = 'badge-low';
              confidenceText = 'DT Fallback';
            }

            return (
              <div
                key={inc.id}
                onClick={() => onSelectIncident(inc)}
                style={{
                  backgroundColor: isSelected ? 'var(--bg-card-hover)' : 'var(--bg-card)',
                  border: isSelected ? '1px solid var(--color-blue)' : '1px solid var(--border-color)',
                  borderRadius: '8px',
                  padding: '1rem',
                  marginBottom: '0.75rem',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  position: 'relative',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span className={`badge ${badgeClass}`}>
                    {confidenceText} ({(inc.confidence_score * 100).toFixed(0)}%)
                  </span>
                  <span style={{ fontSize: '0.7rem', color: sla.color, fontWeight: sla.isUrgent ? 700 : 400, display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Clock size={12} />
                    {sla.label}
                  </span>
                </div>

                <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.35rem' }}>
                  {inc.fault_type} Fault — DT {inc.dt_id}
                </h3>

                {inc.span_from_pole_id && inc.span_to_pole_id ? (
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                    Span: <strong style={{ color: '#f8fafc' }}>{inc.span_from_pole_id}</strong> → <strong style={{ color: '#ef4444' }}>{inc.span_to_pole_id}</strong>
                  </p>
                ) : (
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                    Location: DT {inc.dt_id} transformer line
                  </p>
                )}

                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <MapPin size={12} />
                    PIN {inc.pincode || '560078'} ({inc.ward || 'W-084'})
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Users size={12} />
                    {inc.affected_pole_count} poles ({inc.households_affected || inc.affected_pole_count * 5} houses)
                  </span>
                </div>

                <ChevronRight size={16} style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
