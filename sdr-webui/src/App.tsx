import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { runtimeApi, openEventSocket } from './api';
import { StatusBadge } from './components/StatusBadge';
import type { Activity, Channel, RadioCapabilities, RadioState, RuntimeEvent, Scanner, Stream } from './types';

type ChannelFormState = {
  label: string;
  frequency_hz: number;
  modulation: 'NFM' | 'AM' | 'WFM';
  bandwidth_hz: number;
  audio_rate_hz: number;
  squelch_threshold_db: number;
  squelch_hang_ms: number;
  audio_activity_threshold_dbfs: number;
  activity_attack_ms: number;
  activity_release_ms: number;
  minimum_active_ms: number;
  priority: number;
  enabled: boolean;
};

type ScannerFormState = {
  name: string;
  frequencies_hz: string;
  modulation: 'NFM' | 'AM' | 'WFM';
  bandwidth_hz: number;
  dwell_ms: number;
  hold_ms: number;
  resume_delay_ms: number;
  priority_frequencies_hz: string;
  mode: 'retune' | 'in_band';
  protect_fixed_channels: boolean;
};

const defaultChannel: ChannelFormState = {
  label: '',
  frequency_hz: 162400000,
  modulation: 'NFM',
  bandwidth_hz: 12500,
  audio_rate_hz: 16000,
  squelch_threshold_db: -70,
  squelch_hang_ms: 400,
  audio_activity_threshold_dbfs: -35,
  activity_attack_ms: 120,
  activity_release_ms: 650,
  minimum_active_ms: 500,
  priority: 100,
  enabled: true,
};

const defaultScanner: ScannerFormState = {
  name: '',
  frequencies_hz: '162400000,162550000',
  modulation: 'NFM',
  bandwidth_hz: 12500,
  dwell_ms: 600,
  hold_ms: 3000,
  resume_delay_ms: 800,
  priority_frequencies_hz: '',
  mode: 'retune',
  protect_fixed_channels: true,
};

export function App() {
  const [connected, setConnected] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<RadioCapabilities | null>(null);
  const [radioState, setRadioState] = useState<RadioState | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [scanners, setScanners] = useState<Scanner[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [channelForm, setChannelForm] = useState<ChannelFormState>(defaultChannel);
  const [scannerForm, setScannerForm] = useState<ScannerFormState>(defaultScanner);
  const [editingChannelId, setEditingChannelId] = useState<string | null>(null);
  const [editingScannerId, setEditingScannerId] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [health, readyData, caps, radio, ch, sc, act, st, evt] = await Promise.all([
        runtimeApi.fetchHealth(),
        runtimeApi.fetchReady(),
        runtimeApi.fetchCapabilities(),
        runtimeApi.fetchRadioState(),
        runtimeApi.fetchChannels(),
        runtimeApi.fetchScanners(),
        runtimeApi.fetchActivities(),
        runtimeApi.fetchStreams(),
        runtimeApi.fetchEvents(),
      ]);
      setConnected(health.status === 'ok');
      setReady(Boolean(readyData.data && readyData.data.status === 'ready'));
      setCapabilities(caps);
      setRadioState(radio);
      setChannels(ch);
      setScanners(sc);
      setActivities(act);
      setStreams(st);
      setEvents(evt.slice().reverse());
      setError(null);
    } catch (err) {
      setConnected(false);
      setReady(false);
      setError(err instanceof Error ? err.message : 'Runtime unavailable');
    }
  };

  useEffect(() => {
    refresh();
    const socket = openEventSocket(
      (event) => {
        setEvents((current) => [event, ...current].slice(0, 50));
        refresh();
      },
      (status) => setConnected(status),
    );
    const interval = window.setInterval(refresh, 15000);
    return () => {
      socket.close();
      window.clearInterval(interval);
    };
  }, []);

  const streamByChannel = useMemo(() => {
    const map = new Map<string, Stream>();
    streams.forEach((stream) => map.set(stream.channel_id, stream));
    return map;
  }, [streams]);

  const summary = {
    channels: channels.length,
    scanners: scanners.length,
    activeEvents: activities.filter((activity) => activity.state === 'active').length,
  };

  async function submitChannel(event: FormEvent) {
    event.preventDefault();
    const payload = { ...channelForm };
    try {
      if (editingChannelId) {
        await runtimeApi.updateChannel(editingChannelId, payload);
      } else {
        await runtimeApi.createChannel(payload);
      }
      setChannelForm(defaultChannel);
      setEditingChannelId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save channel');
    }
  }

  async function submitScanner(event: FormEvent) {
    event.preventDefault();
    const payload = {
      ...scannerForm,
      frequencies_hz: scannerForm.frequencies_hz.split(',').map((v) => Number(v.trim())).filter(Boolean),
      priority_frequencies_hz: scannerForm.priority_frequencies_hz.split(',').map((v) => Number(v.trim())).filter(Boolean),
    };
    try {
      if (editingScannerId) {
        await runtimeApi.updateScanner(editingScannerId, payload);
      } else {
        await runtimeApi.createScanner(payload);
      }
      setScannerForm(defaultScanner);
      setEditingScannerId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save scanner');
    }
  }

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">SDR Monitoring Platform</p>
          <h1>Operator Dashboard</h1>
          <p className="subtle">Public API endpoint: {runtimeApi.apiBase}</p>
        </div>
        <div className="status-row">
          <StatusBadge tone={connected ? 'green' : 'red'} label={connected ? 'Connected' : 'Disconnected'} />
          <StatusBadge tone={ready ? 'green' : 'yellow'} label={ready ? 'Ready' : 'Not Ready'} />
        </div>
      </header>

      {error && <section className="panel error-banner">{error}</section>}

      <section className="grid summary-grid">
        <article className="panel summary-card"><span>Channels</span><strong>{summary.channels}</strong></article>
        <article className="panel summary-card"><span>Scanners</span><strong>{summary.scanners}</strong></article>
        <article className="panel summary-card"><span>Active Events</span><strong>{summary.activeEvents}</strong></article>
      </section>

      <section className="grid two-col">
        <article className="panel">
          <div className="section-title"><h2>Runtime Status</h2><button onClick={refresh}>Refresh</button></div>
          {radioState && capabilities ? (
            <dl className="kv-grid">
              <div><dt>Device</dt><dd>{capabilities.device_name}</dd></div>
              <div><dt>Serial</dt><dd>{capabilities.serial}</dd></div>
              <div><dt>Driver</dt><dd>{capabilities.driver}</dd></div>
              <div><dt>Center</dt><dd>{radioState.center_frequency_hz.toLocaleString()} Hz</dd></div>
              <div><dt>Sample Rate</dt><dd>{radioState.sample_rate_hz.toLocaleString()} Hz</dd></div>
              <div><dt>Antenna</dt><dd>{radioState.antenna}</dd></div>
              <div><dt>Gain</dt><dd>{radioState.gain_mode} / {radioState.gain_db} dB</dd></div>
              <div><dt>Bandwidth</dt><dd>{radioState.bandwidth_hz.toLocaleString()} Hz</dd></div>
            </dl>
          ) : <p>Waiting for runtime…</p>}
        </article>
        <article className="panel">
          <h2>Capabilities</h2>
          {capabilities ? (
            <div className="cap-grid">
              <div>
                <h3>Frequency Range</h3>
                <p>{capabilities.frequency_range.min_hz.toLocaleString()} - {capabilities.frequency_range.max_hz.toLocaleString()} Hz</p>
              </div>
              <div>
                <h3>Antennas</h3>
                <p>{capabilities.antennas.join(', ')}</p>
              </div>
              <div>
                <h3>Sample Rates</h3>
                <p>{capabilities.supported_sample_rates_hz.map((v) => v.toLocaleString()).join(', ')}</p>
              </div>
              <div>
                <h3>Bandwidths</h3>
                <p>{capabilities.bandwidth_options_hz.map((v) => v.toLocaleString()).join(', ')}</p>
              </div>
              <div>
                <h3>Modulations</h3>
                <p>{capabilities.supported_modulations.join(', ')}</p>
              </div>
              <div>
                <h3>Gain Controls</h3>
                <p>{capabilities.gain_controls.map((g) => `${g.name} ${g.min_db}-${g.max_db} dB`).join(', ')}</p>
              </div>
            </div>
          ) : <p>No capability data yet.</p>}
        </article>
      </section>

      <section className="grid two-col">
        <article className="panel">
          <div className="section-title"><h2>{editingChannelId ? 'Edit Channel' : 'Add Channel'}</h2></div>
          <form className="form-grid" onSubmit={submitChannel}>
            <label>Label<input value={channelForm.label} onChange={(e) => setChannelForm({ ...channelForm, label: e.target.value })} /></label>
            <label>Frequency (Hz)<input type="number" value={channelForm.frequency_hz} onChange={(e) => setChannelForm({ ...channelForm, frequency_hz: Number(e.target.value) })} required /></label>
            <label>Modulation<select value={channelForm.modulation} onChange={(e) => setChannelForm({ ...channelForm, modulation: e.target.value as ChannelFormState['modulation'] })}><option>NFM</option><option>AM</option><option>WFM</option></select></label>
            <label>Bandwidth (Hz)<input type="number" value={channelForm.bandwidth_hz} onChange={(e) => setChannelForm({ ...channelForm, bandwidth_hz: Number(e.target.value) })} required /></label>
            <label>Audio Rate (Hz)<input type="number" value={channelForm.audio_rate_hz} onChange={(e) => setChannelForm({ ...channelForm, audio_rate_hz: Number(e.target.value) })} required /></label>
            <label>Squelch (dB)<input type="number" value={channelForm.squelch_threshold_db} onChange={(e) => setChannelForm({ ...channelForm, squelch_threshold_db: Number(e.target.value) })} /></label>
            <label>Squelch Hang (ms)<input type="number" value={channelForm.squelch_hang_ms} onChange={(e) => setChannelForm({ ...channelForm, squelch_hang_ms: Number(e.target.value) })} /></label>
            <label>Audio Threshold (dBFS)<input type="number" value={channelForm.audio_activity_threshold_dbfs} onChange={(e) => setChannelForm({ ...channelForm, audio_activity_threshold_dbfs: Number(e.target.value) })} /></label>
            <label>Attack (ms)<input type="number" value={channelForm.activity_attack_ms} onChange={(e) => setChannelForm({ ...channelForm, activity_attack_ms: Number(e.target.value) })} /></label>
            <label>Release (ms)<input type="number" value={channelForm.activity_release_ms} onChange={(e) => setChannelForm({ ...channelForm, activity_release_ms: Number(e.target.value) })} /></label>
            <label>Minimum Active (ms)<input type="number" value={channelForm.minimum_active_ms} onChange={(e) => setChannelForm({ ...channelForm, minimum_active_ms: Number(e.target.value) })} /></label>
            <label>Priority<input type="number" value={channelForm.priority} onChange={(e) => setChannelForm({ ...channelForm, priority: Number(e.target.value) })} /></label>
            <label className="checkbox"><input type="checkbox" checked={channelForm.enabled} onChange={(e) => setChannelForm({ ...channelForm, enabled: e.target.checked })} /> Enabled</label>
            <div className="actions">
              <button type="submit">{editingChannelId ? 'Update Channel' : 'Create Channel'}</button>
              {editingChannelId && <button type="button" className="ghost" onClick={() => { setEditingChannelId(null); setChannelForm(defaultChannel); }}>Cancel</button>}
            </div>
          </form>
        </article>

        <article className="panel">
          <div className="section-title"><h2>Channels</h2></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Label</th><th>ID</th><th>Frequency</th><th>Mode</th><th>BW</th><th>Squelch</th><th>Status</th><th>Stream</th><th>Last Active</th><th>Actions</th></tr></thead>
              <tbody>
                {channels.map((channel) => (
                  <tr key={channel.id}>
                    <td>{channel.label || '—'}</td>
                    <td>{channel.id}</td>
                    <td>{channel.frequency_hz.toLocaleString()}</td>
                    <td>{channel.modulation}</td>
                    <td>{channel.bandwidth_hz.toLocaleString()}</td>
                    <td>{channel.squelch_threshold_db} dB</td>
                    <td><StatusBadge tone={channel.status === 'active' ? 'green' : channel.enabled ? 'blue' : 'gray'} label={`${channel.enabled ? 'Enabled' : 'Disabled'} / ${channel.status}`} /></td>
                    <td>{streamByChannel.get(channel.id)?.state || 'idle'}</td>
                    <td>{channel.last_active_at ? new Date(channel.last_active_at).toLocaleString() : '—'}</td>
                    <td>
                      <div className="inline-actions">
                        <button type="button" onClick={() => { setEditingChannelId(channel.id); setChannelForm({ ...defaultChannel, ...channel, label: channel.label || '' }); }}>Edit</button>
                        <button type="button" className="ghost" onClick={() => runtimeApi.updateChannel(channel.id, { enabled: !channel.enabled }).then(refresh)}>Toggle</button>
                        <button type="button" className="ghost" onClick={() => runtimeApi.updateChannel(channel.id, { muted: !channel.muted }).then(refresh)}>{channel.muted ? 'Unmute' : 'Mute'}</button>
                        <button type="button" className="danger" onClick={() => runtimeApi.deleteChannel(channel.id).then(refresh)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="grid two-col">
        <article className="panel">
          <div className="section-title"><h2>{editingScannerId ? 'Edit Scanner' : 'Create Scanner'}</h2></div>
          <form className="form-grid" onSubmit={submitScanner}>
            <label>Name<input value={scannerForm.name} onChange={(e) => setScannerForm({ ...scannerForm, name: e.target.value })} required /></label>
            <label>Frequencies<input value={scannerForm.frequencies_hz} onChange={(e) => setScannerForm({ ...scannerForm, frequencies_hz: e.target.value })} placeholder="162400000,162550000" required /></label>
            <label>Modulation<select value={scannerForm.modulation} onChange={(e) => setScannerForm({ ...scannerForm, modulation: e.target.value as ScannerFormState['modulation'] })}><option>NFM</option><option>AM</option><option>WFM</option></select></label>
            <label>Bandwidth (Hz)<input type="number" value={scannerForm.bandwidth_hz} onChange={(e) => setScannerForm({ ...scannerForm, bandwidth_hz: Number(e.target.value) })} required /></label>
            <label>Dwell (ms)<input type="number" value={scannerForm.dwell_ms} onChange={(e) => setScannerForm({ ...scannerForm, dwell_ms: Number(e.target.value) })} required /></label>
            <label>Hold (ms)<input type="number" value={scannerForm.hold_ms} onChange={(e) => setScannerForm({ ...scannerForm, hold_ms: Number(e.target.value) })} required /></label>
            <label>Resume Delay (ms)<input type="number" value={scannerForm.resume_delay_ms} onChange={(e) => setScannerForm({ ...scannerForm, resume_delay_ms: Number(e.target.value) })} required /></label>
            <label>Priority Frequencies<input value={scannerForm.priority_frequencies_hz} onChange={(e) => setScannerForm({ ...scannerForm, priority_frequencies_hz: e.target.value })} placeholder="optional comma-separated" /></label>
            <label>Mode<select value={scannerForm.mode} onChange={(e) => setScannerForm({ ...scannerForm, mode: e.target.value as ScannerFormState['mode'] })}><option value="retune">retune</option><option value="in_band">in_band</option></select></label>
            <label className="checkbox"><input type="checkbox" checked={scannerForm.protect_fixed_channels} onChange={(e) => setScannerForm({ ...scannerForm, protect_fixed_channels: e.target.checked })} /> Protect fixed channels</label>
            <div className="actions">
              <button type="submit">{editingScannerId ? 'Update Scanner' : 'Create Scanner'}</button>
              {editingScannerId && <button type="button" className="ghost" onClick={() => { setEditingScannerId(null); setScannerForm(defaultScanner); }}>Cancel</button>}
            </div>
          </form>
        </article>
        <article className="panel">
          <div className="section-title"><h2>Scanners</h2></div>
          <div className="scanner-list">
            {scanners.map((scanner) => (
              <div className="scanner-card" key={scanner.id}>
                <div className="scanner-header">
                  <div>
                    <h3>{scanner.name}</h3>
                    <p>{scanner.id}</p>
                  </div>
                  <StatusBadge tone={scanner.running ? 'green' : 'gray'} label={scanner.running ? 'Running' : 'Stopped'} />
                </div>
                <p>Frequencies: {scanner.frequencies_hz.join(', ')}</p>
                <p>Mode: {scanner.mode} · Dwell {scanner.dwell_ms} ms · Hold {scanner.hold_ms} ms</p>
                <div className="inline-actions">
                  <button type="button" onClick={() => { setEditingScannerId(scanner.id); setScannerForm({
                    name: scanner.name,
                    frequencies_hz: scanner.frequencies_hz.join(','),
                    modulation: scanner.modulation,
                    bandwidth_hz: scanner.bandwidth_hz,
                    dwell_ms: scanner.dwell_ms,
                    hold_ms: scanner.hold_ms,
                    resume_delay_ms: scanner.resume_delay_ms,
                    priority_frequencies_hz: scanner.priority_frequencies_hz.join(','),
                    mode: scanner.mode,
                    protect_fixed_channels: scanner.protect_fixed_channels,
                  }); }}>Edit</button>
                  <button type="button" className="ghost" onClick={() => (scanner.running ? runtimeApi.stopScanner(scanner.id) : runtimeApi.startScanner(scanner.id)).then(refresh)}>{scanner.running ? 'Stop' : 'Start'}</button>
                  <button type="button" className="danger" onClick={() => runtimeApi.deleteScanner(scanner.id).then(refresh)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid two-col">
        <article className="panel">
          <h2>Live Events</h2>
          <div className="event-feed">
            {events.slice(0, 12).map((event, index) => (
              <div className="event-item" key={`${event.timestamp}-${index}`}>
                <div>
                  <strong>{event.event_type}</strong>
                  <p>{new Date(event.timestamp).toLocaleString()}</p>
                </div>
                <div>
                  <p>channel: {event.channel_id || '—'}</p>
                  <p>scanner: {event.scanner_id || '—'}</p>
                  <p>activity: {event.activity_id || '—'}</p>
                </div>
              </div>
            ))}
          </div>
        </article>
        <article className="panel">
          <h2>Activities</h2>
          <div className="event-feed">
            {activities.slice().reverse().slice(0, 12).map((activity) => (
              <div className="event-item" key={activity.id}>
                <div>
                  <strong>{activity.channel_label || activity.channel_id}</strong>
                  <p>{activity.frequency_hz.toLocaleString()} Hz</p>
                </div>
                <div>
                  <p>{activity.state}</p>
                  <p>{activity.duration_ms ? `${activity.duration_ms} ms` : 'live'}</p>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}
