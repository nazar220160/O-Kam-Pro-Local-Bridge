export type ConnectionMode = "lan" | "cloud";
export type Quality = "high" | "medium" | "low" | null;
export interface AccountInfo {
  username: string;
  camera_count: number;
}
export interface Credentials {
  username: string;
  password: string;
}
export type ExportCredentials = Credentials;
export interface Health {
  ok: boolean;
  version: string;
  persistence: { enabled: boolean; error: string | null };
}
export interface LensMetadata {
  id: number;
  codec?: string;
  width?: number;
  height?: number;
  reported_fps?: number;
  measured_fps?: number;
  bitrate_kbps?: number;
  frames_received?: number;
  bytes_received?: number;
  last_frame?: number | null;
  preview_width?: number | null;
}
export interface Camera {
  id: string;
  name: string;
  device_id: string;
  state: string;
  error: string | null;
  ip: string | null;
  substream: number;
  quality: Quality;
  connection_mode: ConnectionMode;
  transport: { mode?: ConnectionMode; path?: string | null };
  viewable: boolean;
  capability: string;
  protocol: string | null;
  lenses: number[];
  lens_metadata: LensMetadata[];
  metadata: Record<string, unknown>;
  account_metadata: Record<string, unknown>;
  viewers: number;
  last_frame: number | null;
  connections: number;
}
export interface StreamPreferences {
  ip?: string | null;
  substream: number;
  quality: Quality;
  connection_mode: ConnectionMode;
}
export interface ControlResult {
  state: string;
  result?: number | null;
  parameters?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface Capability {
  available: boolean | null;
  evidence: Record<string, unknown>;
}
export interface CameraDetails {
  groups: Record<string, Record<string, unknown>>;
  queries: Record<string, ControlResult>;
  capabilities: Record<string, Capability>;
  account?: Record<string, unknown>;
}
export interface NativeServices {
  camera_id: string;
  ip: string;
  ports: { port: number; open: boolean; [key: string]: unknown }[];
  capabilities: Record<string, Capability>;
  protocol_verified: boolean;
  configuration: Record<
    string,
    {
      writable: boolean;
      supported?: boolean | null;
      enabled?: boolean | null;
      reason?: string;
    }
  >;
  instructions?: string[];
  references?: string[];
  probe_type?: string;
}
export interface ExportProfile {
  lens: number;
  token: string;
  width?: number;
  height?: number;
  fps?: number;
  rtsp_uri: string;
  snapshot_uri: string;
}
export interface ExportStatus {
  enabled: boolean;
  available: boolean;
  reason?: string;
  state?: string;
  error?: string | null;
  export_id?: string;
  advertise_host?: string;
  rtsp_port?: number;
  onvif_port?: number;
  rtsp?: boolean;
  onvif?: boolean;
  onvif_uri?: string | null;
  profiles?: ExportProfile[];
  discovery_error?: string | null;
  audio?: { available: boolean; codec?: string };
  ptz?: boolean;
}
export interface ArchiveRecord {
  token: string;
  source: string;
  lens: number;
  start?: string;
  duration?: number;
  bytes?: number;
  [key: string]: unknown;
}
export interface SDRecord {
  id: string;
  filename?: string;
  start?: string;
  timestamp?: string | number;
  duration?: number;
  [key: string]: unknown;
}
export interface ArchiveStatus {
  recording_enabled: boolean;
  workers: {
    lens: number;
    running: boolean;
    error?: string | null;
    segment_seconds?: number;
  }[];
  records: ArchiveRecord[];
  storage: {
    count?: number;
    bytes?: number;
    retention_days?: number;
    max_bytes?: number;
  };
  jobs: {
    id: string;
    state: string;
    error?: string | null;
    records?: ArchiveRecord[];
  }[];
}
