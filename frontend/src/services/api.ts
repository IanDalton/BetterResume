const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

interface ResumeRequestPayload {
  job_description: string;
  format: string;
  model: string;
}

export async function uploadJobsCsv(userId: string, file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/upload-jobs/${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: form
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export async function generateResume(userId: string, payload: ResumeRequestPayload) {
  const res = await fetch(`${API_BASE}/generate-resume/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(`Generate failed: ${res.status}`);
  return res.json() as Promise<{result:any; files:{pdf:string; source:string}}>;
}

export function generateResumeStream(userId: string, payload: ResumeRequestPayload, onEvent: (evt: any)=>void): Promise<{result:any; files?:{pdf:string; source:string}}> {
  // Returns a promise resolving to final result while invoking onEvent per progress event.
  return new Promise((resolve, reject) => {
    // We POST first to initiate SSE because EventSource only supports GET natively; we fallback to fetch+ReadableStream poly.
    // Simpler approach: create a fetch POST to the stream endpoint and manually parse SSE lines.
    fetch(`${API_BASE}/generate-resume-stream/${encodeURIComponent(userId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(res => {
      if (!res.ok || !res.body) { reject(new Error(`Stream failed: ${res.status}`)); return; }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      function pump(): any {
        reader.read().then(({done, value}) => {
          if (done) { return; }
          buffer += decoder.decode(value, {stream: true});
          const parts = buffer.split('\n\n');
            for (let i=0;i<parts.length-1;i++) {
              const line = parts[i].trim();
              if (line.startsWith('data:')) {
                try {
                  const json = JSON.parse(line.slice(5).trim());
                  onEvent(json);
                  if (json.stage === 'done') {
                    resolve({result: json.result, files: json.files});
                  } else if (json.stage === 'error') {
                    reject(new Error(json.message||'Error'));
                  }
                } catch (e) { /* ignore parse errors */ }
              }
            }
            buffer = parts[parts.length-1];
          pump();
        }).catch(err => reject(err));
      }
      pump();
    }).catch(err => reject(err));
  });
}
