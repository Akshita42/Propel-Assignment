import React, { useEffect, useState, useMemo } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';

// Fix default marker icons in Leaflet React
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom Fault Pin Icon (for DT / Feeder level faults)
const faultIcon = new L.DivIcon({
  className: 'custom-fault-marker',
  html: `<div style="
    background-color: #ef4444;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 3px solid #ffffff;
    box-shadow: 0 0 15px #ef4444;
    animation: pulse 1.5s infinite;
  "></div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

// Component to handle map view reset when incident selected
function RecenterMap({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) {
      map.flyTo(center, 16, { duration: 1.2 });
    }
  }, [center, map]);
  return null;
}

export default function NetworkMap({ poles, dts, incidents, topoEdges = [], selectedIncident, onSelectIncident }) {
  // Default map center: Bangalore South subdivision
  const defaultCenter = [12.9352, 77.5831];
  const [mapCenter, setMapCenter] = useState(defaultCenter);

  useEffect(() => {
    if (selectedIncident && selectedIncident.fault_lat && selectedIncident.fault_lon) {
      setMapCenter([selectedIncident.fault_lat, selectedIncident.fault_lon]);
    }
  }, [selectedIncident]);

  // Build a quick lookup: pole_id → {lat, lon}
  const poleCoords = useMemo(() => {
    const map = {};
    poles.forEach((p) => { map[p.pole_id] = { lat: p.lat, lon: p.lon }; });
    return map;
  }, [poles]);

  // Compute wire lines (grey polylines) from topology edges
  const wireLines = useMemo(() => {
    return topoEdges
      .map((edge) => {
        const from = poleCoords[edge.parent_id];
        const to = poleCoords[edge.child_id];
        if (!from || !to) return null;
        return {
          key: `${edge.parent_id}-${edge.child_id}`,
          positions: [[from.lat, from.lon], [to.lat, to.lon]],
        };
      })
      .filter(Boolean);
  }, [topoEdges, poleCoords]);

  // Compute fault span lines (bold red) for SPAN incidents
  const spanFaultLines = useMemo(() => {
    return incidents
      .filter(
        (inc) =>
          inc.fault_type === 'SPAN' &&
          inc.span_from_pole_id &&
          inc.span_to_pole_id
      )
      .map((inc) => {
        const from = poleCoords[inc.span_from_pole_id];
        const to = poleCoords[inc.span_to_pole_id];
        if (!from || !to) return null;
        const isSelected = selectedIncident && selectedIncident.id === inc.id;
        return {
          key: inc.id,
          inc,
          positions: [[from.lat, from.lon], [to.lat, to.lon]],
          isSelected,
        };
      })
      .filter(Boolean);
  }, [incidents, poleCoords, selectedIncident]);

  return (
    <div className="map-container">
      <MapContainer
        center={defaultCenter}
        zoom={14}
        scrollWheelZoom={true}
        style={{ width: '100%', height: '100%' }}
      >
        <RecenterMap center={mapCenter} />

        {/* Free OpenStreetMap tiles — no API key needed */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Wire network lines (grey, drawn first so they appear under poles) */}
        {wireLines.map((line) => (
          <Polyline
            key={line.key}
            positions={line.positions}
            pathOptions={{
              color: '#334155',
              weight: 1.5,
              opacity: 0.7,
            }}
          />
        ))}

        {/* Span Fault Lines — bold red between the two boundary poles */}
        {spanFaultLines.map((line) => (
          <Polyline
            key={line.key}
            positions={line.positions}
            pathOptions={{
              color: '#ef4444',
              weight: line.isSelected ? 7 : 5,
              opacity: 0.95,
              dashArray: '10, 6',
            }}
            eventHandlers={{
              click: () => onSelectIncident(line.inc),
            }}
          >
            <Popup>
              <div style={{ padding: '6px', maxWidth: '220px' }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ef4444', textTransform: 'uppercase' }}>
                  ⚡ Span Fault
                </div>
                <div style={{ fontSize: '0.75rem', marginTop: '4px', color: '#1e293b' }}>
                  DT: {line.inc.dt_id}<br />
                  From: <strong>{line.inc.span_from_pole_id}</strong><br />
                  To: <strong style={{ color: '#ef4444' }}>{line.inc.span_to_pole_id}</strong><br />
                  Poles affected: <strong>{line.inc.affected_pole_count}</strong><br />
                  Confidence: <strong>{line.inc.confidence_level} ({(line.inc.confidence_score * 100).toFixed(0)}%)</strong>
                </div>
              </div>
            </Popup>
          </Polyline>
        ))}

        {/* DT Markers */}
        {dts.map((dt) => (
          <CircleMarker
            key={dt.dt_id}
            center={[dt.lat, dt.lon]}
            radius={8}
            pathOptions={{
              fillColor: '#3b82f6',
              fillOpacity: 0.9,
              color: '#ffffff',
              weight: 2,
            }}
          >
            <Popup>
              <div style={{ padding: '4px' }}>
                <strong style={{ fontSize: '0.9rem', color: '#3b82f6' }}>DT: {dt.dt_id}</strong>
                <div style={{ fontSize: '0.8rem', marginTop: '4px', color: '#94a3b8' }}>
                  Feeder: {dt.feeder_id}<br />
                  Capacity: {dt.capacity_kva || 'N/A'} kVA<br />
                  Households: {dt.households_served || 'N/A'}<br />
                  Topology Source: <strong style={{ color: dt.topology_source === 'GOLD' ? '#22c55e' : '#eab308' }}>{dt.topology_source}</strong>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Pole Markers */}
        {poles.map((pole) => {
          let fillColor = '#22c55e'; // LIVE
          if (pole.last_state === 'DARK') fillColor = '#ef4444';
          if (pole.last_state === 'UNKNOWN') fillColor = '#94a3b8';
          if (pole.last_state === 'DEVICE_FAILURE') fillColor = '#eab308';

          return (
            <CircleMarker
              key={pole.pole_id}
              center={[pole.lat, pole.lon]}
              radius={4}
              pathOptions={{
                fillColor: fillColor,
                fillOpacity: 0.85,
                color: pole.last_state === 'DARK' ? '#ef4444' : '#1e293b',
                weight: pole.last_state === 'DARK' ? 2 : 1,
              }}
            >
              <Popup>
                <div style={{ padding: '4px' }}>
                  <strong style={{ fontSize: '0.85rem' }}>Pole: {pole.pole_id}</strong>
                  <div style={{ fontSize: '0.75rem', marginTop: '4px', color: '#94a3b8' }}>
                    Status: <strong style={{ color: fillColor }}>{pole.last_state}</strong><br />
                    DT: {pole.dt_id}<br />
                    Ward: {pole.ward || 'N/A'} (PIN {pole.pincode || 'N/A'})<br />
                    Device: {pole.has_device ? (pole.is_legacy_firmware ? 'Legacy (fw 1.2.x)' : 'Active') : 'No Device fitted'}
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}

        {/* Fault Location Pins — only for DT/FEEDER faults (SPAN faults are shown as lines above) */}
        {incidents.map((inc) => {
          if (inc.fault_type === 'SPAN') return null; // shown as red polyline
          if (!inc.fault_lat || !inc.fault_lon) return null;

          return (
            <Marker
              key={inc.id}
              position={[inc.fault_lat, inc.fault_lon]}
              icon={faultIcon}
              eventHandlers={{
                click: () => onSelectIncident(inc),
              }}
            >
              <Popup>
                <div style={{ padding: '6px', maxWidth: '220px' }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ef4444', textTransform: 'uppercase' }}>
                    🚨 {inc.fault_type} Fault
                  </div>
                  <div style={{ fontSize: '0.75rem', marginTop: '4px', color: '#f8fafc' }}>
                    DT: {inc.dt_id}<br />
                    Poles affected: <strong>{inc.affected_pole_count}</strong><br />
                    Confidence: <strong>{inc.confidence_level} ({(inc.confidence_score * 100).toFixed(0)}%)</strong>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}
