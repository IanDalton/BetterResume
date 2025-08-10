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
  return res.json();
}
