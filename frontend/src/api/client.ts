/**
 * API Client for the Personal Assistant Telegram Mini App.
 *
 * Handles authentication (Telegram initData), REST requests, and WebSocket event streaming.
 */

import axios, { AxiosInstance } from 'axios';

export interface EventUpdate {
  event_type: 'started' | 'progress' | 'message' | 'result' | 'error';
  job_id: string;
  payload: Record<string, any>;
}

export interface JobStarted {
  job_id: string;
  kind: string;
}

export class PersonalAssistantAPI {
  private client: AxiosInstance;
  private baseURL: string;
  private initData: string = '';
  private webSocketUrl: string;

  constructor(baseURL: string = 'http://localhost:8000') {
    this.baseURL = baseURL;
    this.webSocketUrl = baseURL.replace('http', 'ws');

    this.client = axios.create({
      baseURL: `${baseURL}/api`,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  /**
   * Initialize with Telegram initData (from WebApp.initData).
   * Must be called before making any API requests.
   */
  setInitData(initData: string): void {
    this.initData = initData;
  }

  /**
   * Get request headers with initData authentication.
   */
  private getHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
    };
  }

  /**
   * Health check.
   */
  async health(): Promise<{ status: string; version: string }> {
    const response = await this.client.get('/health');
    return response.data;
  }

  /**
   * Authenticate with the server using initData.
   */
  async authenticate(): Promise<{ user_id: string; first_name?: string; is_premium: boolean }> {
    const response = await this.client.post(
      '/auth',
      { init_data: this.initData },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Submit an Ask command.
   */
  async ask(query: string, sessionId?: string): Promise<JobStarted> {
    const response = await this.client.post(
      '/ask',
      { query, session_id: sessionId },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Submit a Brainstorm command.
   */
  async brainstorm(text: string, sessionId?: string): Promise<JobStarted> {
    const response = await this.client.post(
      '/brainstorm',
      { text, session_id: sessionId },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Submit a Research command.
   */
  async research(topic: string, depth: 'shallow' | 'normal' | 'deep' = 'normal'): Promise<JobStarted> {
    const response = await this.client.post(
      '/research',
      { topic, depth },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Submit feedback on a recommendation or answer.
   */
  async submitFeedback(
    ref: string,
    verdict: 'accept' | 'reject' | 'correct',
    note?: string
  ): Promise<JobStarted> {
    const response = await this.client.post(
      '/feedback',
      { ref, verdict, note },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Request a citation or knowledge graph.
   */
  async getGraph(kind: 'knowledge' | 'citation' = 'knowledge', topic?: string): Promise<JobStarted> {
    const response = await this.client.post(
      '/graph',
      { kind, topic },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Request user's interests.
   */
  async getInterests(minStrength: number = 0.0): Promise<JobStarted> {
    const response = await this.client.post(
      '/interests',
      { min_strength: minStrength },
      { headers: this.getHeaders() }
    );
    return response.data;
  }

  /**
   * Stream job events via Server-Sent Events (SSE).
   * Returns an async iterator of EventUpdates.
   */
  async *streamEventsSSE(jobId: string): AsyncGenerator<EventUpdate> {
    const url = `${this.baseURL}/api/events/${jobId}`;
    const eventSource = new EventSource(url);

    const promise = new Promise<EventUpdate>((resolve, reject) => {
      eventSource.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data);
          resolve(data);
        } catch (e) {
          reject(e);
        }
      });

      eventSource.addEventListener('error', () => {
        eventSource.close();
        reject(new Error('SSE connection failed'));
      });
    });

    try {
      while (true) {
        yield await promise;
      }
    } finally {
      eventSource.close();
    }
  }

  /**
   * Stream job events via WebSocket.
   * Returns an async iterator of EventUpdates.
   *
   * This is preferred over SSE for better performance and bidirectional communication.
   */
  async *streamEventsWebSocket(jobId: string): AsyncGenerator<EventUpdate> {
    const url = `${this.webSocketUrl}/api/ws/events/${jobId}`;
    const ws = new WebSocket(url);

    let resolve: ((value: EventUpdate) => void) | null = null;
    let reject: ((reason?: any) => void) | null = null;

    ws.addEventListener('open', () => {
      console.log(`WebSocket connected for job ${jobId}`);
    });

    ws.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        if (resolve) {
          resolve(data);
          resolve = null;
        }
      } catch (e) {
        if (reject) {
          reject(e);
          reject = null;
        }
      }
    });

    ws.addEventListener('error', (error) => {
      console.error('WebSocket error:', error);
      if (reject) {
        reject(error);
        reject = null;
      }
    });

    ws.addEventListener('close', () => {
      console.log(`WebSocket closed for job ${jobId}`);
    });

    try {
      while (ws.readyState === WebSocket.OPEN) {
        const promise = new Promise<EventUpdate>((res, rej) => {
          resolve = res;
          reject = rej;
        });

        yield await promise;
      }
    } finally {
      ws.close();
    }
  }
}

// Export a singleton instance
export const api = new PersonalAssistantAPI(
  process.env.REACT_APP_API_URL || 'http://localhost:8000'
);
