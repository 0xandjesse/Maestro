// ============================================================
// Maestro — Google Calendar Integration
// ============================================================
//
// Provides read, write, and push-notification access to the
// Sovereign Swarm shared calendar via OAuth2 refresh token flow.
//
// All agents share the same credentials. Access control is
// handled at the credential level — store gcal-credentials.json
// securely and only give agents access who need it.
//
// Usage:
//   const gcal = new GoogleCalendar(credentials);
//   const events = await gcal.listUpcoming();
//   await gcal.createEvent({ title: 'Sprint review', start: ..., end: ... });
// ============================================================

import https from 'https';

export interface GCalCredentials {
  client_id: string;
  client_secret: string;
  refresh_token: string;
  calendar_id: string;
  token_uri: string;
  scope: string;
  project_id: string;
}

export interface GCalEvent {
  id?: string;
  title: string;
  description?: string;
  start: string; // ISO 8601
  end: string;   // ISO 8601
  attendees?: string[]; // email addresses
  location?: string;
}

export interface GCalEventRaw {
  id: string;
  summary: string;
  description?: string;
  start: { dateTime?: string; date?: string };
  end: { dateTime?: string; date?: string };
  attendees?: Array<{ email: string; displayName?: string }>;
  location?: string;
  status: string;
  htmlLink: string;
}

export interface ListEventsOptions {
  maxResults?: number;
  timeMin?: string; // ISO 8601, defaults to now
  timeMax?: string; // ISO 8601
  query?: string;   // free-text search
}

export interface WatchChannelOptions {
  /** Your HTTPS endpoint that will receive push notifications */
  webhookUrl: string;
  /** Channel ID — unique string you generate */
  channelId: string;
  /** Token to validate incoming notifications (optional) */
  token?: string;
  /** TTL in seconds. Max 604800 (1 week). Default: 86400 (1 day) */
  ttlSeconds?: number;
}

export interface WatchChannelResult {
  id: string;
  resourceId: string;
  resourceUri: string;
  expiration: string; // ms timestamp as string
}

export class GoogleCalendar {
  private accessToken: string | null = null;
  private tokenExpiry: number = 0;

  constructor(private creds: GCalCredentials) {}

  // ----------------------------------------------------------
  // Auth
  // ----------------------------------------------------------

  private async getAccessToken(): Promise<string> {
    if (this.accessToken && Date.now() < this.tokenExpiry - 60_000) {
      return this.accessToken;
    }

    const params = new URLSearchParams({
      client_id: this.creds.client_id,
      client_secret: this.creds.client_secret,
      refresh_token: this.creds.refresh_token,
      grant_type: 'refresh_token',
    });

    const data = await this.post('oauth2.googleapis.com', '/token', params.toString(), {
      'Content-Type': 'application/x-www-form-urlencoded',
    });

    const parsed = JSON.parse(data) as { access_token: string; expires_in: number; error?: string };
    if (parsed.error || !parsed.access_token) {
      throw new Error(`GCal auth failed: ${JSON.stringify(parsed)}`);
    }

    this.accessToken = parsed.access_token;
    this.tokenExpiry = Date.now() + parsed.expires_in * 1000;
    return this.accessToken;
  }

  // ----------------------------------------------------------
  // Events
  // ----------------------------------------------------------

  /** List upcoming events. Defaults to next 10 events from now. */
  async listUpcoming(options: ListEventsOptions = {}): Promise<GCalEvent[]> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);

    const params = new URLSearchParams({
      maxResults: String(options.maxResults ?? 10),
      timeMin: options.timeMin ?? new Date().toISOString(),
      orderBy: 'startTime',
      singleEvents: 'true',
    });

    if (options.timeMax) params.set('timeMax', options.timeMax);
    if (options.query) params.set('q', options.query);

    const data = await this.get(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events?${params}`,
      token,
    );

    const parsed = JSON.parse(data) as { items?: GCalEventRaw[]; error?: unknown };
    if (parsed.error) throw new Error(`GCal listEvents error: ${JSON.stringify(parsed.error)}`);

    return (parsed.items ?? []).map(this.normalizeEvent);
  }

  /** Get a single event by ID. */
  async getEvent(eventId: string): Promise<GCalEvent> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);
    const data = await this.get(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events/${encodeURIComponent(eventId)}`,
      token,
    );
    const parsed = JSON.parse(data) as GCalEventRaw & { error?: unknown };
    if (parsed.error) throw new Error(`GCal getEvent error: ${JSON.stringify(parsed.error)}`);
    return this.normalizeEvent(parsed);
  }

  /** Create a new event. */
  async createEvent(event: GCalEvent): Promise<GCalEvent> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);

    const body = JSON.stringify({
      summary: event.title,
      description: event.description,
      location: event.location,
      start: { dateTime: event.start },
      end: { dateTime: event.end },
      attendees: event.attendees?.map(email => ({ email })),
    });

    const data = await this.postJson(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events`,
      body,
      token,
    );

    const parsed = JSON.parse(data) as GCalEventRaw & { error?: unknown };
    if (parsed.error) throw new Error(`GCal createEvent error: ${JSON.stringify(parsed.error)}`);
    return this.normalizeEvent(parsed);
  }

  /** Update an existing event. Partial update — only provided fields are changed. */
  async updateEvent(eventId: string, updates: Partial<GCalEvent>): Promise<GCalEvent> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);

    const body: Record<string, unknown> = {};
    if (updates.title !== undefined) body['summary'] = updates.title;
    if (updates.description !== undefined) body['description'] = updates.description;
    if (updates.location !== undefined) body['location'] = updates.location;
    if (updates.start !== undefined) body['start'] = { dateTime: updates.start };
    if (updates.end !== undefined) body['end'] = { dateTime: updates.end };
    if (updates.attendees !== undefined) body['attendees'] = updates.attendees.map(email => ({ email }));

    const data = await this.patch(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events/${encodeURIComponent(eventId)}`,
      JSON.stringify(body),
      token,
    );

    const parsed = JSON.parse(data) as GCalEventRaw & { error?: unknown };
    if (parsed.error) throw new Error(`GCal updateEvent error: ${JSON.stringify(parsed.error)}`);
    return this.normalizeEvent(parsed);
  }

  /** Delete an event by ID. */
  async deleteEvent(eventId: string): Promise<void> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);
    await this.delete(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events/${encodeURIComponent(eventId)}`,
      token,
    );
  }

  // ----------------------------------------------------------
  // ACL (sharing)
  // ----------------------------------------------------------

  /** Share the calendar with a Google account. Role: 'reader' | 'writer' | 'owner' */
  async shareWith(email: string, role: 'reader' | 'writer' | 'owner'): Promise<void> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);
    const body = JSON.stringify({ role, scope: { type: 'user', value: email } });
    const data = await this.postJson(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/acl`,
      body,
      token,
    );
    const parsed = JSON.parse(data) as { error?: unknown };
    if (parsed.error) throw new Error(`GCal shareWith error: ${JSON.stringify(parsed.error)}`);
  }

  // ----------------------------------------------------------
  // Push notifications (watch)
  // ----------------------------------------------------------

  /**
   * Subscribe to push notifications for calendar changes.
   * Google will POST to webhookUrl whenever an event is created/updated/deleted.
   * The channel expires — re-register before expiration to maintain continuity.
   */
  async watchCalendar(options: WatchChannelOptions): Promise<WatchChannelResult> {
    const token = await this.getAccessToken();
    const calId = encodeURIComponent(this.creds.calendar_id);

    const body = JSON.stringify({
      id: options.channelId,
      type: 'web_hook',
      address: options.webhookUrl,
      token: options.token,
      params: {
        ttl: String(options.ttlSeconds ?? 86400),
      },
    });

    const data = await this.postJson(
      'www.googleapis.com',
      `/calendar/v3/calendars/${calId}/events/watch`,
      body,
      token,
    );

    const parsed = JSON.parse(data) as WatchChannelResult & { error?: unknown };
    if (parsed.error) throw new Error(`GCal watch error: ${JSON.stringify(parsed.error)}`);
    return parsed;
  }

  /** Stop a watch channel before it expires. */
  async stopWatch(channelId: string, resourceId: string): Promise<void> {
    const token = await this.getAccessToken();
    const body = JSON.stringify({ id: channelId, resourceId });
    await this.postJson('www.googleapis.com', '/calendar/v3/channels/stop', body, token);
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private normalizeEvent(raw: GCalEventRaw): GCalEvent {
    return {
      id: raw.id,
      title: raw.summary ?? '(no title)',
      description: raw.description,
      start: raw.start.dateTime ?? raw.start.date ?? '',
      end: raw.end.dateTime ?? raw.end.date ?? '',
      attendees: raw.attendees?.map(a => a.email),
      location: raw.location,
    };
  }

  private get(hostname: string, path: string, token: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const req = https.request({
        hostname, path, method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
      }, res => {
        let data = '';
        res.on('data', d => data += d);
        res.on('end', () => resolve(data));
      });
      req.on('error', reject);
      req.end();
    });
  }

  private post(hostname: string, path: string, body: string, headers: Record<string, string>): Promise<string> {
    return new Promise((resolve, reject) => {
      const req = https.request({
        hostname, path, method: 'POST',
        headers: { ...headers, 'Content-Length': Buffer.byteLength(body) },
      }, res => {
        let data = '';
        res.on('data', d => data += d);
        res.on('end', () => resolve(data));
      });
      req.on('error', reject);
      req.write(body);
      req.end();
    });
  }

  private postJson(hostname: string, path: string, body: string, token: string): Promise<string> {
    return this.post(hostname, path, body, {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    });
  }

  private patch(hostname: string, path: string, body: string, token: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const req = https.request({
        hostname, path, method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
      }, res => {
        let data = '';
        res.on('data', d => data += d);
        res.on('end', () => resolve(data));
      });
      req.on('error', reject);
      req.write(body);
      req.end();
    });
  }

  private delete(hostname: string, path: string, token: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const req = https.request({
        hostname, path, method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      }, res => {
        let data = '';
        res.on('data', d => data += d);
        res.on('end', () => resolve(data));
      });
      req.on('error', reject);
      req.end();
    });
  }
}

/** Load credentials from a JSON file path */
export function loadGCalCredentials(filePath: string): GCalCredentials {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require(filePath) as GCalCredentials;
}
